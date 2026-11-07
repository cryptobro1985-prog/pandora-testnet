"""Full 30-day minute timeline teacher: market state -> HIGH / LOW / NONE.

This is deliberately separate from candidate-only learning. Every completed
minute becomes a supervised example after a causal warm-up. Strict H1 L6/K2
labels are targets only. Features use current/past minute data only.
"""
from __future__ import annotations
import bisect,math
from collections import defaultdict
import numpy as np
from sklearn.ensemble import ExtraTreesClassifier
from research.hype_local_only.feature_discovery import historical_indicator_features

CLASSES=("NONE","LOW","HIGH")

def finite(v):return isinstance(v,(int,float)) and math.isfinite(v)

def label_map(labels):
    out={}
    for z in labels:
        if not z.get("reference_finalized",True):continue
        start=int(z["extreme_interval_start_ms"])
        out[start]=z["side"]
    return out

def build_timeline_rows(minutes,labels):
    minutes=sorted(minutes,key=lambda r:int(r["start_ms"]))
    ends=[int(r["bar_end_ms"]) for r in minutes]
    labs=label_map(labels)
    buys=np.asarray([float(r.get("buy_notional",0) or 0) for r in minutes],dtype=np.float64)
    sells=np.asarray([float(r.get("sell_notional",0) or 0) for r in minutes],dtype=np.float64)
    counts=np.asarray([float(r.get("trade_count",0) or 0) for r in minutes],dtype=np.float64)
    pbuy=np.concatenate([[0.0],np.cumsum(buys)]);psell=np.concatenate([[0.0],np.cumsum(sells)]);pcnt=np.concatenate([[0.0],np.cumsum(counts)])
    closes=np.asarray([float(r["close"]) for r in minutes],dtype=np.float64)
    rows=[]
    for i,r in enumerate(minutes):
        if i<1440:continue
        ts=int(r["bar_end_ms"]);start=int(r["start_ms"]);px=float(r["close"])
        f={}
        for n in (1,3,5,15,30,60,180,360):
            if i<n:continue
            old=closes[i-n]
            if old>0:f[f"timeline_ret_{n}m"]=px/old-1.0
        for n in (1,3,5,15,30,60):
            a=max(0,i-n+1);b=i+1
            bn=float(pbuy[b]-pbuy[a]);sn=float(psell[b]-psell[a]);ct=float(pcnt[b]-pcnt[a]);den=bn+sn
            f[f"timeline_buy_{n}m_log"]=math.log1p(max(0,bn))
            f[f"timeline_sell_{n}m_log"]=math.log1p(max(0,sn))
            f[f"timeline_trade_count_{n}m"]=ct
            if den>0:f[f"timeline_flow_imbalance_{n}m"]=(bn-sn)/den
        for n,name in ((60,"60m"),(360,"6h"),(1440,"24h")):
            q=minutes[i-n+1:i+1]
            hi=max(float(z["high"]) for z in q);lo=min(float(z["low"]) for z in q)
            if hi>lo:f[f"timeline_position_{name}"]=(px-lo)/(hi-lo)
            if lo>0:f[f"timeline_dist_low_{name}_bps"]=(px/lo-1)*10000
            if px>0:f[f"timeline_dist_high_{name}_bps"]=(hi/px-1)*10000
        f["timeline_hour_progress"]=(ts%3_600_000)/3_600_000
        f.update(historical_indicator_features(minutes,ends,ts,"LOW"))
        # Indicator raw values are side-neutral except *_rev. Drop side-specific
        # reverse features here; side class is the target.
        f={k:float(v) for k,v in f.items() if finite(v) and not k.endswith("_rev")}
        rows.append({"ts_ms":ts,"minute_start_ms":start,"label":labs.get(start,"NONE"),"features":f})
    return rows

def schema(train_rows,min_coverage=.98):
    counts=defaultdict(int)
    for r in train_rows:
        for k in r["features"]:counts[k]+=1
    n=max(1,len(train_rows))
    return tuple(sorted(k for k,c in counts.items() if c/n>=min_coverage))

def matrix(rows,names):
    x=np.zeros((len(rows),len(names)),dtype=np.float32)
    for i,r in enumerate(rows):
        f=r["features"]
        for j,k in enumerate(names):
            if k in f:x[i,j]=float(f[k])
    return x

def fit(rows,split_fn,workers=4,all_data=False):
    fitrows=list(rows) if all_data else [r for r in rows if split_fn(r["ts_ms"])=="train"]
    if not fitrows:raise RuntimeError("no timeline fit rows")
    names=schema(fitrows)
    x=matrix(fitrows,names);y=np.asarray([CLASSES.index(r["label"]) for r in fitrows],dtype=np.int64)
    m=ExtraTreesClassifier(n_estimators=700,max_depth=16,min_samples_leaf=2,max_features="sqrt",
                           class_weight="balanced_subsample",n_jobs=max(1,int(workers)),random_state=20261107)
    m.fit(x,y)
    return m,names

def attach_candidate_probabilities(samples,rows,model,names):
    times=[int(r["ts_ms"]) for r in rows]
    cache={}
    for split in samples:
        for z in samples[split]:
            t=int(z["ts"])+int(z["stage"])*1000
            j=bisect.bisect_right(times,t)-1
            if j<0:z["p_timeline"]=0.0;continue
            key=j
            if key not in cache:
                p=model.predict_proba(matrix([rows[j]],names))[0]
                cache[key]={CLASSES[int(cls)]:float(v) for cls,v in zip(model.classes_,p)}
            z["p_timeline"]=cache[key].get(z["side"],0.0)

def classification_metrics(rows,model,names,split_fn,split):
    rr=[r for r in rows if split_fn(r["ts_ms"])==split]
    if not rr:return {}
    pred=model.predict(matrix(rr,names))
    true=np.asarray([CLASSES.index(r["label"]) for r in rr])
    out={"n":len(rr),"locals":int(np.sum(true!=0))}
    for label,idx in (("LOW",1),("HIGH",2)):
        tp=int(np.sum((pred==idx)&(true==idx)));fp=int(np.sum((pred==idx)&(true!=idx)));fn=int(np.sum((pred!=idx)&(true==idx)))
        out[label]={"tp":tp,"fp":fp,"fn":fn,
                    "precision":tp/(tp+fp) if tp+fp else 0.0,
                    "recall":tp/(tp+fn) if tp+fn else 0.0}
    return out
