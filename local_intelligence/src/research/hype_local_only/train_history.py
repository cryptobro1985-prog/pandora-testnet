#!/usr/bin/env python3
"""Causal reconstruction, fixed chronological model comparison, research checkpoints.

The final historical holdout is evaluated only after architecture and threshold
selection in this run. Earlier archive reports already used that same period;
this is not an independent new market sample. Live forward evidence is required.
"""
from __future__ import annotations
import argparse,bisect,gzip,hashlib,json,math,os,pickle,platform,statistics,time
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
for _name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ.setdefault(_name,'2')
import numpy as np
from threadpoolctl import threadpool_limits
from research.hype_local_only.model import LocalOnlyModel,STAGES
from research.hype_local_only.temporal import MinuteFeatureIndex,candidate_temporal_features,HOUR
from research.hype_local_only.nonlinear import fit_predictor,FrozenEnsemble,RiverResearchPredictor
from research.hype_local_only.evaluation import (purged_partition,binary_metrics,event_metrics,
    choose_event_threshold,paired_day_bootstrap)
from research.hype_local_v5.labels import completed_hours,structural_labels

def stamp(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()*1000)
TRAIN_END=stamp('2026-10-23');OOS_START=stamp('2026-10-27')
NAMES=('causal_river_logistic','snapshot_linear','snapshot_hist_gradient_boosting',
       'temporal_hist_gradient_boosting','linear_temporal_ensemble')

def load(path):
    opener=gzip.open if str(path).endswith('.gz') else open
    with opener(path,'rt',encoding='utf-8') as handle:
        for line in handle:
            if line.strip():yield json.loads(line)

