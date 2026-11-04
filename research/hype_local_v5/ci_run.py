"""Run the requested causal research on collected inputs in GitHub Actions."""
from __future__ import annotations
import argparse
import datetime as dt
from dataclasses import asdict
import glob
import json
from pathlib import Path
import traceback

from . import pipeline
from .data import load_bars, provenance, load_snapshots, join_historical_oi


def report(out,status):
    pipeline.write_json(out/'run_status.json',status)
    metrics=status.get('oos_metrics')
    lines=['# HYPE H1 causal study — measured run','',
        'Status: **'+status['status']+'**. No real orders.','',
        '## Data and checks','',
        '```json',json.dumps(status,indent=2),'```','',
        '## Interpretation','',
        'The score is an uncalibrated sequential heuristic; it is not a probability.',
        'A 100% sample precision is not a guarantee of future precision.',
        'The reference is strict offline L6/K2 with same-side collapse; it is not live evidence.',
        'Final OOS was evaluated once only if discovery selected an eligible rule.',
        'Historical OI/book/liquidations are not synthesized. Missing ablations are unmeasured.',
        'Any existing forward artifact was already observed by prior research and is a forward sample, not a new untouched test.',
        'Only outputs with actual counts establish a measurement; absent values mean unmeasured.']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')


def forward(recovered,out):
    files=sorted(recovered.rglob('HYPE_live_microstructure_1s.jsonl')) if recovered.exists() else []
    samples=[]
    for file in files:
        observations=load_snapshots(file)
        samples.append(dict(**provenance(file),snapshots=len(observations),
            duration_seconds=(observations[-1]['ts_ms']-observations[0]['ts_ms'])/1000 if len(observations)>1 else 0,
            snapshots_with_oi=sum(x.get('open_interest') is not None for x in observations),
            snapshots_with_explicit_oi_time=sum(x.get('oi_ts_ms') is not None for x in observations),
            sufficient_six_hour_warmup=bool(observations and observations[-1]['ts_ms']-observations[0]['ts_ms']>=6*3600000)))
    status=dict(status='forward_coverage_audited' if samples else 'forward_data_unavailable',
        files=samples,precision=None,causal_reason='No six-hour raw-price warmup/complete forward reference supplied; coverage alone cannot validate H1 precision',
        no_synthetic_market_data=True)
    report(out,status)
    return 0 if samples else 2


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bars-glob',default='inputs/**/HYPE_micro5s_*.csv.gz')
    ap.add_argument('--recovered',type=Path,default=Path('recovered'))
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--forward-only',action='store_true')
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    if args.forward_only:
        return forward(args.recovered,args.output)
    status=dict(status='started',final_oos_evaluated=False)
    try:
        paths=[Path(x) for x in sorted(glob.glob(args.bars_glob,recursive=True))]
        if not paths:
            raise ValueError('No actual 5-second input parts were collected')
        rows=load_bars(paths,interval_ms=5000)
        sources=[provenance(p) for p in paths]
        status.update(input_files=sources,observed_rows=len(rows),
            coverage=pipeline.coverage(rows,pipeline.WARMUP,pipeline.END))
        # Legitimate public REST collection on the selected Actions runner.
        # Failure is recorded independently; OI is never manufactured.
        from .acquire import fetch_historical_oi
        try:
            oi_path=args.output/'HYPE_oi_5m.csv'
            status['historical_oi']=fetch_historical_oi(dt.date(2026,10,4),dt.date(2026,11,2),oi_path)
            if status['historical_oi']['points']:
                rows=list(join_historical_oi(rows,oi_path))
                sources.append(dict(**provenance(oi_path),publication_lag_ms=300000))
        except Exception as error:
            status['historical_oi']=dict(status='unavailable',error=str(error),observations_synthesized=False)
        # Historical replay uses actual executed-flow bars only. Contemporary
        # forward OI/book snapshots do not overlap October and cannot be backfilled.
        selected=pipeline.discover(rows,args.output,sources)
        status['discovery_selection']=selected
        if selected['status']=='selected_for_oos':
            status['oos_metrics']=pipeline.evaluate_oos(rows,args.output,args.output/'selection.json',sources)
            status.update(status='market_replay_completed',final_oos_evaluated=True)
        else:
            status['status']='no_eligible_model_on_discovery'
        report(args.output,status)
        return 0
    except Exception as error:
        status.update(status='blocked',error=type(error).__name__+': '+str(error),
            traceback=traceback.format_exc(),market_metrics=None)
        report(args.output,status)
        return 2


if __name__=='__main__':raise SystemExit(main())
