"""Two frozen JEPA probes. No Champion retraining or post-OOS selection."""
from __future__ import annotations
import argparse,gzip,json,pickle,time
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import torch
from scipy.optimize import minimize_scalar
from scipy.special import softmax
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from .jepa import Config,MarketSequence,NumericJEPA,digest,stamp,HOUR
from .reliability import CheckpointStore,WriterLock,atomic_json,atomic_bytes
from .evaluation import purged_partition,choose_event_threshold,paired_day_bootstrap
from .train_history import metrics_bundle,describe_partition

NAMES=('jepa_linear','quantum_jepa_linear')
def read_rows(path):
    with gzip.open(path,'rt') as f:return [json.loads(line) for line in f if line.strip()]
@dataclass
class Probe:
    columns:list
    estimator:object
    temperature:float=1.
    def matrix(self,rows):return np.asarray([[r['probe_features'].get(k,np.nan) for k in self.columns] for r in rows])
    def probabilities(self,rows):
        p=self.estimator.predict_proba(self.matrix(rows))
        return softmax(np.log(np.clip(p,1e-8,1))/self.temperature,axis=1)
    def local(self,rows):
        p=self.probabilities(rows);columns={int(c):i for i,c in enumerate(self.estimator.classes_)}
        return np.asarray([p[i,columns[1 if r['side']=='LOW' else 2]] for i,r in enumerate(rows)])
def labels(rows):return np.asarray([0 if not r['strict_true'] else 1 if r['side']=='LOW' else 2 for r in rows])
def fit_probe(rows,calibration):
    columns=sorted({k for r in rows for k in r['probe_features']})
    estimator=make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),
        StandardScaler(),LogisticRegression(C=.05,max_iter=500,random_state=20261107))
    q=Probe(columns,estimator);estimator.fit(q.matrix(rows),labels(rows))
    if set(estimator.classes_)!={0,1,2}:raise ValueError('insufficient classes for LOW/HIGH/CONTINUATION')
    if calibration:
        p=np.clip(estimator.predict_proba(q.matrix(calibration)),1e-8,1);y=labels(calibration)
        def loss(t):return float(-np.log(softmax(np.log(p)/t,axis=1)[np.arange(len(y)),y]).mean())
        result=minimize_scalar(loss,bounds=(.5,5),method='bounded')
        if result.success:q.temperature=float(result.x)
    return q
@torch.no_grad()
def embed(model,data,rows):
    result=[];missing=0
    for row in rows:
        i=data.at(row['snapshot_ts_ms'],model.cfg.context)
        if i is None:missing+=1;continue
        z=model.context(data.batch([i],model.cfg.context)).numpy()[0]
        features={f'z{j}':float(v) for j,v in enumerate(z)}
        features['candidate_side']=1. if row['side']=='LOW' else -1.
        features['candidate_age_s']=float(row['delay_s'])
        result.append(dict(row,latent=features))
    return result,missing

