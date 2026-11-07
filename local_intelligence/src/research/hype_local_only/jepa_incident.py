"""Retrospective closed-minute replay, never a claim of faithful live receipt."""
import json,pickle,time
from pathlib import Path
import numpy as np
import torch
from .jepa import Config,MarketSequence,NumericJEPA,diagnostics,digest
from .jepa_probe import Probe
from .reliability import CheckpointStore,atomic_json
from .temporal import MinuteFeatureIndex,candidate_temporal_features
from .model import LocalOnlyModel
from .jepa_research import ErrorMemory

def replay(root=Path('.')):
    root=Path(root);out=root/'artifacts/jepa_research'
    source=json.loads((out/'INCIDENT_SOURCE.json').read_text());cid=source['candidate_id']
    state_path=root/'artifacts/latest_checkpoint/feature_state.pkl'
    with state_path.open('rb') as f:state=pickle.load(f)
    minutes=list(state.candles['1'].values())
    saved=CheckpointStore(out/'ssl_checkpoint').load();model=NumericJEPA(Config(**saved['config']))
    model.load_state_dict(saved['model']);model.eval();torch.set_num_threads(2)
    data=MarketSequence(minutes).normalize(model.cfg.train_cutoff_ms,**saved['normalization'])
    index=MinuteFeatureIndex(minutes)
    comparison=json.loads((out/'JEPA_COMPARISON.json').read_text());probes={}
    for name in ('jepa_linear','quantum_jepa_linear'):
        p=out/(name+'.pkl')
        if digest(p)!=p.with_suffix('.pkl.sha256').read_text().strip():raise ValueError('probe checksum mismatch')
        with p.open('rb') as f:probes[name]=pickle.load(f)
    champion=LocalOnlyModel.load(root/'artifacts/quantum_research/champion/local_only_model.pkl')
    events=[json.loads(line) for line in (root/'artifacts/latest_evidence/LOCAL_EVENTS.jsonl').read_text().splitlines()]
    stages=[e for e in events if e.get('candidate_id')==cid and e.get('event')=='LOCAL_STAGE']
    report={'schema':'PANDORA-HIGH-78.5515-REPLAY-v1','candidate_id':cid,'source_pickle_sha256':digest(state_path),
        'mode':'RETROSPECTIVE_CLOSED_MINUTE_RECONSTRUCTION','original_receipt_times_known':False,
        'limitations':['Archived M1 OHLC exists, but original receipt clocks and subminute tape are absent.',
            'Flow/trade-count inputs are explicitly missing. Availability is assumed at completed-minute end.',
            'This is not the exact live state and is not independent evidence of general detection quality.'],
        'teacher_outcome':False,'expected_side_before_and_after_prediction':'HIGH',
        'superseded_at_ms':source['first_higher_high']['ts_ms'],'new_high':source['first_higher_high']['price'],
        'rows':[],'real_orders':False,'promoted':False}
    previous_snapshots={};previous_latents=[];previous_ts=None
    for event in sorted(stages,key=lambda e:e['ts_ms']):
        ts=event['ts_ms'];stage=event['stage'];i=data.at(ts,model.cfg.context)
        if i is None:
            report['rows'].append({'stage':stage,'reason':'NO_CAUSAL_COMPLETE_CONTEXT','jepa_probabilities':None});continue
        with torch.no_grad():
            z,pred=model(data.batch([i],model.cfg.context));z=z.numpy()[0];pred=pred.numpy()[0]
            targets=[model.target(data.batch([i+h],model.cfg.context)).numpy()[0] for h in model.cfg.horizons]
        d=diagnostics(z,previous_latents[-1] if previous_latents else None,
            previous_latents[-2] if len(previous_latents)>1 else None,predictions=pred,matured_target=targets,
            elapsed_seconds=(ts-previous_ts)/1000 if previous_ts is not None else 1.)
        previous_latents.append(z);previous_ts=ts
        age=(ts-source['chronology'][0]['ts_ms'])/1000
        fx=candidate_temporal_features(index.features('HIGH',age,78.5515,ts),previous_snapshots)
        previous_snapshots[stage]=fx
        latent={f'z{j}':float(v) for j,v in enumerate(z)};latent.update(candidate_side=-1.,candidate_age_s=float(stage))
        probabilities={}
        for name,q in probes.items():
            inputs={**latent,**(fx if name=='quantum_jepa_linear' else {})}
            p=q.probabilities([{'probe_features':inputs}])[0]
            probabilities[name]={str(int(c)):float(p[j]) for j,c in enumerate(q.estimator.classes_)}
        qp=champion.probability('HIGH',stage,fx)
        old_probability=event.get('probability')
        qj=probabilities['quantum_jepa_linear'];error=ErrorMemory(out/'INCIDENT_ERROR_MEMORY.jsonl')
        matured=1794016804001
        error.mature(f'{cid}:{stage}',max(int(time.time()*1000),matured),matured,'CONTINUATION',
            'HIGH' if event.get('accepted') else 'CONTINUATION',
            source['chronology'][0]['ts_ms'],min(e['ts_ms'] for e in stages),
            ts if event.get('accepted') else None,old_probability,qj['2'],d)
        report['rows'].append({'stage':stage,'prediction_ts_ms':ts,'old_quantum_probability':old_probability,
            'old_accepted':event.get('accepted'),'current_frozen_champion_high_probability':qp,
            'jepa_probabilities':probabilities,
            'jepa_decisions':{n:{'local_threshold':comparison['models'][n]['threshold'],
                'would_accept_HIGH':p['2']>=comparison['models'][n]['threshold'],
                'most_probable_class':max(p,key=p.get)} for n,p in probabilities.items()},
            'current_champion_would_accept_HIGH':champion.predict('HIGH',stage,fx)[1],
            'probability_class_map':{'0':'CONTINUATION','1':'LOW','2':'HIGH'},
            'current_champion_jepa_high_disagreement':abs(qp-qj['2']),
            'latent':z.tolist(),'predicted_future_latent':pred.tolist(),
            'diagnostics_evaluation_only':d,'future_target_available_ms':int(data.ends[i+max(model.cfg.horizons)]),
            'feature_source_max_end_ms':int(data.ends[i]),'feature_masks_unknown':['historical_flow','trade_count','original_receipt_latency']})
    atomic_json(out/'INCIDENT_REPLAY.json',report);return report
if __name__=='__main__':
    r=replay();print(json.dumps({'incident':r['candidate_id'],'stages_replayed':len(r['rows']),'mode':r['mode']}))
