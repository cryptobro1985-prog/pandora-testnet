"""Portable frozen full-history heads; no training or teacher imports."""
import hashlib,io,pickle
from pathlib import Path
from dataclasses import dataclass,field
import numpy as np
from scipy.special import expit
from .reliability import atomic_bytes

class _LocalModelUnpickler(pickle.Unpickler):
    def find_class(self,module,name):
        # One-time migration of this task's locally trained -m checkpoint.
        if module=='__main__' and name in ('Head','FullHistoryModel'):return globals()[name]
        return super().find_class(module,name)

@dataclass
class Head:
    estimator:object
    a:float=1.
    b:float=0.
    calibrated:bool=False
    threshold:float=.5
    def score(self,x):
        p=np.clip(self.estimator.predict_proba(x)[:,1],1e-7,1-1e-7)
        return expit(self.a*np.log(p/(1-p))+self.b)

@dataclass
class FullHistoryModel:
    name:str
    columns:list
    heads:dict=field(default_factory=dict)
    metadata:dict=field(default_factory=dict)
    def predict(self,side,features,as_of_ms,research_historical=False):
        if as_of_ms<=max(self.metadata['fit_available_until_ms'],self.metadata.get('threshold_selected_until_ms',0)) and not research_historical:
            return {'state':'ABSTAIN','reason':'MODEL_TRAINING_OVERLAPS_QUERY','research_only':True}
        if features.get('candidate_present')!=1:
            return {'state':'CONTINUATION','score':0.,'probability':None,'research_only':True}
        row=np.asarray([[features.get(c,np.nan) for c in self.columns]],dtype=np.float32)
        score=float(self.heads[side].score(row)[0]);valid=self.metadata.get('independently_calibrated',False)
        accepted=score>=self.heads[side].threshold
        return {'state':'LOCAL_FORMING' if accepted else 'CONTINUATION','side':side,'score':score,
            'probability':score if valid else None,'calibration_scope':self.metadata.get('role'),
            'threshold':self.heads[side].threshold,'high_confidence_validated':False,
            'accepted_research_candidate':accepted,'research_only':True,'real_orders':False}
    def save(self,path):
        blob=pickle.dumps(self,pickle.HIGHEST_PROTOCOL);atomic_bytes(path,blob)
        atomic_bytes(Path(str(path)+'.sha256'),(hashlib.sha256(blob).hexdigest()+'\n').encode())
    @classmethod
    def load(cls,path):
        path=Path(path);blob=path.read_bytes()
        if hashlib.sha256(blob).hexdigest()!=Path(str(path)+'.sha256').read_text().strip():raise ValueError('model checksum mismatch')
        result=_LocalModelUnpickler(io.BytesIO(blob)).load()
        if not isinstance(result,cls):raise ValueError('wrong model type')
        return result