def compare(root,out):
    torch.set_num_threads(2)
    screen=json.loads((out/'JEPA_SCREEN.json').read_text())
    if not screen['screen']['passed']:raise ValueError('SSL screen failed: no probes authorized')
    inputs={name:digest(root/name) for name in (
        'artifacts/history_30d_local116/compact_1m.jsonl.gz',
        'artifacts/quantum_research/causal_candidates.jsonl.gz',
        'artifacts/quantum_research/locked_oos_predictions.jsonl.gz')}
    if (out/'JEPA_COMPARISON.json').exists():
        cached=json.loads((out/'JEPA_COMPARISON.json').read_text())
        if cached.get('inputs')!=inputs:raise ValueError('cached comparison input mismatch')
        return cached
    saved=CheckpointStore(out/'ssl_checkpoint').load();cfg=Config(**saved['config'])
    model=NumericJEPA(cfg);model.load_state_dict(saved['model']);model.eval()
    source=root/'artifacts/history_30d_local116/compact_1m.jsonl.gz'
    if digest(source)!=saved['dataset_sha256']:raise ValueError('minute input hash changed')
    data=MarketSequence.load(source).normalize(cfg.train_cutoff_ms,**saved['normalization'])
    original=read_rows(root/'artifacts/quantum_research/causal_candidates.jsonl.gz')
    rows,missing=embed(model,data,original)
    with gzip.open(root/'artifacts/history_30d_local116/labels.json.gz','rt') as f:teachers=json.load(f)['strict']
    report={'schema':'PANDORA-JEPA-PROBE-v1','predeclared_selection':'maximum mean walk-forward event F1, then minimum Brier',
        'inputs':inputs,'models':{},'folds':[],'encoder_frozen':True,'missing_sequence_rows':missing,
        'representation_training_cutoff_ms':cfg.train_cutoff_ms,'ssl_dataset_sha256':saved['dataset_sha256'],
        'locked_oos_is_historical_not_new_forward':True,'promoted':False,'real_orders':False}
    splits=[('2026-10-22','2026-10-23','2026-10-23','2026-10-25'),
            ('2026-10-23','2026-10-25','2026-10-25','2026-10-27')]
    fitted={};scores={name:[] for name in NAMES}
    for boundaries in splits:
        a,b,c,d=map(stamp,boundaries)
        eligible_teachers=[t for t in teachers if t.get('reference_finalized_ms') is not None and t['reference_finalized_ms']<=d-6*HOUR]
        fold={'boundaries':boundaries,'models':{}}
        for name in NAMES:
            rr=[dict(r,probe_features={**r['latent'],**(r['features'] if name=='quantum_jepa_linear' else {})}) for r in rows]
            train,cal,valid=purged_partition(rr,a,b,c,d)
            probe=fit_probe(train,cal);prob=probe.local(valid)
            threshold=choose_event_threshold(valid,prob,eligible_teachers,c,d)
            metrics=metrics_bundle(valid,prob,threshold,eligible_teachers,c,d)
            fold['models'][name]={'threshold':threshold,'validation':metrics,
                'train':describe_partition(train),'calibration':describe_partition(cal),'selection':describe_partition(valid)}
            scores[name].append((metrics['event']['f1'],metrics['sample']['brier']))
            fitted[name]=(probe,threshold,rr)
        report['folds'].append(fold)
    selection={n:{'mean_event_f1':float(np.mean([a for a,b in s])),
                  'mean_brier':float(np.mean([b for a,b in s]))} for n,s in scores.items()}
    selected=max(NAMES,key=lambda n:(selection[n]['mean_event_f1'],-selection[n]['mean_brier']))
    report.update(selection=selection,selected_challenger=selected)
    # Select before loading and scoring the historical final holdout.
    start,end=stamp('2026-10-27'),stamp('2026-11-03')
    cached=read_rows(root/'artifacts/quantum_research/locked_oos_predictions.jsonl.gz')
    champion={(r['candidate_id'],r['delay_s']):r['probabilities']['linear_temporal_ensemble'] for r in cached}
    baseline_report=json.loads((root/'artifacts/quantum_research/HISTORICAL_TRAINING_REPORT.json').read_text())
    baseline_threshold=baseline_report['architectures']['linear_temporal_ensemble']['threshold']
    all_predictions=[]
    for name,(probe,threshold,rr) in fitted.items():
        oos=[r for r in rr if start<=r['candidate_ts_ms']<end and r['snapshot_ts_ms']<end]
        p=probe.local(oos);base=np.asarray([champion[(r['candidate_id'],r['delay_s'])] for r in oos])
        report['models'][name]={'oos':metrics_bundle(oos,p,threshold,teachers,start,end),
            'champion_on_same_rows':metrics_bundle(oos,base,baseline_threshold,teachers,start,end),
            'paired_day_brier':paired_day_bootstrap(oos,base,p),
            'threshold':threshold,'temperature':probe.temperature,'head_classes':list(map(int,probe.estimator.classes_))}
        blob=pickle.dumps(probe,pickle.HIGHEST_PROTOCOL);atomic_bytes(out/(name+'.pkl'),blob)
        import hashlib
        atomic_bytes(out/(name+'.pkl.sha256'),(hashlib.sha256(blob).hexdigest()+'\n').encode())
        for r,v in zip(oos,p):all_predictions.append({'model':name,'candidate_id':r['candidate_id'],'stage':r['delay_s'],'p_local':float(v)})
    picked=report['models'][selected];j=picked['oos'];q=picked['champion_on_same_rows']
    improvement=(j['event']['f1']>q['event']['f1']+.02 and j['sample']['brier']<=q['sample']['brier']
        and all((j[s]['recall'] or 0)>=(q[s]['recall'] or 0)-.02 for s in ('LOW','HIGH')))
    report['eligible_for_forward_shadow']=bool(improvement)
    report['next']='collect independent forward shadow; champion remains frozen' if improvement else 'STOP scaling: no sufficient Local improvement; keep existing Champion'
    report['negative_result_is_valid']=not improvement
    atomic_json(out/'JEPA_COMPARISON.json',report)
    with gzip.open(out/'PROBE_OOS_PREDICTIONS.jsonl.gz','wt') as f:
        for r in all_predictions:f.write(json.dumps(r)+'\n')
    saved['downstream_heads']={n:str(out/(n+'.pkl')) for n in NAMES};saved['promotion_status']='FORWARD_REQUIRED' if improvement else 'REJECTED_HISTORICAL_GATE'
    CheckpointStore(out/'ssl_checkpoint').save(saved)
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path('.'));p.add_argument('--output',type=Path,default=Path('artifacts/jepa_research'));args=p.parse_args()
    with WriterLock(args.output/'.jepa_writer.lock'):
        result=compare(args.root,args.output);print(json.dumps({'selected':result['selected_challenger'],'eligible':result['eligible_for_forward_shadow'],'next':result['next']}))
if __name__=='__main__':main()
