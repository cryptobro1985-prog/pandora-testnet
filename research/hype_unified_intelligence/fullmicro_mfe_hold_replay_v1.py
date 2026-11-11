#!/usr/bin/env python3
"""HYPE FULLMICRO trend holding vs MFE recoil — paper research.

Reuses EXACT entry candidate chronology/quality and models from the saved
fullmicro_economic_candidate_search_v1.py; adds two exit variants. Only the
development split chooses a frozen probability threshold.

Future outcome labels are training-only. Next-minute OPEN execution proxy.
Stop priority in each ambiguous OHLC bar. No broker, orders, or live release.
"""
from __future__ import annotations
import argparse,zipfile,gzip,json,hashlib
from pathlib import Path
from collections import Counter
import numpy as np
from research.hype_unified_intelligence.fullmicro_economic_candidate_search_v1 import (
    load,candidate_events,feature_families,features,make_model,
    PURGE_MS,COST,COOLDOWN_MS,
)

STOP=.006
MAX_MIN=180

def trade(g,bars,mode):
    i=g["index"];side=g["side"]
    entry=float(bars[i]["open"])
    op=np.array([x["open"] for x in bars],float)
    high=np.array([x["high"] for x in bars],float)
    low=np.array([x["low"] for x in bars],float)
    close=np.array([x["close"] for x in bars],float)
    buy=np.array([x.get("buy_notional",0) or 0 for x in bars],float)
    sell=np.array([x.get("sell_notional",0) or 0 for x in bars],float)
    end=np.array([x["bar_end_ms"] for x in bars],dtype=np.int64)
    gap=np.array([x.get("gap",False) for x in bars],bool)
    mfe=mae=0.
    for j in range(i,min(len(bars)-1,i+MAX_MIN)+1):
        if j>i and (gap[j] or end[j]-end[j-1]!=60000):
            gross=side*(op[j]/entry-1)
            return dict(net=gross-COST,mfe=mfe,mae=mae,
                        exit_index=j,exit=op[j],reason="GAP_UNVERIFIED")
        adverse=1-low[j]/entry if side==1 else high[j]/entry-1
        favorable=high[j]/entry-1 if side==1 else 1-low[j]/entry
        # No favorable first on a bar that also touches the stop
        if adverse>=STOP:
            px=min(op[j],entry*(1-STOP)) if side==1 else max(op[j],entry*(1+STOP))
            gross=side*(px/entry-1)
            return dict(net=gross-COST,mfe=mfe,mae=max(mae,adverse),
                        exit_index=j,exit=px,reason="HARD_STOP")
        mfe=max(mfe,0.,favorable);mae=max(mae,0.,adverse)
        if (j>=i+5 and j+1<len(bars) and not gap[j+1]
            and end[j+1]-end[j]==60000):
            own=buy if side==1 else sell
            opp=sell if side==1 else buy
            den=np.maximum(1,own[j-2:j+1]+opp[j-2:j+1])
            pressure=(own[j-2:j+1]-opp[j-2:j+1])/den
            opp_streak=int(np.sum(pressure<-.12))
            ret3=side*(close[j]/close[j-3]-1.)
            recoil=max(0.,mfe-side*(close[j]/entry-1))
            if (mode=="flow_confirmed" and mfe>=.005 and opp_streak>=2
                and ret3<-.0015 and recoil>max(.0035,.4*mfe)):
                px=op[j+1];gross=side*(px/entry-1)
                return dict(net=gross-COST,mfe=mfe,mae=mae,
                            exit_index=j+1,exit=px,reason="FLOW_PRICE_TRANSFER_NEXT_OPEN")
            if (mode=="trail_only" and mfe>=.008 and
                recoil>max(.005,.4*mfe)):
                px=op[j+1];gross=side*(px/entry-1)
                return dict(net=gross-COST,mfe=mfe,mae=mae,
                            exit_index=j+1,exit=px,reason="TRAIL_NEXT_OPEN")
    j=min(len(bars)-1,i+MAX_MIN)
    gross=side*(close[j]/entry-1)
    return dict(net=gross-COST,mfe=mfe,mae=mae,
                exit_index=j,exit=close[j],reason="MAX_HOLD_MARK_UNVERIFIED")

