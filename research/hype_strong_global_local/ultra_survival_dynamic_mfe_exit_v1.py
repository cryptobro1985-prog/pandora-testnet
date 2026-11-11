#!/usr/bin/env python3
"""Frozen Ultra Survival V2 + dynamic MFE HOLD/CLOSE/FLIP research.

Detector is never retuned. Exit parameters are selected only on JUL_AUG,
AUG_SEP, SEP_OCT; OCT_NOV is scored after the selection. MAY is reported
separately as an earlier sealed-detector diagnostic, not used for exit choice.

No future teacher/local label enters runtime decisions. Signals come only from
frozen Ultra Survival V2. Dynamic exit uses observed price, MFE and optionally
completed-minute public-trade flow. Emergency stop is paper-only OHLC proxy.
"""
from __future__ import annotations
import argparse,bisect,json,itertools,math,statistics
from pathlib import Path
from research.hype_local_only.replay_ultra_survival_v2 import replay,read_jsonl_gz

COST=.0012
DEV=("JUL_AUG","AUG_SEP","SEP_OCT")
TEST="OCT_NOV"

def q(v,p):
    if not v:return None
    z=sorted(v);x=(len(z)-1)*p;i=int(x);j=min(i+1,len(z)-1);w=x-i
    return z[i]*(1-w)+z[j]*w

def signals(compact,labels):
    bars=read_jsonl_gz(compact);score=replay(compact,labels)
    starts=[int(b["start_ms"]) for b in bars]
    sig=[]
    for r in score["episode_rows"]:
        if not r.get("accepted"):continue
        i=bisect.bisect_left(starts,int(r["signal_ts_ms"]))
        if i>=len(bars):continue
        sig.append({"i":i,"ts":starts[i],"side":1 if r["side"]=="LOW" else -1,
                    "side_name":r["side"],"true":bool(r.get("true_first"))})
    return bars,score,sorted(sig,key=lambda x:x["i"])

def simulate(bars,sig,par):
    stop,activation,floor,fraction,confirm,use_flow=par
    sig_by_i={}
    for s in sig:sig_by_i.setdefault(s["i"],[]).append(s)
    pos=None;trades=[];pending_exit=None;opp_streak=0
    for i,b in enumerate(bars):
        if pending_exit and i>=pending_exit["i"] and pos is not None:
            px=float(b["open"]);sign=pos["side"];gross=sign*(px/pos["entry"]-1)
            trades.append({**pos,"exit_i":i,"exit":px,"gross":gross,
                           "net":gross-COST,"reason":pending_exit["reason"]})
            pos=None;pending_exit=None;opp_streak=0

        # Opposite confirmed signal is the highest-priority causal flip.
        for s in sig_by_i.get(i,[]):
            if pos is not None and s["side"]!=pos["side"]:
                px=float(b["open"]);sign=pos["side"];gross=sign*(px/pos["entry"]-1)
                trades.append({**pos,"exit_i":i,"exit":px,"gross":gross,
                               "net":gross-COST,"reason":"OPPOSITE_ULTRA_FLIP"})
                pos=None;pending_exit=None;opp_streak=0
            if pos is None:
                px=float(b["open"])
                if px>0:
                    pos={"entry_i":i,"entry":px,"side":s["side"],"signal_true":s["true"],
                         "mfe":0.0,"mae":0.0,"max_recoil":0.0}
            # same-side signal while already positioned: HOLD, not pyramid.

        if pos is None:continue
        if bool(b.get("gap",False)):
            if i+1<len(bars):
                pending_exit={"i":i+1,"reason":"DATA_GAP_NEXT_OPEN"}
            continue
        entry=pos["entry"];sign=pos["side"]
        hi=float(b["high"]);lo=float(b["low"]);cl=float(b["close"]);op=float(b["open"])
        adverse=(1-lo/entry) if sign==1 else (hi/entry-1)
        favorable=(hi/entry-1) if sign==1 else (1-lo/entry)
        # Stop first in ambiguous OHLC bar.
        if adverse>=stop/100:
            stop_px=entry*(1-sign*stop/100)
            px=min(op,stop_px) if sign==1 else max(op,stop_px)
            gross=sign*(px/entry-1)
            pos["mae"]=max(pos["mae"],adverse)
            trades.append({**pos,"exit_i":i,"exit":px,"gross":gross,
                           "net":gross-COST,"reason":"EMERGENCY_STOP"})
            pos=None;pending_exit=None;opp_streak=0
            continue
        pos["mfe"]=max(pos["mfe"],favorable,0.0)
        pos["mae"]=max(pos["mae"],adverse,0.0)
        mark=sign*(cl/entry-1)
        recoil=max(0.0,pos["mfe"]-mark);pos["max_recoil"]=max(pos["max_recoil"],recoil)
        if pos["mfe"]<activation/100 or i+1>=len(bars):
            opp_streak=0;continue
        threshold=max(floor/100,fraction*pos["mfe"])
        deterioration=recoil>=threshold
        if use_flow and deterioration and i>=2:
            buy=sum(float(bars[k].get("buy_notional") or 0) for k in range(i-2,i+1))
            sell=sum(float(bars[k].get("sell_notional") or 0) for k in range(i-2,i+1))
            own=buy if sign==1 else sell;opp=sell if sign==1 else buy
            flow_opp=(opp-own)/max(opp+own,1e-12)
            ret3=sign*(cl/float(bars[i-2]["close"])-1)
            deterioration=(flow_opp>=.08 and ret3<=-.001)
        opp_streak=opp_streak+1 if deterioration else 0
        if opp_streak>=confirm and pending_exit is None:
            pending_exit={"i":i+1,"reason":"MFE_RECOIL_FLOW" if use_flow else "MFE_RECOIL"}

    if pos is not None:
        px=float(bars[-1]["close"]);gross=pos["side"]*(px/pos["entry"]-1)
        trades.append({**pos,"exit_i":len(bars)-1,"exit":px,"gross":gross,
                       "net":gross-COST,"reason":"BLOCK_END_MARK"})
    return trades

