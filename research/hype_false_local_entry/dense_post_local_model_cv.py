"""Cross-period causal model for accepting/rejecting dense post-Local core flips.

Signals are emitted label-blind by CausalReversalMachine. Features use only
completed M1 bars available at the signal timestamp. Strict terminal labels are
used offline for event targets, threshold calibration, and scoring only.

Research/paper only. No order execution.
"""
import argparse, gzip, json, math
from bisect import bisect_left
from pathlib import Path
from statistics import median

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.inspection import permutation_importance

from .audit_dense_coverage import read_jsonl
from .causal_sequential_engine import CausalReversalMachine


def ltime(x): return int(x["extreme_interval_start_ms"])
def lprice(x): return float(x["extreme_price"])


def bend(b):
    if b.get("bar_end_ms") is not None: return int(b["bar_end_ms"])
    if b.get("start_ms") is not None: return int(b["start_ms"])+int(b.get("interval_ms",60000))
    return int(b["ts_ms"])


def num(b,k):
    try: return max(0.0,float(b.get(k,0) or 0))
    except (TypeError,ValueError): return 0.0


def load(base,name):
    base=Path(base)
    with gzip.open(base/"labels.json.gz","rt",encoding="utf-8") as f: doc=json.load(f)
    labels=sorted([x for x in doc.get("strict",[]) if x.get("reference_finalized")],key=ltime)
    bars=sorted(list(read_jsonl(base/"compact_1m.jsonl.gz")),key=bend)
    m=CausalReversalMachine(); ev=[]
    for b in bars: ev.extend(m.on_bar(b))
    flips=[s for s in ev if s.core_flip and s.stage in ("HARD_CONFIRMED","ULTRA_CONFIRMED")]
    return {"name":name,"bars":bars,"labels":labels,"flips":flips}


FEATURES=[]


def event_features(bars, idx, s):
    side=s.side; sign=1.0 if side=="LOW" else -1.0
    close=float(bars[idx]["close"]); extreme=float(s.extreme_price)
    d={}
    d["retrace_bps"]=sign*(close/extreme-1.0)*10000.0
    d["score"]=float(s.score)
    d["ultra"]=1.0 if s.stage=="ULTRA_CONFIRMED" else 0.0

    # Locate the causal anchor bar by price, searching backward only.
    anchor_idx=idx
    tol=max(1e-10,abs(extreme)*1e-9)
    for j in range(idx,-1,-1):
        px=float(bars[j]["low"] if side=="LOW" else bars[j]["high"])
        if abs(px-extreme)<=tol:
            anchor_idx=j; break
        if side=="LOW" and px < extreme-tol: break
        if side=="HIGH" and px > extreme+tol: break
    d["anchor_age_min"]=float(idx-anchor_idx)

    for n in (1,3,5,10,15,30):
        j=max(0,idx-n)
        prev=float(bars[j]["close"])
        mv=sign*(close/prev-1.0)*10000.0 if prev>0 else 0.0
        w=bars[j+1:idx+1] if j<idx else [bars[idx]]
        buy=sum(num(x,"buy_notional") for x in w)
        sell=sum(num(x,"sell_notional") for x in w)
        total=buy+sell
        newn=buy if side=="LOW" else sell
        oldn=sell if side=="LOW" else buy
        flow=sign*(buy-sell)/total if total>0 else 0.0
        seq=[float(x["close"]) for x in bars[j:idx+1]]
        signed=[]; ab=[]
        for a,b in zip(seq,seq[1:]):
            rr=sign*(b/a-1.0)*10000.0 if a>0 else 0.0
            signed.append(rr); ab.append(abs(rr))
        fav=sum(max(x,0.0) for x in signed)
        adv=sum(max(-x,0.0) for x in signed)
        d[f"move{n}"]=mv
        d[f"flow{n}"]=flow
        d[f"new_eff{n}"]=fav/max(newn/100000.0,1e-6)
        d[f"old_eff{n}"]=adv/max(oldn/100000.0,1e-6)
        d[f"eff_ratio{n}"]=d[f"new_eff{n}"]/max(d[f"old_eff{n}"],1e-4)
        d[f"persist{n}"]=sum(x>0 for x in signed)/max(1,len(signed))
        d[f"path_eff{n}"]=max(mv,0.0)/max(sum(ab),1e-6)
        d[f"total_notional{n}"]=math.log1p(total)

    # Recent range / volatility context.
    for n in (15,30,60):
        w=bars[max(0,idx-n+1):idx+1]
        hi=max(float(x["high"]) for x in w); lo=min(float(x["low"]) for x in w)
        rb=(hi/lo-1.0)*10000.0 if lo>0 else 0.0
        d[f"range{n}_bps"]=rb
        d[f"retrace_over_range{n}"]=d["retrace_bps"]/max(rb,1e-6)
        rets=[]
        for a,b in zip(w,w[1:]):
            pa=float(a["close"]); pb=float(b["close"])
            rets.append((pb/pa-1.0)*10000.0 if pa>0 else 0.0)
        d[f"vol{n}_bps"]=float(np.std(rets)) if rets else 0.0

    # Pre-extreme impulse and retrace fraction.
    for n in (15,30,60):
        j=max(0,anchor_idx-n)
        pre=float(bars[j]["close"])
        if side=="LOW":
            imp=(pre/extreme-1.0)*10000.0 if extreme>0 else 0.0
        else:
            imp=(extreme/pre-1.0)*10000.0 if pre>0 else 0.0
        d[f"pre_impulse{n}_bps"]=max(0.0,imp)
        d[f"retrace_frac_pre{n}"]=d["retrace_bps"]/max(d[f"pre_impulse{n}_bps"],1e-6)

    # Same-leg / prior-false-attempt proxy: compare current 5m new-side
    # efficiency and path persistence with the strongest burst in prior hour.
    current_eff=d["new_eff5"]; current_path=d["path_eff5"]
    prior_eff=[]; prior_path=[]
    for k in range(max(5,idx-60),max(5,idx-5)):
        p=float(bars[k-5]["close"]); q=float(bars[k]["close"])
        mv=sign*(q/p-1.0)*10000.0 if p>0 else 0.0
        w=bars[k-4:k+1]
        buy=sum(num(x,"buy_notional") for x in w); sell=sum(num(x,"sell_notional") for x in w)
        newn=buy if side=="LOW" else sell
        seq=[float(x["close"]) for x in bars[k-5:k+1]]
        signed=[sign*(b/a-1.0)*10000.0 for a,b in zip(seq,seq[1:]) if a>0]
        eff=sum(max(x,0.0) for x in signed)/max(newn/100000.0,1e-6)
        path=max(mv,0.0)/max(sum(abs(x) for x in signed),1e-6)
        prior_eff.append(eff); prior_path.append(path)
    pe=max(prior_eff) if prior_eff else 0.0
    pp=max(prior_path) if prior_path else 0.0
    d["eff5_vs_prior_max"]=current_eff/max(pe,1e-4)
    d["eff5_minus_prior_max"]=current_eff-pe
    d["path5_vs_prior_max"]=current_path/max(pp,1e-4)

    # Side-independent coding; models are trained separately by signal side.
    return d


