"""Reproducible discovery / sealed-OOS replay. No trading or network side effects.

Run as: python -m research.hype_local_v5.pipeline --help
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from .data import load_bars, load_snapshots, join_asof, join_historical_oi, provenance, aggregate_raw_trades
from .engine import Config, Engine
from .features import FeatureBuilder
from .evaluation import evaluate
from .labels import structural_labels


def stamp(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)


WARMUP = stamp('2026-10-04')
DISCOVERY = stamp('2026-10-11')
OOS = stamp('2026-10-27')
END = stamp('2026-11-03')  # 2 November inclusive, UTC
LABEL_MARGIN = 2*3_600_000
FOLDS = [(stamp('2026-10-19'),stamp('2026-10-23')),
         (stamp('2026-10-23'),OOS)]


def digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def implementation_manifest():
    root = Path(__file__).parent
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest()
            for name in ('data.py','features.py','engine.py','labels.py','evaluation.py','pipeline.py')}


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w',encoding='utf-8') as handle:
        json.dump(obj,handle,indent=2,allow_nan=False)
        handle.write('\n')


def write_ledger(path, rows):
    """Always retain a machine-readable JSON and a CSV (nested cells are JSON)."""
    path = Path(path)
    write_json(path.with_suffix('.json'), rows)
    keys = sorted({k for row in rows for k in row})
    if not keys:
        keys = ['status']
    with path.with_suffix('.csv').open('w',newline='',encoding='utf-8') as handle:
        writer = csv.DictWriter(handle,fieldnames=keys)
        writer.writeheader()
        writer.writerows({k:json.dumps(v,sort_keys=True) if isinstance(v,(dict,list)) else v for k,v in row.items()} for row in rows)


def coverage(rows, start, end):
    selected = [r for r in rows if start <= r['start_ms'] and r['ts_ms'] <= end]
    intervals = sorted((max(start,r['start_ms']),min(end,r.get('bar_end_ms',r['ts_ms']))) for r in selected)
    duration, cursor = 0,start
    for begin,finish in intervals:
        duration += max(0,finish-max(cursor,begin))
        cursor = max(cursor,finish)
    ratio = duration/(end-start)
    return dict(rows=len(selected),covered_fraction=ratio,
        first_start_ms=selected[0]['start_ms'] if selected else None,
        last_end_ms=selected[-1].get('bar_end_ms',selected[-1]['ts_ms']) if selected else None)


def check_coverage(rows, start, end):
    cov = coverage(rows,start,end)
    if cov['covered_fraction'] < .99 or not rows:
        raise ValueError('insufficient observed coverage; need >=99% of required window: '+json.dumps(cov))
    if cov['first_start_ms'] > start+60000 or cov['last_end_ms'] < end-60000:
        raise ValueError('required start/end boundaries not covered')
    return cov


def replay(rows, config, end_ms=None, retain_trajectory=True):
    engine = Engine(config,retain_trajectory=retain_trajectory,retain_events=False)
    for row in rows:
        if end_ms is not None and row['ts_ms'] > end_ms:
            break
        engine.update(row)
    return engine


def replay_many(rows,configs,end_ms):
    """One causal feature pass, independent state machines for fixed hypotheses."""
    engines=[Engine(c,retain_trajectory=False,retain_events=False) for c in configs]
    builder=FeatureBuilder();previous_end=None
    for row in rows:
        if row['ts_ms']>end_ms:break
        if previous_end is not None and row['start_ms']!=previous_end:
            builder=FeatureBuilder()
        observed=builder.update(row)
        for engine in engines:engine.update(row,observed_features=observed)
        previous_end=row.get('bar_end_ms',row['start_ms']+row['interval_ms'])
    return engines


def ledger_bundle(out, engine, result):
    out.mkdir(parents=True,exist_ok=True)
    for name, values in [('candidates',engine.candidates),('confirmed_locals',engine.confirmed),
                         ('swing_episodes',engine.episodes),('confidence_trajectories',engine.trajectory),
                         ('engine_accepted_candidates',result['accepted']),
                         ('first_accepted_candidates',result['first_accepted']),('false_locals',result['false_locals']),
                         ('missed_locals',result['missed_locals']),('censored',result['censored'])]:
        write_ledger(out/name,values)
    write_json(out/'metrics.json',result['metrics'])


def discover(rows, out, source_manifest):
    """Small predeclared grid; final OOS rows never enter replay or labels."""
    history = [r for r in rows if WARMUP <= r['start_ms'] and r['ts_ms'] <= OOS]
    cov = check_coverage(history,WARMUP,OOS)
    labels, exclusions = structural_labels(history)
    fold_labels = {end:structural_labels([r for r in history if r['ts_ms']<=end])
                   for _,end in FOLDS}
    results = []
    configs = []
    grid=[]
    # Four transparent configurations per family; no learned likelihood claims.
    for family in 'ABCDEF':
        missing=[]
        if family in 'CDEF' and not any(r.get('open_interest') is not None for r in history):
            missing.append('historical_OI')
        if family in 'DF' and not any(r.get('long_liq_notional_60s') is not None for r in history):
            missing.append('historical_liquidations')
        if family in 'EF' and not any(r.get('ask_replenishment_proxy_ratio_60s') is not None or r.get('ask_restored_notional_60s') is not None for r in history):
            missing.append('historical_orderbook')
        if missing:
            results.append(dict(model_family=family,ablation_status='not_evaluated_missing_data',missing_sources=missing,folds=[]))
            continue
        for maturity in (.75,1.25):
            for score in (.65,.80):
                config = Config(model_family=family,maturity_atr=maturity,accept_score=score,
                                require_absorption=family!='A')
                grid.append(config)
    records=[dict(config=asdict(c),folds=[],ablation_status='evaluated') for c in grid]
    for start,end in FOLDS:
        engines=replay_many(history,grid,end)
        eligible_labels=[x for x in fold_labels[end][0] if x['label_available_ms']<=end and
                         x['extreme_interval_start_ms']<end-LABEL_MARGIN]
        for record,engine in zip(records,engines):
            fold=evaluate(engine,history,eligible_labels,start,end-LABEL_MARGIN,fold_labels[end][1])
            record['folds'].append(fold['metrics'])
        del engines
    for config,record in zip(grid,records):
        record.update(accepted=sum(x['accepted'] for x in record['folds']),
                      true=sum(x['true'] for x in record['folds']))
        record['rankable']=all(x['accepted']>0 for x in record['folds'])
        results.append(record);configs.append((config,None,record))
    from .evaluation import wilson
    eligible = [x for x in configs if x[2]['rankable']]
    eligible.sort(key=lambda x:(wilson(x[2]['true'],x[2]['accepted'])[0],
                               x[2]['true'], -x[2]['accepted']),reverse=True)
    selection = dict(status='selected_for_oos' if eligible else 'no_eligible_model',
        selected_config=asdict(eligible[0][0]) if eligible else None,
        selection_basis='maximum pooled Wilson lower bound among configs with decisions in both chronological folds; no calibrated probability claim',
        folds=FOLDS, coverage=cov, source_manifest=source_manifest,
        implementation_manifest=implementation_manifest(),
        interval_ms=sorted({r['interval_ms'] for r in rows}),
        untouched_oos_start_ms=OOS, label_spec='strict L6/K2; ambiguous OHLC hours excluded',
        forward_only_families='C/D/E/F require actual fresh corresponding observations; no synthetic backfill',
        limitations=['heuristic sequential evidence score, not SPRT or fitted likelihood',
                    'small samples cannot establish perfect future precision',
                    'folds compare fixed rules; no within-fold learned model parameters'])
    selection['selection_sha256'] = digest(selection)
    write_json(out/'selection.json',selection)
    write_json(out/'walk_forward_ablation.json',results)
    write_json(out/'label_exclusions.json',exclusions)
    if eligible:
        config,_,_ = eligible[0]
        engine = replay(history,config,OOS)
        eval_labels = [x for x in labels if x['label_available_ms']<=OOS and x['extreme_interval_start_ms']<OOS-LABEL_MARGIN]
        result = evaluate(engine,history,eval_labels,DISCOVERY,OOS-LABEL_MARGIN,exclusions)
        ledger_bundle(out/'discovery',engine,result)
    return selection


def evaluate_oos(rows,out,selection_path,source_manifest):
    selection = json.loads(selection_path.read_text())
    claimed = selection.pop('selection_sha256')
    if digest(selection) != claimed:
        raise ValueError('selection manifest changed; refuse OOS evaluation')
    selection['selection_sha256'] = claimed
    if selection['status']!='selected_for_oos':
        raise ValueError('no model selected on discovery')
    if selection.get('implementation_manifest') != implementation_manifest():
        raise ValueError('research implementation differs from sealed discovery')
    if selection.get('interval_ms') != sorted({r['interval_ms'] for r in rows}):
        raise ValueError('bar interval differs from sealed discovery')
    # Final file's hash must agree with discovery provenance. Separate new data
    # cannot silently masquerade as the same already sealed study.
    if source_manifest != selection['source_manifest']:
        raise ValueError('data provenance differs from sealed discovery manifest')
    check_coverage(rows,WARMUP,END)
    out.mkdir(parents=True,exist_ok=True)
    lock = selection_path.parent/('OOS_CONSUMED_'+claimed+'.json')
    # Reserve BEFORE inspecting OOS outcomes; failed evaluations remain recorded.
    with lock.open('x') as handle:
        json.dump(dict(selection_sha256=claimed,status='evaluation_started',
                       warning='do not tune this study after viewing final outcomes'),handle)
    try:
        history = [r for r in rows if WARMUP<=r['start_ms'] and r['ts_ms']<=END]
        engine = replay(history,Config(**selection['selected_config']),END)
        labels,excluded = structural_labels(history)
        labels = [x for x in labels if x['extreme_interval_start_ms']<END-LABEL_MARGIN]
        result = evaluate(engine,history,labels,OOS,END-LABEL_MARGIN,excluded)
        ledger_bundle(out/'oos',engine,result)
        write_json(out/'oos'/'label_exclusions.json',excluded)
        write_json(lock,dict(selection_sha256=claimed,status='evaluated',metrics=result['metrics']))
        return result['metrics']
    except Exception as error:
        write_json(lock,dict(selection_sha256=claimed,status='failed_consumed',error=str(error)))
        raise


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('mode',choices=['discover','evaluate-oos','forward','prepare-raw'])
    ap.add_argument('--bars',nargs='+',type=Path)
    ap.add_argument('--raw',nargs='+',type=Path)
    ap.add_argument('--raw-end',help='UTC exclusive completeness boundary of last raw archive, ISO date')
    ap.add_argument('--snapshots',type=Path)
    ap.add_argument('--oi',type=Path)
    ap.add_argument('--oi-publication-lag-ms',type=int,default=300000)
    ap.add_argument('--interval-ms',type=int,default=60000)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--selection',type=Path)
    ap.add_argument('--family',choices=list('ABCDEF'),default='B')
    ap.add_argument('--baseline-without-absorption',action='store_true',
                    help='explicitly disable mandatory observed climax/absorption for exploratory forward baseline')
    args = ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    try:
        if args.mode=='prepare-raw':
            if not args.raw or not args.raw_end:
                ap.error('prepare-raw needs --raw and --raw-end (exclusive UTC completeness boundary)')
            rows=[]
            for path in args.raw:
                rows.extend(aggregate_raw_trades(path,interval_ms=args.interval_ms,end_ms=stamp(args.raw_end)))
            # Reader validates overlap/conflicting parts on the subsequent replay.
            write_ledger(args.output/'raw_bars',rows)
            write_json(args.output/'provenance.json',dict(source='raw_executed_trades',
                files=[provenance(p) for p in args.raw], completeness_boundary_ms=stamp(args.raw_end),
                completeness_is_archive_contract_not_independently_verified=True,
                interval_ms=args.interval_ms,rows=len(rows)))
            print(json.dumps({'status':'aggregated_actual_raw_rows','bars':len(rows)}))
            return 0
        if not args.bars:
            ap.error('--bars is required for replay')
        rows = load_bars(args.bars,interval_ms=args.interval_ms)
        manifest = [provenance(p) for p in args.bars]
        if args.oi:
            rows = list(join_historical_oi(rows,args.oi,publication_lag_ms=args.oi_publication_lag_ms))
            manifest.append(dict(**provenance(args.oi),publication_lag_ms=args.oi_publication_lag_ms,
                note='source publication latency assumption; historical cadence 5min, no 30s backfill'))
        if args.snapshots:
            rows = list(join_asof(rows,load_snapshots(args.snapshots)))
            manifest.append(provenance(args.snapshots))
        if args.mode=='discover':
            result = discover(rows,args.output,manifest)
        elif args.mode=='evaluate-oos':
            if args.selection is None:
                ap.error('--selection is required for sealed OOS')
            result = evaluate_oos(rows,args.output,args.selection,manifest)
        else:
            engine = replay(rows,Config(model_family=args.family,
                require_absorption=args.family!='A' and not args.baseline_without_absorption))
            for name,values in [('candidates',engine.candidates),('confirmed_locals',engine.confirmed),
                                ('swing_episodes',engine.episodes),('confidence_trajectories',engine.trajectory)]:
                write_ledger(args.output/name,values)
            result = dict(status='replayed_not_structurally_validated',rows=len(rows),
                accepted=len(engine.confirmed),provenance=manifest,
                warning='forward replay alone supplies no true-local precision without mature offline labels')
        write_json(args.output/'run_status.json',result)
        print(json.dumps(result,indent=2))
        return 0
    except (ValueError,OSError,KeyError) as error:
        status = dict(status='blocked',error=str(error),market_metrics=None,
                      synthetic_data_used=False,oos_evaluated=False)
        write_json(args.output/'run_status.json',status)
        print(json.dumps(status,indent=2))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