def write_json(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')

def sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def robust(vals):
    vals=[float(v) for v in vals if isinstance(v,(int,float)) and math.isfinite(v)]
    if not vals:return 0.,1.
    median=statistics.median(vals)
    return median,max(1e-6,1.4826*statistics.median(abs(x-median) for x in vals),abs(median)*.02)

def stats(rows,probs,threshold):return binary_metrics(rows,probs,threshold)

def choose_threshold(rows,probs,stage=300):
    choices=np.unique(np.r_[.01,np.quantile(probs,np.linspace(0,1,51)),1.]) if len(probs) else [.5]
    return float(max(choices,key=lambda t:(binary_metrics(rows,probs,t)['f1'],float(t))))

def build_causal_rows(snapshots,minutes,teachers):
    """Replace leaked archive values and explicitly mature alternating labels."""
    index=MinuteFeatureIndex(minutes)
    hours=completed_hours(minutes);hour_map={r['start_ms']:r for r in hours}
    teacher_by_id={int(t['label_id']):t for t in teachers}
    reproduced,_=structural_labels(minutes)
    normalized=lambda rr:[(t['side'],t['hour_ms'],float(t['extreme_price'])) for t in rr]
    if normalized(reproduced)!=normalized(teachers):
        raise ValueError('strict labels do not reproduce from retained compact history')
    result=[];excluded=Counter();previous=defaultdict(dict)
    for original in sorted(snapshots,key=lambda r:(r['snapshot_ts_ms'],r['candidate_id'])):
        stage=int(original['delay_s'])
        if stage not in STAGES:
            excluded['unused_stage_0_30_600_900']+=1;continue
        h=int(original['candidate_ts_ms'])//HOUR*HOUR
        win=[hour_map.get(h+j*HOUR) for j in range(-6,3)]
        if any(r is None for r in win):
            excluded['missing_teacher_hour']+=1;continue
        past=win[:6];cur=win[6];future=win[7:]
        high=cur['high']>max(r['high'] for r in past) and cur['high']>=max(r['high'] for r in future)
        low=cur['low']<min(r['low'] for r in past) and cur['low']<=min(r['low'] for r in future)
        if high and low:
            excluded['ambiguous_teacher_hour']+=1;continue
        side=original['side'];raw_pivot=high if side=='HIGH' else low
        field='high' if side=='HIGH' else 'low'
        extreme_match=math.isclose(float(original['extreme_price']),float(cur[field]),rel_tol=1e-12,abs_tol=1e-10)
        teacher=teacher_by_id.get(int(original['strict_label_id'])) if original['strict_true'] else None
        if teacher and not teacher.get('reference_finalized'):
            excluded['terminal_uncensored_positive']+=1;continue
        mature=max(h+3*HOUR,max(int(r['available_at_ms']) for r in win))
        if raw_pivot and extreme_match:
            opposite=[t for t in teachers if t['side']!=side and t['hour_ms']>h]
            if not opposite:
                excluded['unfinalized_pivot_run']+=1;continue
            mature=max(mature,int(opposite[0]['label_available_ms']))
        if teacher:mature=max(mature,int(teacher['reference_finalized_ms']))
        features=index.features(side,stage,float(original['extreme_price']),int(original['snapshot_ts_ms']))
        features=candidate_temporal_features(features,previous[original['candidate_id']])
        previous[original['candidate_id']][stage]=features
        if 'm1__retrace_bps' not in features:
            excluded['no_fresh_causal_minute']+=1;continue
        row={k:v for k,v in original.items() if k not in ('features','historical_gap_sources')}
        stop=bisect.bisect_right(index.ends,int(original['snapshot_ts_ms']))
        row.update(features=features,label_mature_ms=mature,event_key=f'{side}:{h}',
                   prediction_ts_ms=int(original['snapshot_ts_ms']),
                   teacher='FINALIZED_ALTERNATING_H1_L6_K2',causal_features=True,
                   feature_source_max_end_ms=index.ends[stop-1])
        result.append(row)
    return result,{'excluded':dict(excluded),'retained_rows':len(result),
        'retained_candidates':len({r['candidate_id'] for r in result}),
        'retained_positive_candidates':len({r['candidate_id'] for r in result if r['strict_true']}),
        'feature_policy':'completed-minute OHLC paths only; original 5s/1m snapshot values discarded',
        'publication_assumption':'exchange bar finalization at bar_end; historical receipt latency unknown',
        'historical_gap_features':'audited separately; not fitted until live parity demonstrated'}

def fit_river(rows,legacy=False):
    model=LocalOnlyModel()
    if legacy:model.feature_policy='legacy'
    for r in sorted(rows,key=lambda r:(r['label_mature_ms'],r['snapshot_ts_ms'])):
        model.learn(r['side'],int(r['delay_s']),r['features'],r['strict_true'],
                    repeat=8 if legacy and r['strict_true'] else 1,event_id=r['candidate_id'])
    return RiverResearchPredictor(model,'archive_river_oversampled' if legacy else 'causal_river_logistic')

def fit_alternatives(train,calibration):
    result={'causal_river_logistic':fit_river(train)}
    for name in NAMES[1:4]:result[name]=fit_predictor(name,train,calibration)
    result[NAMES[-1]]=FrozenEnsemble(result['snapshot_linear'],result['temporal_hist_gradient_boosting'])
    return result

def describe_partition(rows):
    return {'rows':len(rows),'candidates':len({r['candidate_id'] for r in rows}),
        'positive_candidates':len({r['candidate_id'] for r in rows if r['strict_true']}),
        'max_label_mature_ms':max((r['label_mature_ms'] for r in rows),default=None),
        'max_prediction_ms':max((r['snapshot_ts_ms'] for r in rows),default=None)}

def metrics_bundle(rows,probs,threshold,teachers,start,end):
    out={'sample':binary_metrics(rows,probs,threshold),
         'event':event_metrics(rows,probs,threshold,teachers,start,end),'heads':{}}
    for side in ('LOW','HIGH'):
        out[side]=event_metrics(rows,probs,threshold,teachers,start,end,side)
        for stage in STAGES:
            indices=[i for i,r in enumerate(rows) if r['side']==side and int(r['delay_s'])==stage]
            out['heads'][f'{side}_{stage}s']=binary_metrics([rows[i] for i in indices],[probs[i] for i in indices],threshold)
    return out

def feature_effects(rows):
    effects=[]
    for name in sorted({k for r in rows for k in r['features']}):
        pos=[r['features'][name] for r in rows if r['strict_true'] and name in r['features']]
        neg=[r['features'][name] for r in rows if not r['strict_true'] and name in r['features']]
        if len(pos)<3 or len(neg)<3:continue
        median,scale=robust(pos+neg)
        effects.append({'feature':name,'effect':(statistics.median(pos)-statistics.median(neg))/scale,
            'median':median,'scale':scale,'support':len(pos)+len(neg),
            'status':'descriptive training-only; not multiple-testing-corrected evidence'})
    return sorted(effects,key=lambda r:abs(r['effect']),reverse=True)

def latency(predictor,rows):
    timings=[]
    for row in rows[:min(100,len(rows))]:
        start=time.perf_counter();predictor.probabilities([row]);timings.append((time.perf_counter()-start)*1000)
    return {f'p{q}_ms':float(np.percentile(timings,q)) for q in (50,95,99)} if timings else {}

def train_auxiliary_h1(model,minutes,cutoff):
    """Completed-hour raw K2 shadow task; never drives the finalized local signal."""
    hours=completed_hours(minutes)
    for i in range(6,len(hours)-2):
        window=hours[i-6:i+3]
        if any(b['start_ms']!=a['ts_ms'] for a,b in zip(window,window[1:])):continue
        if max(r['available_at_ms'] for r in window)>cutoff:continue
        row=hours[i];past=window[:6];future=window[7:]
        high=row['high']>max(r['high'] for r in past) and row['high']>=max(r['high'] for r in future)
        low=row['low']<min(r['low'] for r in past) and row['low']<=min(r['low'] for r in future)
        if high and low:continue
        for side,target in (('LOW',low),('HIGH',high)):
            x=model._h1_features(hours,i,side)
            if x:
                model.h1_models[side].learn_one(x,bool(target))
                model.h1_labels[side]+=1;model.h1_positive[side]+=int(bool(target))
        model.h1_last_trained_hour_ms=int(row['start_ms'])
    return model

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('snapshots','compact-1m','labels-gz','model-out','memory-out','report-out'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--research-dir',type=Path)
    parser.add_argument('--full-history-research',action='store_true')
    args=parser.parse_args()
    if (args.model_out.parent/'RUNTIME_CURRENT.json').exists():
        raise SystemExit('refusing historical overwrite of live runtime; use a separate challenger directory')
    directory=args.research_dir or args.report_out.parent;directory.mkdir(parents=True,exist_ok=True)
    started=time.perf_counter();originals=list(load(args.snapshots));minutes=list(load(args.compact_1m))
    with gzip.open(args.labels_gz,'rt',encoding='utf-8') as handle:label_data=json.load(handle)
    teachers=label_data['strict'];rows,quality=build_causal_rows(originals,minutes,teachers)
    causal_path=directory/'causal_candidates.jsonl.gz'
    with gzip.open(causal_path,'wt',encoding='utf-8',compresslevel=9) as handle:
        for r in rows:handle.write(json.dumps(r,separators=(',',':'),allow_nan=False)+'\n')
    report={'version':LocalOnlyModel.VERSION,'seed':20261107,'historical_rows':len(originals),
        'dataset_quality':quality,'teacher_events_total':len(teachers),
        'teacher_events_finalized':sum(bool(t.get('reference_finalized')) for t in teachers),
        'internal_teacher_events':len(label_data.get('internal',[])),
        'architecture_selection':'minimum mean walk-forward Brier; ties by PR-AUC; final holdout never selects',
        'purge_embargo_hours':6,'model_candidates':list(NAMES),'walk_forward':[],
        'input_hashes':{str(p):sha256(p) for p in (args.snapshots,args.compact_1m,args.labels_gz)},
        'environment':{'python':platform.python_version(),'threads':2,'numpy':np.__version__},
        'limitations':['Only 76 finalized strict teacher events, one market/month; wide confidence intervals.',
            'Candidate proposals are archive six-hour extremes, not all live dense proposals.',
            'Historical receipt/publication latency unavailable; replay assumes bar finalization at close.',
            'This historical holdout was used by old archive reports; it is not a new independent market period.',
            'No independent live forward evidence or demonstrated Cortex additive gain.',
            'First accepted side/hour suppression requires forward paper verification.']}
    folds=[('2026-10-16','2026-10-18','2026-10-18','2026-10-21'),
        ('2026-10-20','2026-10-22','2026-10-22','2026-10-25'),
        ('2026-10-23','2026-10-25','2026-10-25','2026-10-27')]
    scores=defaultdict(list);pr_scores=defaultdict(list)
    with threadpool_limits(limits=2):
        for boundaries in folds:
            train_end,cal_end,eval_start,eval_end=map(stamp,boundaries)
            train,cal,valid=purged_partition(rows,train_end,cal_end,eval_start,eval_end)
            models=fit_alternatives(train,cal)
            fold={'boundaries':boundaries,'train':describe_partition(train),'calibration':describe_partition(cal),
                  'validation':describe_partition(valid),'models':{}}
            for name,predictor in models.items():
                metric=binary_metrics(valid,predictor.probabilities(valid),.5)
                scores[name].append(metric['brier']);pr_scores[name].append(metric['pr_auc'] or 0.)
                fold['models'][name]={k:metric[k] for k in ('brier','pr_auc','ece')}
            report['walk_forward'].append(fold)
            print('WALK_FORWARD '+json.dumps(fold,separators=(',',':')),flush=True)
        selection={name:{'mean_brier':float(np.mean(scores[name])),'mean_pr_auc':float(np.mean(pr_scores[name]))} for name in NAMES}
        selected=min(NAMES,key=lambda n:(selection[n]['mean_brier'],-selection[n]['mean_pr_auc']))
        report['selection']=selection;report['selected_architecture']=selected
        end=max(r['bar_end_ms'] for r in minutes)
        train,cal,validation=purged_partition(rows,TRAIN_END,stamp('2026-10-25'),stamp('2026-10-25'),OOS_START)
        oos=[r for r in rows if OOS_START<=r['candidate_ts_ms']<end and r['snapshot_ts_ms']<end]
        models=fit_alternatives(train,cal);predictions={};thresholds={};report['architectures']={}
        validation_teachers=[t for t in teachers if t.get('reference_finalized_ms') is not None
                             and t['reference_finalized_ms']<=OOS_START-6*HOUR]
        report['partitions']={k:describe_partition(part) for k,part in (('train',train),('calibration',cal),('threshold_validation',validation),('locked_oos',oos))}
        for name,predictor in models.items():
            vp=predictor.probabilities(validation)
            threshold=choose_event_threshold(validation,vp,validation_teachers,stamp('2026-10-25'),OOS_START)
            thresholds[name]=threshold;op=predictor.probabilities(oos);predictions[name]=op
            report['architectures'][name]={'threshold':threshold,
                'validation':metrics_bundle(validation,vp,threshold,validation_teachers,stamp('2026-10-25'),OOS_START),
                'oos':metrics_bundle(oos,op,threshold,teachers,OOS_START,end),'latency':latency(predictor,oos),
                'gpu_required':False,'api_cost_usd':0.0,
                'checkpoint_pickle_bytes':len(pickle.dumps(predictor,pickle.HIGHEST_PROTOCOL))}
        report['paired_day_bootstrap']={name:paired_day_bootstrap(oos,predictions['causal_river_logistic'],probs)
            for name,probs in predictions.items() if name!='causal_river_logistic'}
        maturity={(r['candidate_id'],r['delay_s']):r['label_mature_ms'] for r in rows}
        old_rows=[dict(r,label_mature_ms=maturity.get((r['candidate_id'],r['delay_s']),int(r['candidate_ts_ms'])+3*HOUR))
            for r in originals if int(r['delay_s']) in STAGES]
        old_train=[r for r in old_rows if r['snapshot_ts_ms']<TRAIN_END-6*HOUR and r['label_mature_ms']<=TRAIN_END-6*HOUR]
        old_valid=[r for r in old_rows if stamp('2026-10-25')<=r['snapshot_ts_ms']<OOS_START]
        old_oos=[r for r in old_rows if OOS_START<=r['snapshot_ts_ms']<end]
        old=fit_river(old_train,legacy=True);oldthreshold=choose_threshold(old_valid,old.probabilities(old_valid))
        report['contaminated_archive_baseline']={'warning':'UNSAFE inputs include future final 5s/1m bar values; not causal evidence',
            'threshold':oldthreshold,'oos_sample':binary_metrics(old_oos,old.probabilities(old_oos),oldthreshold)}
        champion=train_auxiliary_h1(fit_river(train).model,minutes,TRAIN_END-6*HOUR)
        if selected!='causal_river_logistic':champion.frozen_predictor=models[selected]
        champion.thresholds={key:thresholds[selected] for key in champion.thresholds}
        training_cutoff=max(r['label_mature_ms'] for r in train)
        champion.history_meta={'role':'research_champion_requires_forward_validation','training_cutoff_ms':training_cutoff,
            'max_train_available_ms':training_cutoff,'max_calibration_available_ms':max(r['label_mature_ms'] for r in cal),
            'threshold_validated_until_ms':OOS_START,'evaluation_oos_start_ms':OOS_START,
            'teacher':'FINALIZED_ALTERNATING_H1_L6_K2','causal_dataset_sha256':sha256(causal_path),
            'h1_auxiliary_teacher':'RAW_H1_L6_K2_COMPLETED_HOUR_SHADOW_ONLY',
            'causal_reconstruction':True,'causal_input_schema':'completed_minute_ohlc_v1',
            'selected_architecture':selected,'historical_rows':len(originals),'used_stage_rows':len(train),
            'online_challenger_threshold':thresholds['causal_river_logistic'],
            'training_excludes_final_oos':True,'real_orders':False,'forward_validated':False}
        memory={'version':'HYPE-CAUSAL-RELATIONSHIPS-v2','status':'training-only descriptive; independent validation required','heads':{}}
        for side in ('LOW','HIGH'):
            for stage in STAGES:
                rr=[r for r in train if r['side']==side and int(r['delay_s'])==stage]
                memory['heads'][f'{side}_{stage}s']={'top_feature_relationships':feature_effects(rr)[:30],
                    'top_pair_relationships':[],'baseline_positive_rate':sum(r['strict_true'] for r in rr)/max(1,len(rr)),'support':len(rr)}
        champion.relationship_memory=memory
        from research.hype_local_only.reliability import WriterLock
        with WriterLock(args.model_out.parent/'.local_writer.lock'):champion.save(args.model_out)
        champion.make_online_challenger().save(directory/'online_challenger.pkl')
        alternate=fit_river(train).model;alternate.frozen_predictor=models['temporal_hist_gradient_boosting']
        alternate.thresholds={key:thresholds['temporal_hist_gradient_boosting'] for key in alternate.thresholds}
        alternate.history_meta=dict(champion.history_meta,selected_architecture='temporal_hist_gradient_boosting',role='nonlinear_alternative')
        alternate.save(directory/'nonlinear_alternative.pkl')
        linear=fit_river(train).model;linear.frozen_predictor=models['snapshot_linear']
        linear.thresholds={key:thresholds['snapshot_linear'] for key in linear.thresholds}
        linear.history_meta=dict(champion.history_meta,selected_architecture='snapshot_linear',role='preregistered_linear_alternative_not_promoted')
        linear.save(directory/'linear_alternative.pkl')
        if args.full_history_research:
            final_train=[r for r in rows if r['label_mature_ms']<=end-6*HOUR]
            full=train_auxiliary_h1(fit_river(final_train).model,minutes,end-6*HOUR)
            full.history_meta={'role':'full_history_research_only','independent_oos':False,'training_cutoff_ms':max(r['label_mature_ms'] for r in final_train),
                'causal_reconstruction':True,'causal_input_schema':'completed_minute_ohlc_v1','forward_validated':False}
            full.save(directory/'full_history_research_only.pkl')
        write_json(args.memory_out,memory);report['final_model']=champion.report()
        report['heads']={key:{'threshold':thresholds[selected],'oos':value} for key,value in report['architectures'][selected]['oos']['heads'].items()}
        with gzip.open(directory/'locked_oos_predictions.jsonl.gz','wt',encoding='utf-8',compresslevel=9) as handle:
            for i,row in enumerate(oos):
                record={k:row[k] for k in ('candidate_id','side','delay_s','candidate_ts_ms','snapshot_ts_ms','strict_true','strict_label_id','event_key','label_mature_ms')}
                record['probabilities']={name:float(p[i]) for name,p in predictions.items()}
                handle.write(json.dumps(record,separators=(',',':'))+'\n')
    report['elapsed_s']=time.perf_counter()-started
    import resource
    report['peak_process_rss_mib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
    write_json(args.report_out,report)
    print('LOCAL_ONLY_HISTORY='+json.dumps({'selected':selected,'rows':len(rows),'report':str(args.report_out),
        'oos':report['architectures'][selected]['oos']['event']},separators=(',',':')),flush=True)

if __name__=='__main__':main()