def build_events(period):
    bars=period["bars"]; ends=[bend(b) for b in bars]
    labels=period["labels"]; flips=period["flips"]
    rows=[]
    for s in flips:
        i=bisect_left(ends,int(s.ts_ms))
        if i>=len(ends) or ends[i]!=int(s.ts_ms): continue
        # Assign only to completed strict intervals; this is offline target.
        li=None
        for k in range(len(labels)-1):
            if ltime(labels[k]) <= int(s.ts_ms) < ltime(labels[k+1]):
                li=k; break
        if li is None: continue
        local=labels[li]; next_local=labels[li+1]
        f=event_features(bars,i,s)
        rows.append({
            "period":period["name"],"interval":li,"ts_ms":int(s.ts_ms),
            "signal_side":s.side,"target_side":local["side"],
            "y":1 if s.side==local["side"] else 0,
            "lag_ms":int(s.ts_ms)-ltime(local),
            "entry_price":float(s.close),"extreme_price":lprice(local),
            "next_price":lprice(next_local),"features":f,
        })
    return rows


def feature_names(rows):
    names=sorted(set().union(*(r["features"].keys() for r in rows)))
    return names


def matrix(rows,names):
    return np.asarray([[float(r["features"].get(n,0.0) or 0.0) for n in names] for r in rows],dtype=float)


def fit_models(train,names,seed=17):
    models={}
    for side in ("LOW","HIGH"):
        rr=[r for r in train if r["signal_side"]==side]
        X=matrix(rr,names); y=np.asarray([r["y"] for r in rr],dtype=int)
        m=ExtraTreesClassifier(n_estimators=350,max_depth=8,min_samples_leaf=4,
                               max_features="sqrt",class_weight="balanced",
                               random_state=seed,n_jobs=-1)
        m.fit(X,y); models[side]=m
    return models


def score_rows(models,rows,names):
    for side in ("LOW","HIGH"):
        idx=[i for i,r in enumerate(rows) if r["signal_side"]==side]
        if not idx: continue
        X=matrix([rows[i] for i in idx],names)
        p=models[side].predict_proba(X)[:,1]
        for i,v in zip(idx,p): rows[i]["p_terminal"]=float(v)


