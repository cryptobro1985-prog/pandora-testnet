from __future__ import annotations
import math,pickle,statistics
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
        self.h1_models={side:classifier() for side in ("LOW","HIGH")}
        self.h1_labels={side:0 for side in ("LOW","HIGH")}
        self.h1_positive={side:0 for side in ("LOW","HIGH")}
        self.h1_thresholds={side:0.5 for side in ("LOW","HIGH")}
        self.h1_last_trained_hour_ms=None
        self.h1_shadow={}

    def learn(self,side,stage,x,y,source="history",repeat=1):
        key=(str(side),int(stage))
        xx=clean(x)
        for _ in range(max(1,int(repeat))):
            self.models[key].learn_one(xx,bool(y))
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

    def _h1_features(self,rows,index,side):
        if index<6 or index>=len(rows):return {}
        cur=rows[index];past=rows[index-6:index]
        if len(past)!=6:return {}
        if any(int(b["start_ms"])!=int(a["start_ms"])+3_600_000 for a,b in zip(past+[cur],(past+[cur])[1:])):
            return {}
        sign=1.0 if side=="LOW" else -1.0
        past_hi=max(float(z["high"]) for z in past);past_lo=min(float(z["low"]) for z in past)
        span=max(past_hi-past_lo,1e-9);rng=max(float(cur["high"])-float(cur["low"]),1e-9)
        closes=[float(z["close"]) for z in past]
        ranges=[max(float(z["high"])-float(z["low"]),1e-9) for z in past]
        out={
            "h1_side":sign,
            "h1_high_break_bps":(float(cur["high"])/max(past_hi,1e-9)-1.0)*10000.0,
            "h1_low_break_bps":(past_lo/max(float(cur["low"]),1e-9)-1.0)*10000.0,
            "h1_extreme_position":((float(cur["low"])-past_lo)/span if side=="LOW" else
                                   (past_hi-float(cur["high"]))/span),
            "h1_body_rev_bps":sign*(float(cur["close"])/max(float(cur["open"]),1e-9)-1.0)*10000.0,
            "h1_range_bps":(float(cur["high"])/max(float(cur["low"]),1e-9)-1.0)*10000.0,
            "h1_close_position":(float(cur["close"])-float(cur["low"]))/rng,
            "h1_upper_wick_share":max(0.0,float(cur["high"])-max(float(cur["open"]),float(cur["close"])))/rng,
            "h1_lower_wick_share":max(0.0,min(float(cur["open"]),float(cur["close"]))-float(cur["low"]))/rng,
            "h1_trend_6_rev_bps":sign*(float(cur["close"])/max(closes[0],1e-9)-1.0)*10000.0,
            "h1_trend_3_rev_bps":sign*(float(cur["close"])/max(closes[-3],1e-9)-1.0)*10000.0,
            "h1_range_vs_prev_mean":rng/max(statistics.mean(ranges),1e-9),
        }
        return clean(out)

    @staticmethod
    def _completed_h1(state,ts_ms):
        rows=[]
        for start in sorted(state.candles.get("60",{})):
            if int(start)+3_600_000>int(ts_ms):continue
            b=state.candles["60"][start]
            if all(finite(b.get(k)) for k in ("open","high","low","close")):
                rows.append({"start_ms":int(start),"open":float(b["open"]),"high":float(b["high"]),
                             "low":float(b["low"]),"close":float(b["close"])})
        return rows

    def train_h1_history(self,state,ts_ms):
        """Train every matured H1 Local in the backfill. K2 future is label-only."""
        rows=self._completed_h1(state,ts_ms)
        if len(rows)<9:return
        last=self.h1_last_trained_hour_ms
        for i in range(6,len(rows)-2):
            row=rows[i]
            if last is not None and int(row["start_ms"])<=int(last):continue
            win=rows[i-6:i+3]
            if any(int(b["start_ms"])!=int(a["start_ms"])+3_600_000 for a,b in zip(win,win[1:])):continue
            past=rows[i-6:i];future=rows[i+1:i+3]
            hi=float(row["high"])>max(float(z["high"]) for z in past) and float(row["high"])>=max(float(z["high"]) for z in future)
            lo=float(row["low"])<min(float(z["low"]) for z in past) and float(row["low"])<=min(float(z["low"]) for z in future)
            if hi and lo:hi=lo=False
            for side,y in (("LOW",lo),("HIGH",hi)):
                x=self._h1_features(rows,i,side)
                if not x:continue
                # H1 positives are rare; moderate oversampling prevents the classifier
                # from learning the trivial "never Local" solution.
                repeat=4 if y else 1
                for _ in range(repeat):self.h1_models[side].learn_one(x,bool(y))
                self.h1_labels[side]+=1;self.h1_positive[side]+=int(bool(y))
            self.h1_last_trained_hour_ms=int(row["start_ms"])
        i=len(rows)-1
        if i>=6:
            lowx=self._h1_features(rows,i,"LOW");highx=self._h1_features(rows,i,"HIGH")
            lp=float(self.h1_models["LOW"].predict_proba_one(lowx).get(True,0.5)) if lowx else 0.5
            hp=float(self.h1_models["HIGH"].predict_proba_one(highx).get(True,0.5)) if highx else 0.5
            self.h1_shadow={"hour_ms":int(rows[i]["start_ms"]),"low_probability":lp,
                            "high_probability":hp,"side":"LOW" if lp>=hp else "HIGH",
                            "confidence":max(lp,hp),"teacher":"H1_L6_K2_STRICT",
                            "future_used_as_input":False}

    def h1_prior(self,side):
        return float((self.h1_shadow or {}).get("low_probability" if side=="LOW" else "high_probability",0.5))

    def relationship_evidence(self,side,stage,x,limit=8):
        head=((self.relationship_memory.get("heads") or {}).get(f"{side}_{stage}s") or {})
        rows=head.get("top_feature_relationships") or []
        supports=[];contradicts=[]
        for r in rows:
            name=r.get("feature");effect=r.get("effect");med=r.get("median")
            if name not in x or not finite(effect) or not finite(med):continue
            ok=(float(x[name])>=float(med)) if float(effect)>0 else (float(x[name])<=float(med))
            item={"feature":name,"value":float(x[name]),"historical_median":float(med),"effect":float(effect)}
            (supports if ok else contradicts).append(item)
        supports.sort(key=lambda z:abs(z["effect"]),reverse=True)
        contradicts.sort(key=lambda z:abs(z["effect"]),reverse=True)
        return {"supports":supports[:limit],"contradicts":contradicts[:limit],
                "pairs":(head.get("top_pair_relationships") or [])[:limit]}

    def report(self):
        return {
            "version":self.VERSION,
            "labels":{f"{s}_{h}s":self.labels[(s,h)] for s in ("LOW","HIGH") for h in STAGES},
            "positive":{f"{s}_{h}s":self.positive[(s,h)] for s in ("LOW","HIGH") for h in STAGES},
            "thresholds":{f"{s}_{h}s":self.thresholds[(s,h)] for s in ("LOW","HIGH") for h in STAGES},
            "history_meta":self.history_meta,
            "live_labels":self.live_labels,
            "last_signal":self.last_signal,
            "h1":{"labels":self.h1_labels,"positive":self.h1_positive,
                  "thresholds":self.h1_thresholds,"shadow":self.h1_shadow,
                  "last_trained_hour_ms":self.h1_last_trained_hour_ms},
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
