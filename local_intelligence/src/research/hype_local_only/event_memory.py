"""Durable market cases. Outcomes appear only after their actual maturity clock."""
from pathlib import Path
import numpy as np
from .reliability import CheckpointStore,WriterLock
from .evaluation import wilson

class EventMemory:
    def __init__(self,directory):
        self.directory=Path(directory);self.store=CheckpointStore(self.directory)
        saved=self.store.load()
        self.state=saved or {'schema':1,'cases':[],'vectors':np.empty((0,0),dtype=np.float32),'columns':[],'ids':set()}
    def seed(self,cases,vectors,columns,source_hashes):
        with WriterLock(self.directory/'.case_writer.lock'):
            latest=self.store.load()
            if latest:self.state=latest
            if self.state['cases']:
                if self.state.get('source_hashes')!=source_hashes:raise ValueError('memory sources changed; retain old memory')
                return False
            self.state.update(cases=cases,vectors=np.asarray(vectors,dtype=np.float32),columns=list(columns),
                ids={r['id'] for r in cases},source_hashes=source_hashes)
            self.store.save(self.state);return True
    def add(self,case,vector,as_of_ms):
        if case['label_available_ms']>as_of_ms:raise ValueError('label is not mature')
        with WriterLock(self.directory/'.case_writer.lock'):
            saved=self.store.load()
            if saved:self.state=saved
            if case['id'] in self.state['ids']:return False
            v=np.asarray(vector,dtype=np.float32)
            if v.shape!=(len(self.state['columns']),):raise ValueError('case feature schema mismatch')
            self.state['vectors']=np.concatenate([self.state['vectors'],v[None]],axis=0)
            self.state['cases'].append(case);self.state['ids'].add(case['id'])
            self.store.save(self.state);return True
    def query(self,features,side,as_of_ms,exclude_event_key=None,k=16):
        cases=self.state['cases']
        indices=[i for i,r in enumerate(cases) if r['side']==side and r['label_available_ms']<=as_of_ms
                 and r['event_key']!=exclude_event_key]
        if not indices:return {'state':'INSUFFICIENT_MATURE_CASES','events':0,'probability':None}
        x=np.asarray([features.get(n,np.nan) for n in self.state['columns']],dtype=np.float32)
        matrix=self.state['vectors'][indices]
        # Stats use only eligible past cases, even for a retrospective query.
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',RuntimeWarning)
            med=np.nanmedian(matrix,axis=0);scale=np.nanmedian(np.abs(matrix-med),axis=0)*1.4826
        scale=np.where(np.isfinite(scale)&(scale>1e-5),scale,1.)
        common=np.isfinite(matrix)&np.isfinite(x);count=common.sum(1)
        delta=np.where(common,np.clip((matrix-x)/scale,-10,10),0)
        distance=(delta*delta).sum(1)/np.maximum(count,1)
        distance[count<min(10,len(x))]=np.inf
        picked=[];seen=set()
        for j in np.argsort(distance):
            if not np.isfinite(distance[j]):continue
            case=cases[indices[j]]
            # Distinct stage/candidate examples in one hour are one experiment.
            block=case['event_key']
            if block in seen:continue
            seen.add(block);picked.append(dict(case,distance=float(distance[j])))
            if len(picked)>=k:break
        positives=sum(bool(r['local_true']) for r in picked);n=len(picked)
        return {'state':'PAST_CASE_EVIDENCE' if n else 'INSUFFICIENT_SHARED_FEATURES','events':n,
            'empirical_local_rate':positives/n if n else None,'rate_ci95':wilson(positives,n),
            'probability':None,'interpretation':'neighbor event frequency, not calibrated forecast confidence',
            'cases':picked}

def seed_full_history(root,directory):
    from .full_history_features import FullHistoryFeatures
    from .full_history_data import DenseLocalData,SIDE_COLUMNS
    features=FullHistoryFeatures(root);data=DenseLocalData.load(root,features.minutes)
    memory=EventMemory(Path(directory)/'event_memory');cases=[];vectors=[];seen=set();cutoff=int(features.ends[-1])
    for side in ('LOW','HIGH'):
        for i,r in enumerate(data.meta[side]):
            if not data.active[side][i] or data.y[side][i]<0 or r['label_mature_ms']>cutoff:continue
            key=(r['event_key'],bool(r['strict_true']))
            if key in seen:continue
            seen.add(key);cases.append({'id':f"{r['candidate_id']}:{int(r['strict_true'])}",
                'event_key':r['event_key'],'side':side,'prediction_ts_ms':r['snapshot_ts_ms'],
                'label_available_ms':r['label_mature_ms'],'local_true':bool(r['strict_true']),
                'strict_label_id':r['strict_label_id'],'extreme_price':r['extreme_price']})
            vectors.append(np.r_[features.features[i],data.state[side][i]])
    memory.seed(cases,np.asarray(vectors),list(features.names)+list(SIDE_COLUMNS),features.source_hashes)
    return {'cases':len(memory.state['cases']),'columns':len(memory.state['columns']),
        'unique_positive_locals':len({r['strict_label_id'] for r in memory.state['cases'] if r['local_true']}),
        'used_all_matured_events':True,'normalization_at_query_uses_past_cases_only':True}
