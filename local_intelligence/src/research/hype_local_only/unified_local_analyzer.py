"""Unified research analyzer: evidence, memory and delayed confirmation stay distinct."""
import argparse,gzip,json,math
from pathlib import Path
import numpy as np
from .full_history_model import FullHistoryModel
from .full_history_features import FullHistoryFeatures
from .candidate_memory import CausalExtremeTracker,HOUR,SIDE_COLUMNS
from .event_memory import EventMemory
from .reliability import CheckpointStore,WriterLock,atomic_json

class UnifiedLocalAnalyzer:
    def __init__(self,root,model_path=None,runtime=None):
        self.root=Path(root);directory=self.root/'artifacts/full_history_research'
        self.model=FullHistoryModel.load(model_path or directory/'all_history/local_analyzer.pkl')
        self.memory=EventMemory(directory/'event_memory')
        self.runtime=Path(runtime) if runtime else None
        self.store=CheckpointStore(self.runtime) if self.runtime else None
        saved=self.store.load() if self.store else None
        self.state=saved or {'schema':1,'confirmed_ids':set(),'last_teacher':None,'expected_side':None}
    def accept_teacher(self,teacher,as_of_ms):
        available=teacher.get('reference_finalized_ms')
        if not teacher.get('reference_finalized') or available is None or available>as_of_ms:
            return {'state':'WAITING_FOR_TEACHER','confirmed':False}
        def update():
            if self.store:
                saved=self.store.load()
                if saved:self.state=saved
            key=f"{teacher['side']}:{teacher['hour_ms']}:{teacher['extreme_price']}"
            if key in self.state['confirmed_ids']:return {'state':'ALREADY_CONFIRMED','confirmed':True}
            self.state['confirmed_ids'].add(key);previous=self.state['last_teacher']
            if previous is None or teacher['hour_ms']>previous['hour_ms']:
                self.state['last_teacher']=teacher
                self.state['expected_side']='HIGH' if teacher['side']=='LOW' else 'LOW'
            if self.store:self.store.save(self.state)
            return {'state':'TEACHER_CONFIRMED','confirmed':True,'side':teacher['side'],
                'extreme_price':teacher['extreme_price'],'teacher_available_ms':available,
                'expected_side':self.state['expected_side'],'prediction_accuracy_claim':None,
                'research_only':True,'real_orders':False}
        if self.store:
            with WriterLock(self.runtime/'.analyzer_writer.lock'):return update()
        return update()
    def analyze(self,minutes,aux,as_of_ms,canonical_inputs=None):
        # No target label/evaluation field is passed to either numeric encoder.
        known=[r for r in minutes if int(r['start_ms'])+60000<=as_of_ms
               and int(r.get('received_ts_ms') or int(r['start_ms'])+60000)<=as_of_ms]
        if not known:return {'state':'ABSTAIN','reason':'NO_RECEIVED_COMPLETED_MINUTES','real_orders':False}
        known=sorted(known,key=lambda r:int(r['start_ms']));last_end=int(known[-1]['start_ms'])+60000
        if as_of_ms-last_end>90000:return {'state':'ABSTAIN','reason':'STALE_MINUTE_DATA','real_orders':False}
        features=FullHistoryFeatures.from_records(known,aux)
        values=features.at(as_of_ms)
        tracker=CausalExtremeTracker()
        for row in known:snapshot=tracker.step(row)
        if not snapshot['history_complete']:
            return {'state':'WARMUP','reason':'NEED_SIX_COMPLETE_PAST_H1','real_orders':False}
        scores={}
        clocks=features.source_clocks(as_of_ms)
        missing_sources=[name for name in ('mark','index','oi','funding') if not clocks.get(name,{}).get('observed') or clocks.get(name,{}).get('stale')]
        if values.get('w360m__flow_observed')!=1:missing_sources.append('six_hour_executed_flow')
        for side in ('LOW','HIGH'):
            c=snapshot['candidates'][side]
            extra=dict(zip(SIDE_COLUMNS,[0.,np.nan,np.nan,(as_of_ms//60000%60)/60,np.nan]))
            if c:
                extra.update(candidate_present=1.,candidate_age_s=(as_of_ms-c['candidate_ts_ms'])/1000,
                    retrace_bps=(1 if side=='LOW' else -1)*(known[-1]['close']/c['extreme_price']-1)*10000)
                past=list(tracker.hours)
                bound=min(r['low'] for r in past) if side=='LOW' else max(r['high'] for r in past)
                extra['distance_past_extreme_bps']=(1 if side=='LOW' else -1)*(c['extreme_price']/bound-1)*10000
            vector={**values,**extra}
            score=self.model.predict(side,vector,as_of_ms)
            if c:
                score['candidate']=c
                score['case_memory']=self.memory.query(vector,side,as_of_ms,f"{side}:{c['hour_ms']}")
            scores[side]=score
        # Do not fabricate a single high-certainty verdict by averaging weak experts.
        proposed=[s for s,v in scores.items() if v.get('accepted_research_candidate')]
        supplied=canonical_inputs or {}
        from research.hype_quant.feature_contract import INPUT_IDS,TARGET_IDS
        valid_ids={str(i) for i in INPUT_IDS};forbidden={str(i) for i in TARGET_IDS}
        summary={'contract_points':116,'allowed_predictive_points':86,
            'provided_predictive_points':sum(str(k) in valid_ids for k in supplied),
            'target_fields_excluded':sum(str(k) in forbidden for k in supplied),
            'trained_source_families':['completed candles','executed flow/counts','mark/index','OI','funding'],
            'live_only_untrained':['L50','liquidation stream','receive-latency'],
            'actual_source_clocks':features.source_clocks(as_of_ms)}
        result={'state':'LOCAL_CANDIDATE' if proposed else 'CONTINUATION','candidates':proposed,
            'scores':scores,'expected_side':self.state['expected_side'],'last_teacher':self.state['last_teacher'],
            'high_confidence_decision':None,'confidence_requirement':'independent forward precision/recall gate not met',
            'model_role':self.model.metadata['role'],'as_of_ms':as_of_ms,'feature_coverage':summary,'missing_trained_sources':missing_sources,
            'cortex_evidence':{'role':'numeric evidence and error analysis; no authority to promote',
                'candidate_scores':{s:v.get('score') for s,v in scores.items()},
                'requires_more_evidence':True},'research_only':True,'real_orders':False}
        if missing_sources:result['state']='WATCH_SOURCE_COVERAGE'
        if all(v.get('state')=='ABSTAIN' for v in scores.values()):result['state']='ABSTAIN'
        return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path('.'));p.add_argument('--model',type=Path)
    p.add_argument('--minutes',type=Path,required=True);p.add_argument('--as-of-ms',type=int,required=True);p.add_argument('--aux-dir',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();opener=gzip.open if args.minutes.suffix=='.gz' else open
    with opener(args.minutes,'rt') as f:minutes=[json.loads(line) for line in f if line.strip()]
    aux={}
    if args.aux_dir:
        for key,name in [('mark','mark_1m'),('index','index_1m'),('oi','open_interest_5m'),('funding','funding')]:
            with gzip.open(args.aux_dir/(name+'.jsonl.gz'),'rt') as f:aux[key]=[json.loads(line) for line in f if line.strip()]
    model=UnifiedLocalAnalyzer(args.root,args.model);result=model.analyze(minutes,aux,args.as_of_ms)
    atomic_json(args.output,result);print(json.dumps({'state':result['state'],'output':str(args.output),'real_orders':False}))
if __name__=='__main__':main()
