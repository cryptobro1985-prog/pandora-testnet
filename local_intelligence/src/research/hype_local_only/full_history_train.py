"""Fixed-budget training on all saved source channels and dense minute states."""
from __future__ import annotations
import argparse,copy,gzip,hashlib,json,pickle,time
from dataclasses import dataclass,field
from pathlib import Path
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from sklearn.ensemble import HistGradientBoostingClassifier
from threadpoolctl import threadpool_limits
from .full_history_features import FullHistoryFeatures
from .full_history_data import DenseLocalData,SIDE_COLUMNS
from .evaluation import event_metrics,binary_metrics,choose_event_threshold
from .reliability import WriterLock,atomic_json,atomic_bytes,CheckpointStore
from .jepa import stamp,HOUR
from .full_history_model import Head,FullHistoryModel

NAMES=('full_hgb','full_hgb_jepa')
FOLDS=(('2026-10-22','2026-10-23','2026-10-23','2026-10-25'),('2026-10-23','2026-10-25','2026-10-25','2026-10-27'))
EMBARGO=6*HOUR
PARAMS=dict(max_iter=120,max_leaf_nodes=15,min_samples_leaf=60,l2_regularization=20.,learning_rate=.05,class_weight='balanced',early_stopping=False,random_state=20261107)

def file_hash(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def indices(data,side,start,end,mature_end):
    return np.asarray([i for i,r in enumerate(data.meta[side]) if data.y[side][i]>=0 and
        start<=r['snapshot_ts_ms']<end and r['label_mature_ms']<=mature_end],dtype=int)

def calibration(raw,y):
    if not len(y) or len(set(y))<2:return 1.,0.,False
    logit=np.log(np.clip(raw,1e-7,1-1e-7)/np.clip(1-raw,1e-7,1))
    def loss(ab):
        z=ab[0]*logit+ab[1]
        return float(np.mean(np.logaddexp(0,z)-y*z)+.002*(ab[0]-1)**2+.0002*ab[1]**2)
    result=minimize(loss,[1.,0.],method='L-BFGS-B',bounds=[(0.,5.),(-12.,8.)])
    return (float(result.x[0]),float(result.x[1]),True) if result.success else (1.,0.,False)


def latent_matrix(root,features,directory):
    import torch
    from .jepa import MarketSequence,NumericJEPA,Config
    store=CheckpointStore(root/'artifacts/jepa_research/ssl_checkpoint');state=store.load()
    cfg=Config(**state['config']);model=NumericJEPA(cfg);model.load_state_dict(state['model']);model.eval();torch.set_num_threads(2)
    key=file_hash(store.generations/store.active_generation/'bundle.pkl')
    path=directory/'frozen_jepa_latents.npz';meta=directory/'JEPA_LATENT_CACHE.json'
    if path.exists() and meta.exists() and json.loads(meta.read_text()).get('checkpoint_sha256')==key:
        with np.load(path,allow_pickle=False) as c:
            if np.array_equal(c['ends'],features.ends):return c['latent'].copy(),cfg.train_cutoff_ms
    data=MarketSequence(features.minutes).normalize(cfg.train_cutoff_ms,**state['normalization'])
    matrix=np.full((len(features.ends),cfg.latent),np.nan,dtype=np.float32)
    eligible=[i for i,t in enumerate(features.ends) if data.window_ok(i,cfg.context,int(t))]
    with torch.no_grad():
        for start in range(0,len(eligible),256):
            idx=np.asarray(eligible[start:start+256]);matrix[idx]=model.context(data.batch(idx,cfg.context)).numpy()
    np.savez_compressed(path,ends=features.ends,latent=matrix)
    atomic_json(meta,{'checkpoint_sha256':key,'encoder_frozen':True,'training_cutoff_ms':cfg.train_cutoff_ms})
    return matrix,cfg.train_cutoff_ms

def metrics(data,chosen,prob,thresholds,teachers,start,end):
    rows=[];p=[];by_side={};stages={}
    for side in ('LOW','HIGH'):
        ii=chosen[side];rr=[data.meta[side][i] for i in ii];pp=prob[side]
        by_side[side]=event_metrics(rr,pp,thresholds[side],teachers,start,end,side)
        # Side thresholds differ; normalize solely for shared binary event acceptance.
        rows.extend(rr);p.extend([float(v>=thresholds[side]) for v in pp])
        stages[side]=binary_metrics(rr,pp,thresholds[side])
    return {'event':event_metrics(rows,p,.5,teachers,start,end),'LOW':by_side['LOW'],'HIGH':by_side['HIGH'],
            'per_minute':stages,'warning':'minute rows correlated; event recall counts all finalized reference locals'}

def train(root,directory):
    directory.mkdir(parents=True,exist_ok=True);started=time.monotonic()
    features=FullHistoryFeatures(root);source=dict(features.source_hashes)
    labels=root/'artifacts/history_30d_local116/labels.json.gz';source[str(labels.relative_to(root))]=file_hash(labels)
    result_path=directory/'FULL_HISTORY_RESULT.json'
    if result_path.exists():
        prior=json.loads(result_path.read_text())
        if prior['source_hashes']!=source:raise ValueError('changed sources; use separate experiment directory')
        return prior
    data=DenseLocalData.load(root,features.minutes);z,ssl_cutoff=latent_matrix(root,features,directory)
    base={s:np.concatenate([features.features,data.state[s]],1) for s in ('LOW','HIGH')}
    matrices={'full_hgb':base,'full_hgb_jepa':{s:np.concatenate([base[s],z],1) for s in base}}
    report={'schema':'FULL-SAVED-HISTORY-LOCAL-v1','source_hashes':source,'rows':len(features.ends),
        'raw_feature_count':len(features.names),'dense_minutes_used':True,'candidate_population':'causal six-completed-H1 extreme, max300s',
        'target':'finalized alternating strict H1 L6/K2','folds':[],'selected':None,'promoted':False,
        'old_champion_unchanged':True,'real_orders':False,'ssl_encoder_training_cutoff_ms':ssl_cutoff,
        'dataset':{s:{'labelled_states':int(np.sum(data.y[s]>=0)),'positive_states':int(np.sum(data.y[s]==1)),
            'positive_events':len({r['strict_label_id'] for i,r in enumerate(data.meta[s]) if data.y[s][i]==1}),
            'active_states':int(data.active[s].sum())} for s in data.y},'params':PARAMS}
    fitted={};selection={n:[] for n in NAMES}
    for dates in FOLDS:
        a,b,c,d=map(stamp,dates);fold={'boundaries':dates,'models':{}}
        references=[t for t in data.teachers if t.get('reference_finalized_ms') is not None and t['reference_finalized_ms']<=d-EMBARGO]
        for name in NAMES:
            model=FullHistoryModel(name,list(features.names)+list(SIDE_COLUMNS)+([f'jepa_z{i}' for i in range(z.shape[1])] if name.endswith('jepa') else []))
            vv={};probs={};thresholds={};partitions={}
            for side in ('LOW','HIGH'):
                ti=indices(data,side,0,a-EMBARGO,a-EMBARGO);ci=indices(data,side,a,b-EMBARGO,b-EMBARGO);vi=indices(data,side,c,d,d-EMBARGO)
                x=matrices[name][side];clf=HistGradientBoostingClassifier(**PARAMS);clf.fit(x[ti],data.y[side][ti])
                head=Head(clf);head.a,head.b,head.calibrated=calibration(clf.predict_proba(x[ci])[:,1],data.y[side][ci])
                pp=head.score(x[vi]);pp[~data.active[side][vi]]=0
                active=[j for j,i in enumerate(vi) if data.active[side][i]]
                rr=[data.meta[side][vi[j]] for j in active];vp=pp[active]
                head.threshold=choose_event_threshold(rr,vp,[t for t in references if t['side']==side],c,d)
                model.heads[side]=head;vv[side]=vi;probs[side]=pp;thresholds[side]=head.threshold
                partitions[side]={'train':len(ti),'calibration':len(ci),'validation':len(vi),
                    'train_positive':int(data.y[side][ti].sum()),'calibration_positive':int(data.y[side][ci].sum()),
                    'max_train_label_available_ms':max(data.meta[side][i]['label_mature_ms'] for i in ti)}
            summary=metrics(data,vv,probs,thresholds,references,c,d)
            fold['models'][name]={'metrics':summary,'thresholds':thresholds,'partitions':partitions}
            selection[name].append((summary['event']['f1'],-summary['event']['false_events']))
            model.metadata={'role':'evaluated_historical_frozen','fit_available_until_ms':b,
                'threshold_selected_until_ms':d,'independently_calibrated':all(h.calibrated for h in model.heads.values()),
                'source_hashes':source,'forward_validated':False}
            fitted[name]=model
        report['folds'].append(fold);print('FOLD_DONE',dates,flush=True)
    rank={n:tuple(np.mean(np.asarray(v),axis=0)) for n,v in selection.items()}
    selected=max(NAMES,key=lambda n:rank[n]);report['selected']=selected
    report['selection']={n:{'mean_validation_event_f1':float(v[0]),'negative_false_events':float(v[1])} for n,v in rank.items()}
    # Model/threshold choices above are frozen before this historical scoring.
    start,end=stamp('2026-10-27'),stamp('2026-11-03');report['historical_holdout']={}
    for name,model in fitted.items():
        ii={s:indices(data,s,start,end,end) for s in data.y}
        pp={s:model.heads[s].score(matrices[name][s][ii[s]]) for s in data.y}
        for s in pp:pp[s][~data.active[s][ii[s]]]=0
        report['historical_holdout'][name]=metrics(data,ii,pp,{s:h.threshold for s,h in model.heads.items()},data.teachers,start,end)
    prior=json.loads((root/'artifacts/quantum_research/HISTORICAL_TRAINING_REPORT.json').read_text())
    report['old_pipeline_reference']=prior['architectures']['linear_temporal_ensemble']['oos']['event']
    report['comparison_warning']='same dates/teachers, different complete proposal pipelines; historical period previously viewed, not new forward evidence'
    fitted[selected].save(directory/'evaluated/local_analyzer.pkl')
    final=copy.deepcopy(fitted[selected]);cutoff=int(features.ends[-1]);all_indices={}
    for side in ('LOW','HIGH'):
        ii=indices(data,side,0,cutoff+1,cutoff);all_indices[side]=ii
        clf=HistGradientBoostingClassifier(**PARAMS);clf.fit(matrices[selected][side][ii],data.y[side][ii])
        # Fitting all matured labels uses old calibration rows too: never claim
        # that the resulting score retains independent calibration.
        previous=fitted[selected].heads[side]
        final.heads[side]=Head(clf,a=previous.a,b=previous.b,calibrated=False,threshold=previous.threshold)
    final.metadata=dict(final.metadata,role='all_30_day_research_learner',independently_calibrated=False,
        fit_available_until_ms=cutoff,forward_validated=False,
        thresholds_require_forward_revalidation=True,calibration_mapping='transferred_old_fold_not_independent',all_matured_states={s:len(v) for s,v in all_indices.items()})
    final.save(directory/'all_history/local_analyzer.pkl')
    report['full_history_fit']=final.metadata;report['elapsed_seconds']=time.monotonic()-started
    report['next']='independent forward paper validation; raw all-history scores are not calibrated near-certainty'
    atomic_json(result_path,report)
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path('.'));parser.add_argument('--output',type=Path,default=Path('artifacts/full_history_research'));args=parser.parse_args()
    with WriterLock(args.output/'.full_history_writer.lock'),threadpool_limits(limits=2):
        result=train(args.root,args.output);print(json.dumps({'selected':result['selected'],'historical':result['historical_holdout'][result['selected']]['event']}))
if __name__=='__main__':main()
