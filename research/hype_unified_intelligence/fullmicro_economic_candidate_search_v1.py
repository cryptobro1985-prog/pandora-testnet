#!/usr/bin/env python3
"""HYPE FULL-MICRO causal candidate-path economic research, research ONLY.

Exact data/feature search contract:
- 300-second candidate snapshots; first subsequent minute OPEN for paper entry.
- 161 crossed historical L50 books excluded; 121 contiguous minutes required.
- Separate LOW->LONG and HIGH->SHORT heads, not hindsight-confirmed locals.
- Future 60m take-before-stop is TARGET only, never predictive feature.
- Chronological 60/20/20 split with 121-minute label purge.
- Models/families chosen on development, NOT test.
- This is a historical, already-inspected split; result is diagnostic only.
- 12bps roundtrip cost proxy. No verified executable bid/ask/mark liquidation.
"""
from __future__ import annotations
import argparse,zipfile,gzip,json,hashlib,datetime
from collections import Counter
from pathlib import Path
import numpy as np
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import ExtraTreesClassifier,HistGradientBoostingClassifier

ROOT="01_JUL12_AUG07_FULL_MICRO"
EXCLUDE_ABSOLUTE={
 "fullmicro_mark_price_next_funding_time",
 "fullmicro_open_interest_sum_open_interest",
 "fullmicro_open_interest_sum_open_interest_value",
 "fullmicro_ticker_base_asset_volume",
 "fullmicro_ticker_quote_asset_volume",
 "fullmicro_ticker_last_price",
 "fullmicro_ticker_open_price",
 "fullmicro_ticker_price_change",
 "fullmicro_mark_price_index_price",
 "fullmicro_mark_price_mark_price",
}
PURGE_MS=121*60*1000
COST=.0012
MAX_HORIZON=120
TAKE=.0075
STOP=.004
COOLDOWN_MS=30*60000