def metric(trades):
    if not trades:return {"trades":0,"compound_pct":0,"maxdd_pct":0,"median_capture":None}
    rets=[x["net"] for x in trades];eq=1.;peak=1.;dd=0.
    for r in rets:
        eq*=max(1e-12,1+r);peak=max(peak,eq);dd=max(dd,1-eq/peak)
    cap=[x["gross"]/x["mfe"] for x in trades if x["mfe"]>1e-9]
    return {
      "trades":len(trades),"wins":sum(x>0 for x in rets),
      "win_rate":sum(x>0 for x in rets)/len(rets),
      "compound_pct":100*(eq-1),"maxdd_pct":100*dd,
      "median_mfe_pct":100*q([x["mfe"] for x in trades],.5),
      "median_mae_pct":100*q([x["mae"] for x in trades],.5),
      "median_capture":q(cap,.5) if cap else None,
      "stop_count":sum(x["reason"]=="EMERGENCY_STOP" for x in trades),
      "flip_count":sum(x["reason"]=="OPPOSITE_ULTRA_FLIP" for x in trades),
      "exit_reasons":{k:sum(x["reason"]==k for x in trades)
                      for k in sorted({x["reason"] for x in trades})}
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--block",action="append",nargs=3,metavar=("NAME","COMPACT","LABELS"),required=True)
    ap.add_argument("--out",type=Path,required=True);a=ap.parse_args()
    data={}
    for name,c,l in a.block:
        bars,score,sig=signals(Path(c),Path(l))
        data[name]={"bars":bars,"score":score,"sig":sig}
    grid=list(itertools.product(
       (1.0,1.25,1.5,2.0),      # emergency stop %
       (.5,.75,1.0),             # activate MFE protection after %
       (.25,.35,.5),             # minimum allowed recoil %
       (.35,.45,.55),            # allowed fraction of MFE giveback
       (1,3),                     # persistence bars
       (False,True)))             # optional opposite-flow confirmation
    trials=[]
    for p in grid:
        per={n:metric(simulate(data[n]["bars"],data[n]["sig"],p)) for n in DEV}
        minret=min(per[n]["compound_pct"] for n in DEV)
        aggret=sum(per[n]["compound_pct"] for n in DEV)
        maxdd=max(per[n]["maxdd_pct"] for n in DEV)
        totaltr=sum(per[n]["trades"] for n in DEV)
        cap=[per[n]["median_capture"] for n in DEV if per[n]["median_capture"] is not None]
        medcap=statistics.median(cap) if cap else -9
        # Robustness first: worst block, then total return, then drawdown/capture.
        score=(minret,aggret-.5*maxdd+.25*medcap,totaltr)
        trials.append((score,p,per))
    best=max(trials,key=lambda x:x[0])
    p=best[1]
    test=metric(simulate(data[TEST]["bars"],data[TEST]["sig"],p))
    may=metric(simulate(data["MAY"]["bars"],data["MAY"]["sig"],p)) if "MAY" in data else None
    positive_all_dev=all(best[2][n]["compound_pct"]>0 for n in DEV)
    result={
      "version":"HYPE-ULTRA-SURVIVAL-V2-DYNAMIC-MFE-EXIT-v1",
      "detector":"frozen Ultra Survival V2 unchanged",
      "selection":"exit parameters selected only on JUL_AUG+AUG_SEP+SEP_OCT; robustness maximizes minimum block return first",
      "selected":{"stop_pct":p[0],"activation_mfe_pct":p[1],"recoil_floor_pct":p[2],
                  "recoil_fraction_of_mfe":p[3],"confirmation_bars":p[4],
                  "require_opposite_flow":p[5]},
      "development":best[2],"development_positive_all_blocks":positive_all_dev,
      "historical_later_test_OCT_NOV":test,
      "MAY_diagnostic_not_used_for_exit_selection":may,
      "signal_scores":{n:data[n]["score"]["evaluation"] for n in data},
      "research_only":True,"real_orders":False,
      "verdict":("PROMISING_HISTORICAL_EXIT_NOT_PRODUCTION"
                 if positive_all_dev and test["compound_pct"]>0
                 else "REJECT_NO_ROBUST_POSITIVE_EXIT"),
      "limitations":[
        "Oct-Nov and May have been inspected elsewhere; neither is a new untouched system OOS.",
        "OHLC emergency-stop execution and 12bps cost are proxies.",
        "No exact mark-price liquidation, latency, capacity or queue model.",
        "Parameter search tests hundreds of exit combinations; multiple-testing risk remains.",
        "New genuinely untouched forward required before any live risk."
      ]
    }
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    print(json.dumps({"selected":result["selected"],"development":result["development"],
      "test":test,"may":may,"verdict":result["verdict"]},ensure_ascii=False))
if __name__=="__main__":main()
