from __future__ import annotations
import copy,hashlib,json,math,os,pickle,statistics,tempfile,uuid
from dataclasses import dataclass,field
from pathlib import Path
from typing import Any
from river import compose,linear_model,preprocessing

STAGES=(60,180,300)

def finite(v):
    return isinstance(v,(int,float)) and math.isfinite(v)

def clean(x):
    forbidden={"strict_true","internal_true","strict_label_id","internal_label_id",
               "label","target","reference_finalized_ms","label_mature_ms","candidate_id","symbol"}
    out={}
    for k,v in x.items():
        name=str(k);bare=name.removeprefix("live__")
        if bare in forbidden or bare.startswith(("target_","eval_","future_","post_")):
            continue
        if bare.isdigit() and 81<=int(bare)<=110:
            continue
        if finite(v) and not isinstance(v,bool):
            out[name]=max(-1e9,min(1e9,float(v)))
    return out

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
    evidence:dict[str,Any]=field(default_factory=dict)

class LocalOnlyModel:
    VERSION="HYPE-LOCAL-ONLY-v2-causal-research"
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
        self.frozen_predictor=None
        self.feature_policy="causal_m1_v1"
        self.model_version_id=uuid.uuid4().hex
        self.inference_errors=0
        self.learning_events=set()

    def _inputs(self,x):
        xx=clean(x)
        if getattr(self,"feature_policy","legacy")=="causal_m1_v1":
            return {k:v for k,v in xx.items() if k.startswith(("m1__","seq__"))}
        return xx

    def learn(self,side,stage,x,y,source="history",repeat=1,event_id=None):
        key=(str(side),int(stage))
        if key not in self.models:raise ValueError("unknown side/stage")
        events=getattr(self,"learning_events",set())
        if event_id is not None and (str(event_id),key) in events:return False
        xx=self._inputs(x)
        if not xx:return False
        # Class repetition biases posterior probabilities; legacy repeat argument
        # remains accepted for API compatibility but new causal models train once.
        repeats=1 if getattr(self,"feature_policy","legacy")=="causal_m1_v1" else max(1,int(repeat))
        for _ in range(repeats):
            self.models[key].learn_one(xx,bool(y))
        self.labels[key]+=1
        self.positive[key]+=int(bool(y))
        if source=="live": self.live_labels+=1
        if event_id is not None:
            events.add((str(event_id),key));self.learning_events=events
        return True

    def probability(self,side,stage,x):
        try:
            xx=self._inputs(x)
            if not xx:return .5
            frozen=getattr(self,"frozen_predictor",None)
            if frozen is not None:
                value=float(frozen.probability(xx))
                if not math.isfinite(value) or not 0<=value<=1:
                    raise ValueError("invalid probability from frozen predictor")
                return value
            p=self.models[(str(side),int(stage))].predict_proba_one(xx)
            value=float(p.get(True,p.get(1,0.5)))
            return max(1e-5,min(1-1e-5,value))
        except Exception:
            self.inference_errors=getattr(self,"inference_errors",0)+1
            return 0.5

    def predict(self,side,stage,x):
        before=getattr(self,"inference_errors",0)
        p=self.probability(side,stage,x)
        available=self._inputs(x)
        usable=("m1__retrace_bps" in available and available.get("m1__bar_age_s",float("inf"))<=90
                if getattr(self,"feature_policy","legacy")=="causal_m1_v1" else bool(available))
        key=(str(side),int(stage));threshold=self.thresholds.get(key)
        trained=getattr(self,"frozen_predictor",None) is not None or self.labels.get(key,0)>0
        threshold_valid=finite(threshold) and 0<=float(threshold)<=1
        return p,bool(usable and trained and threshold_valid and getattr(self,"inference_errors",0)==before
                      and p>=float(threshold))

    def make_online_challenger(self):
        """Preserve training memory; independent River challenger can adapt online."""
        challenger=copy.deepcopy(self)
        challenger.frozen_predictor=None
        challenger.model_version_id=uuid.uuid4().hex
        online_threshold=(getattr(self,"history_meta",{}) or {}).get("online_challenger_threshold")
        if finite(online_threshold) and 0<=float(online_threshold)<=1:
            challenger.thresholds={key:float(online_threshold) for key in challenger.thresholds}
        challenger.history_meta=dict(challenger.history_meta,role="online_challenger",
                                     parent_model_version_id=getattr(self,"model_version_id",None))
        return challenger

    def probability_evidence(self,side,stage,x):
        """Expose support/missingness without inventing a per-event confidence CI."""
        probability,accepted=self.predict(side,stage,x)
        frozen=getattr(self,"frozen_predictor",None)
        schemas=[]
        for predictor in (getattr(frozen,"first",None),getattr(frozen,"second",None),frozen):
            if predictor is not None and hasattr(predictor,"features"):
                schemas.extend(predictor.features)
        schema=set(schemas);observed=self._inputs(x)
        missing=sorted(schema-set(observed))
        return {"probability":probability,"accepted":accepted,
                "model_version_id":getattr(self,"model_version_id","legacy-unversioned"),
                "uncertainty_status":"high_small_teacher_sample_requires_forward_validation",
                "trained_stage_rows":self.labels.get((str(side),int(stage)),0),
                "trained_stage_positives":self.positive.get((str(side),int(stage)),0),
                "missing_trained_features":missing,
                "missing_fraction":len(missing)/len(schema) if schema else None,
                "forward_validated":bool(self.history_meta.get("forward_validated",False))}

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
        available=getattr(state,"available_candles",None)
        if callable(available):
            return [{"start_ms":int(b["start_ms"]),**{k:float(b[k]) for k in ("open","high","low","close")}}
                    for b in available("60",int(ts_ms),complete_only=True)
                    if all(finite(b.get(k)) for k in ("open","high","low","close"))]
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
                repeat=1
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
            "model_version_id":getattr(self,"model_version_id","legacy-unversioned"),
            "feature_policy":getattr(self,"feature_policy","legacy"),
            "architecture":getattr(getattr(self,"frozen_predictor",None),"name","river_online_logistic"),
            "inference_errors":getattr(self,"inference_errors",0),
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
        path=Path(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        data=pickle.dumps(self,pickle.HIGHEST_PROTOCOL)
        fd,name=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=path.parent)
        try:
            with os.fdopen(fd,"wb") as f:
                f.write(data);f.flush();os.fsync(f.fileno())
            os.replace(name,path)
            # Runtime bundles additionally protect all files with a generation
            # manifest; this sidecar detects standalone checkpoint corruption.
            checksum=path.with_suffix(path.suffix+".sha256")
            checksum.write_text(hashlib.sha256(data).hexdigest()+"\n",encoding="ascii")
        finally:
            if os.path.exists(name):os.unlink(name)

    @staticmethod
    def load(path:Path):
        path=Path(path);data=path.read_bytes()
        checksum=path.with_suffix(path.suffix+".sha256")
        if checksum.exists() and checksum.read_text(encoding="ascii").strip()!=hashlib.sha256(data).hexdigest():
            raise ValueError("checkpoint SHA256 mismatch")
        # Pickle files are executable: load only trusted local checkpoints.
        obj=pickle.loads(data)
        if not isinstance(obj,LocalOnlyModel): raise TypeError("not LocalOnlyModel")
        if not hasattr(obj,"feature_policy"):obj.feature_policy="legacy"
        if not hasattr(obj,"model_version_id"):obj.model_version_id="legacy-unversioned"
        return obj