def finite(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and np.isfinite(v)

def load(master):
    with zipfile.ZipFile(master) as z:
        with gzip.open(z.open(ROOT+"/candidate_snapshots_full_micro.jsonl.gz"),"rt") as inp:
            snaps=[json.loads(l) for l in inp if l.strip()]
        with gzip.open(z.open(ROOT+"/compact_1m.jsonl.gz"),"rt") as inp:
            bars=[json.loads(l) for l in inp if l.strip()]
    return sorted((r for r in snaps if r.get("delay_s")==300),
                  key=lambda r:r["snapshot_ts_ms"]),bars

def feature_families(rows):
    keys=set().union(*(r["features"] for r in rows))
    base=[k for k in sorted(keys) if not k.startswith("fullmicro_") and k!="age_s"]
    price=[k for k in base if not any(token in k for token in
            ("imbalance","flow","eff_","log","count","trade_"))]
    flow=[k for k in base if k not in price]
    book=[k for k in sorted(keys) if k.startswith((
       "fullmicro_book_","fullmicro_spread","fullmicro_bid_","fullmicro_ask_"))]
    liq=[k for k in sorted(keys) if k.startswith((
       "fullmicro_liq_","fullmicro_long_liq_","fullmicro_short_liq_"))]
    oi=[k for k in sorted(keys) if k.startswith("fullmicro_open_interest_")]
    allnames=[k for k in sorted(keys) if k!="age_s" and k not in EXCLUDE_ABSOLUTE]
    return {
      "price":price,"price_flow":price+flow,
      "plus_book":price+flow+book,
      "plus_oi_liq":price+flow+book+liq+oi,
      "all_derived":allnames}

def candidate_events(snap,bars):
    start=np.asarray([r["start_ms"] for r in bars],dtype=np.int64)
    end=np.asarray([r["bar_end_ms"] for r in bars],dtype=np.int64)
    op=np.asarray([r["open"] for r in bars],dtype=float)
    hi=np.asarray([r["high"] for r in bars],dtype=float)
    lo=np.asarray([r["low"] for r in bars],dtype=float)
    close=np.asarray([r["close"] for r in bars],dtype=float)
    gap=np.asarray([r.get("gap",False) for r in bars])
    out=[];bad=Counter()
    for r in snap:
        f=r["features"];spread=f.get("fullmicro_spread_bps")
        if (f.get("fullmicro_book_valid")!=1 or f.get("fullmicro_book_gap_count")!=0
            or not finite(spread) or spread<=0):
            bad["CROSSED_OR_INVALID_BOOK"]+=1;continue
        t=int(r["snapshot_ts_ms"]);i=int(np.searchsorted(start,t,side="left"))
        if i<=0 or i+MAX_HORIZON+1>=len(bars):
            bad["OUT_OF_RANGE"]+=1;continue
        if start[i]<t or start[i]-t>60000:
            bad["INVALID_ENTRY_TIME"]+=1;continue
        if (end[i+MAX_HORIZON]-start[i]!=(MAX_HORIZON+1)*60000
            or gap[i:i+MAX_HORIZON+1].any()
            or (np.diff(start[i:i+MAX_HORIZON+1])!=60000).any()):
            bad["FUTURE_GAP"]+=1;continue
        entry=op[i];s=1 if r["side"]=="LOW" else -1
        if not finite(entry) or entry<=0:
            bad["INVALID_PRICE"]+=1;continue
        result=0;reason="timeout";j=i+59
        for k in range(i,i+60):
            adverse=1-lo[k]/entry if s==1 else hi[k]/entry-1
            favorable=hi[k]/entry-1 if s==1 else 1-lo[k]/entry
            # Conservative OHLC tie order: adverse first
            if adverse>=STOP:reason="stop";j=k;break
            if favorable>=TAKE:result=1;reason="take";j=k;break
        px=(min(op[j],entry*(1-STOP)) if s==1 else
             max(op[j],entry*(1+STOP))) if reason=="stop" else (
             entry*(1+s*TAKE) if reason=="take" else close[j])
        pnl=s*(px/entry-1)-COST
        out.append({"r":r,"f":f,"t":t,"side":s,"index":i,
                    "exit_index":j,"y":result,"pnl":float(pnl),
                    "reason":reason})
    return out,bad,end

def features(events,names):
    return np.asarray([[float(g["f"][k]) if finite(g["f"].get(k))
        else np.nan for k in names] for g in events],dtype=float)

def summary(events,prob,threshold,end):
    trades=[];busy=-10**20
    for g,p in zip(events,prob):
        if g["t"]<busy or p<threshold:continue
        trades.append(g)
        busy=max(g["t"]+COOLDOWN_MS,int(end[g["exit_index"]]))
    if not trades:return {"trades":0,"underlying_pct":0,"max_dd_pct":0}
    ret=np.asarray([g["pnl"] for g in trades])
    eq=np.cumprod(1+ret);peaks=np.maximum.accumulate(np.r_[1,eq])[1:]
    return {
      "trades":len(trades),"wins":int(np.sum(ret>0)),
      "underlying_pct":round(float(100*(eq[-1]-1)),3),
      "max_dd_pct":round(float(100*np.max(1-eq/peaks)),3),
      "profit_factor":(
         round(float(np.sum(ret[ret>0])/-np.sum(ret[ret<0])),3)
         if np.any(ret<0) else None),
      "take_count":sum(g["reason"]=="take" for g in trades)}

def make_model(method):
    if method=="ridge":
        return make_pipeline(
            SimpleImputer(strategy="median",add_indicator=True),
            StandardScaler(),
            LogisticRegression(C=.1,max_iter=500,class_weight="balanced"))
    if method=="trees":
        return make_pipeline(
            SimpleImputer(strategy="median",add_indicator=True),
            ExtraTreesClassifier(n_estimators=120,min_samples_leaf=12,
                 max_features=.6,class_weight="balanced",
                 random_state=42,n_jobs=2))
    return make_pipeline(
        SimpleImputer(strategy="median",add_indicator=True),
        HistGradientBoostingClassifier(max_iter=100,min_samples_leaf=20,
            max_leaf_nodes=7,l2_regularization=20,learning_rate=.05,
            random_state=42))

def study(master):
    snapshots,bars=load(master)
    cohorts,bad,end=candidate_events(snapshots,bars)
    n=len(cohorts);t1=cohorts[int(.6*n)]["t"];t2=cohorts[int(.8*n)]["t"]
    splits={
      "train":[g for g in cohorts if g["t"]<t1-PURGE_MS],
      "dev":[g for g in cohorts if t1<=g["t"]<t2-PURGE_MS],
      "historical_test":[g for g in cohorts if g["t"]>=t2]}
    families=feature_families(snapshots)
    arms={
      "ridge_price_flow":("price_flow","ridge"),
      "ridge_full_derived":("all_derived","ridge"),
      "trees_price_flow":("price_flow","trees"),
      "trees_full_derived":("all_derived","trees"),
      "hgb_price_flow":("price_flow","hgb"),
      "hgb_full_derived":("all_derived","hgb")}
    results={}
    for tag,(group,method) in arms.items():
        names=families[group];p={}
        for split,events in splits.items():p[split]=np.zeros(len(events))
        heads={}
        for side,side_name in ((1,"LONG"),(-1,"SHORT")):
            trs=[g for g in splits["train"] if g["side"]==side]
            X=features(trs,names)
            use=np.isfinite(X).mean(axis=0)>.25
            y=np.asarray([g["y"] for g in trs])
            if np.unique(y).size<2:raise RuntimeError("one-class training "+tag)
            model=make_model(method)
            model.fit(X[:,use],y)
            heads[side_name]={"train":len(trs),"positive":int(y.sum()),
                              "features":int(use.sum())}
            for split,events in splits.items():
                ix=[i for i,g in enumerate(events) if g["side"]==side]
                if ix:
                    pp=model.predict_proba(features([events[i] for i in ix],names)[:,use])[:,1]
                    p[split][ix]=pp
        trials=[]
        for th in (.3,.4,.5,.6,.7,.8):
            m=summary(splits["dev"],p["dev"],th,end)
            score=m["underlying_pct"]-.75*m["max_dd_pct"]
            if m["trades"]<4:score=-1e6
            trials.append((score,th,m))
        feasible=[z for z in trials if z[0]>-1e5]
        best=max(feasible,key=lambda z:z[0]) if feasible else None
        th=best[1] if best else 1.1
        results[tag]={
          "input_family":group,"method":method,"heads":heads,
          "dev_threshold":th,
          "dev":best[2] if best else {"trades":0,"verdict":"ABSTAIN"},
          "historical_test":summary(splits["historical_test"],
                    p["historical_test"],th,end),
          "promotion_allowed":False}
    return {
       "version":"HYPE_FULLMICRO_ECONOMIC_SEARCH_REPLAY_V1",
       "research_only":True,"real_orders":False,
       "archive_sha256":hashlib.sha256(Path(master).read_bytes()).hexdigest(),
       "candidate_count":len(snapshots),"quality_clean_count":n,
       "excluded_by_reason":dict(bad),
       "available_feature_families":{k:len(v) for k,v in families.items()},
       "period_counts":{k:len(v) for k,v in splits.items()},
       "split_ms":{"train_dev":t1,"dev_test":t2,"purge":PURGE_MS},
       "future_target":"60m +75bps before -40bps, STOP priority in same candle",
       "paper_execution":"next minute open, 12bps round trip proxy, 30m cooldown; no verified bid/ask or marks",
       "models":results,
       "verdict":"HISTORICAL_DIAGNOSTIC_ONLY_NO_VERIFIED_TRANSFER",
       "warning":"Previously inspected July test, not untouched OOS. No live promotion."}

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--master",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    result=study(a.master)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps({k:{"dev":v["dev"],
       "test":v["historical_test"]} for k,v in result["models"].items()},
       ensure_ascii=False))