def replayer(events,probs,threshold,mode,bars,end):
    trades=[];next_allowed=-10**18
    for g,p in zip(events,probs):
        if g["t"]<next_allowed or p<threshold:continue
        tr=trade(g,bars,mode)
        trades.append({"timestamp_ms":g["t"],"direction":"LONG" if g["side"]==1 else "SHORT",
                       **tr})
        next_allowed=max(g["t"]+COOLDOWN_MS,int(end[tr["exit_index"]]))
    if not trades:return {"trades":0,"underlying_pct":0,"maxdd_pct":0,"median_capture":None},[]
    rets=np.asarray([t["net"] for t in trades])
    eq=np.cumprod(1+rets);peak=np.maximum.accumulate(np.r_[1,eq])[1:]
    captures=[t["net"]/(t["mfe"]+1e-6) for t in trades if t["mfe"]>0]
    return {
        "trades":len(trades),"wins":int(sum(rets>0)),
        "underlying_pct":round(float(100*(eq[-1]-1)),3),
        "maxdd_pct":round(float(100*np.max(1-eq/peak)),3),
        "median_capture":round(float(np.median(captures)),3) if captures else None,
        "median_mfe_pct":round(float(np.median([t["mfe"] for t in trades])*100),3),
        "median_mae_pct":round(float(np.median([t["mae"] for t in trades])*100),3),
        "exit_reasons":dict(Counter(t["reason"] for t in trades))
    },trades

def study(master):
    snap,bars=load(master)
    candidates,bad,end=candidate_events(snap,bars)
    n=len(candidates);t1=candidates[int(.6*n)]["t"];t2=candidates[int(.8*n)]["t"]
    splits={
        "train":[g for g in candidates if g["t"]<t1-PURGE_MS],
        "dev":[g for g in candidates if t1<=g["t"]<t2-PURGE_MS],
        "historical_test":[g for g in candidates if g["t"]>=t2]}
    fam=feature_families(snap)
    out={}
    for group in ("price_flow","all_derived"):
        names=fam[group];p={k:np.zeros(len(v)) for k,v in splits.items()}
        for side in (1,-1):
            rr=[g for g in splits["train"] if g["side"]==side]
            X=features(rr,names)
            usable=np.isfinite(X).mean(axis=0)>.25
            model=make_model("hgb")
            model.fit(X[:,usable],[g["y"] for g in rr])
            for split,ss in splits.items():
                ix=[i for i,g in enumerate(ss) if g["side"]==side]
                if ix:
                    p[split][ix]=model.predict_proba(
                        features([ss[i] for i in ix],names)[:,usable])[:,1]
        for mode in ("flow_confirmed","trail_only"):
            choices=[]
            for th in (.3,.4,.5,.6,.7):
                dev,_=replayer(splits["dev"],p["dev"],th,mode,bars,end)
                score=(dev["underlying_pct"]-.7*dev["maxdd_pct"]
                       if dev["trades"]>=4 else -1e6)
                choices.append((score,th,dev))
            feasible=[x for x in choices if x[0]>-1e5]
            best=max(feasible,key=lambda x:x[0]) if feasible else None
            th=best[1] if best else 1.1
            test,trades=replayer(splits["historical_test"],
                       p["historical_test"],th,mode,bars,end)
            out[group+"/"+mode]={
              "threshold_dev_only":th,
              "development":best[2] if best else {"trades":0,"verdict":"ABSTAIN"},
              "historical_test":test,
              "historical_test_trades":trades,
              "accepted_for_live":False}
    return {
      "version":"HYPE-FULLMICRO-MFE-HOLD-REPLAY-v1",
      "master_sha256":hashlib.sha256(Path(master).read_bytes()).hexdigest(),
      "candidate_count":len(snap),"clean_count":len(candidates),
      "exclusions":dict(bad),
      "split_counts":{k:len(v) for k,v in splits.items()},
      "cost":"12bps roundtrip proxy, next-minute OPEN, 60bps emergency underlying stop",
      "limitations":["Historical July already inspected",
                     "Not executable bid/ask/mark-price tick replay",
                     "Stop gaps are estimates; cannot guarantee no liquidation",
                     "Development returns must be positive with sufficient events before promotion",
                     "MFE path uses bars up to exit, not hindsight theoretical max"],
      "arms":out,"research_only":True,"real_orders":False,
      "verdict":"NO_UNTOUCHED_PROFITABLE_ENTRY_EXIT_EDGE_ESTABLISHED"}
if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--master",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    r=study(a.master)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(r,indent=2,allow_nan=False)+"\n")
    print(json.dumps({k:{"development":v["development"],
      "historical_test":v["historical_test"]} for k,v in r["arms"].items()}))
