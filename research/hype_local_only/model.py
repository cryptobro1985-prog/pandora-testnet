from __future__ import annotations
import math,pickle
from dataclasses import dataclass,field
from pathlib import Path
from typing import Any
from river import compose,linear_model,preprocessing

STAGES=(60,180,300)

def finite(v):
    return isinstance(v,(int,float)) and math.isfinite(v)

def clean(x):
    return {str(k):max(-1e9,min(1e9,float(v))) for k,v in x.items() if finite(v)}

def classifier():
    return compose.Pipeline(preprocessing.StandardScaler(),linear_model.LogisticRegression(l2=0.001))

@dataclass
class Candidate:
    side:str
    extreme_price:float
    extreme_ts_ms:int
    candidate_id:str
    snapshots:dict[int,dict[str,float]]=field(default_factory=dict)
    probabilities:dict[int,float]=field(default_factory=dict)
    stages_done:set[int]=field(default_factory=set)
    invalidated:bool=False

class LocalOnlyModel:
    VERSION="HYPE-LOCAL-ONLY-v1"
    def __init__(self):
        self.models={(s,h):classifier() for s in ("LOW","HIGH") for h in STAGES}
        self.labels={(s,h):0 for s in ("LOW","HIGH") for h in STAGES}
        self.positive={(s,h):0 for s in ("LOW","HIGH") for h in STAGES}
        self.thresholds={(s,h):0.5 for s in ("LOW","HIGH") for h in STAGES}
        self.history_meta={}
        self.relationship_memory={}
        self.live_labels=0
        self.last_signal=None

    def learn(self,side,stage,x,y,source="history"):
        key=(str(side),int(stage))
        self.models[key].learn_one(clean(x),bool(y))
        self.labels[key]+=1
        self.positive[key]+=int(bool(y))
        if source=="live": self.live_labels+=1

    def probability(self,side,stage,x):
        try:
            p=self.models[(str(side),int(stage))].predict_proba_one(clean(x))
            return float(p.get(True,p.get(1,0.5)))
        except Exception:
            return 0.5

    def predict(self,side,stage,x):
        p=self.probability(side,stage,x)
        return p,p>=float(self.thresholds[(str(side),int(stage))])

    def report(self):
        return {
            "version":self.VERSION,
            "labels":{f"{s}_{h}s":self.labels[(s,h)] for s in ("LOW","HIGH") for h in STAGES},
            "positive":{f"{s}_{h}s":self.positive[(s,h)] for s in ("LOW","HIGH") for h in STAGES},
            "thresholds":{f"{s}_{h}s":self.thresholds[(s,h)] for s in ("LOW","HIGH") for h in STAGES},
            "history_meta":self.history_meta,
            "live_labels":self.live_labels,
            "last_signal":self.last_signal,
        }

    def save(self,path:Path):
        path.parent.mkdir(parents=True,exist_ok=True)
        tmp=path.with_suffix(".tmp")
        with tmp.open("wb") as f:pickle.dump(self,f,pickle.HIGHEST_PROTOCOL)
        tmp.replace(path)

    @staticmethod
    def load(path:Path):
        with path.open("rb") as f:obj=pickle.load(f)
        if not isinstance(obj,LocalOnlyModel): raise TypeError("not LocalOnlyModel")
        return obj