def eval_seq(rows,thresholds):
    groups={}
    for r in rows: groups.setdefault((r["period"],r["interval"]),[]).append(r)
    accepted=[]
    for key,rr in groups.items():
        rr=sorted(rr,key=lambda x:x["ts_ms"])
        first=next((x for x in rr if x.get("p_terminal",0.0)>=thresholds[x["signal_side"]]),None)
        if first is not None: accepted.append(first)
    true=[r for r in accepted if r["y"]==1]; wrong=[r for r in accepted if r["y"]==0]
    total=len(groups)
    def med(key,vals):
        z=[x[key] for x in vals if x.get(key) is not None]
        return median(z) if z else None
    entry=[]
    remain=[]
    for r in true:
        sign=1.0 if r["target_side"]=="LOW" else -1.0
        entry.append(sign*(r["entry_price"]/r["extreme_price"]-1.0)*10000.0)
        full=sign*(r["next_price"]-r["extreme_price"])
        rem=sign*(r["next_price"]-r["entry_price"])
        if full>0: remain.append(rem/full)
    return {
        "swings":total,"accepted":len(accepted),"true_first":len(true),"wrong_first":len(wrong),
        "no_signal":total-len(accepted),
        "precision":len(true)/len(accepted) if accepted else None,
        "recall":len(true)/total if total else None,
        "median_lag_ms":med("lag_ms",true),
        "median_entry_bps":median(entry) if entry else None,
        "median_remaining":median(remain) if remain else None,
    }


def choose_thresholds(train_rows,targets):
    # Build the threshold frontier once, then select all operating points from it.
    vals=np.linspace(0.40,0.98,15)
    frontier=[]
    for lo in vals:
        for hi in vals:
            th={"LOW":float(lo),"HIGH":float(hi)}
            m=eval_seq(train_rows,th)
            frontier.append((th,m))
    out={}
    for target in targets:
        eligible=[]
        for th,m in frontier:
            if m["accepted"]<20 or m["precision"] is None or m["precision"]+1e-12<target:
                continue
            lag=m["median_lag_ms"] if m["median_lag_ms"] is not None else 1e18
            eligible.append(((m["recall"],m["precision"],-lag),th,m))
        if not eligible:
            out[str(target)]=None
        else:
            _,th,m=max(eligible,key=lambda x:x[0])
            out[str(target)]={"thresholds":th,"train":m}
    eligible=[]
    for th,m in frontier:
        if m["recall"]>=0.50 and m["precision"] is not None:
            eligible.append(((m["precision"],m["recall"]),th,m))
    if eligible:
        _,th,m=max(eligible,key=lambda x:x[0])
        out["best_precision_recall_ge_0.50"]={"thresholds":th,"train":m}
    else:
        out["best_precision_recall_ge_0.50"]=None
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--period",action="append",required=True,help="NAME=DIR")
    p.add_argument("--out",required=True)
    args=p.parse_args()
    periods=[]
    for spec in args.period:
        name,base=spec.split("=",1); periods.append(load(base,name))
    all_rows=[]
    by_period={}
    for per in periods:
        rr=build_events(per); by_period[per["name"]]=rr; all_rows.extend(rr)
    names=feature_names(all_rows)
    folds=[]
    targets=(0.95,0.97,0.98,0.99,1.0)
    for holdout in [p["name"] for p in periods]:
        train=[dict(r) for r in all_rows if r["period"]!=holdout]
        test=[dict(r) for r in all_rows if r["period"]==holdout]
        models=fit_models(train,names)
        score_rows(models,train,names); score_rows(models,test,names)
        selected=choose_thresholds(train,targets)
        for k,v in selected.items():
            if v is not None: v["test"]=eval_seq(test,v["thresholds"])
        folds.append({"holdout":holdout,"selected":selected})
        print("HOLDOUT",holdout,json.dumps(selected,separators=(",",":")))

    # Fit all data only for feature relationship ranking; NOT OOS performance.
    models=fit_models([dict(r) for r in all_rows],names,seed=29)
    importance={}
    for side in ("LOW","HIGH"):
        rr=[r for r in all_rows if r["signal_side"]==side]
        imp=models[side].feature_importances_
        pairs=sorted(zip(names,imp),key=lambda x:x[1],reverse=True)[:20]
        importance[side]=[{"feature":n,"importance":float(v)} for n,v in pairs]
    result={
        "status":"research_only_orders_off",
        "objective":"first accepted signal after strict Local, LOW->LONG HIGH->SHORT",
        "features":names,"folds":folds,"all_data_feature_importance":importance,
        "caveat":"thresholds selected inside each training fold; holdout period never used for that fold selection",
    }
    Path(args.out).write_text(json.dumps(result,indent=2)+"\n")
    print("IMPORTANCE",json.dumps(importance,separators=(",",":")))


if __name__=="__main__":
    main()
