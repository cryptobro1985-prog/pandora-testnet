#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math, statistics
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

from research.hype_movement_signature import replay_normalized_v2 as v2

@dataclass
class AP:
    window:int
    q_best:float
    q_edge:float
    gba:float=0.0015
    gbf:float=0.25
    min_hold:int=2
    confirm:int=1
    min_score:float=0.0

PRESETS=[
    AP(w,qb,qe)
    for w in (240,720,1440)
    for qb in (0.90,0.95,0.975)
    for qe in (0.60,0.75,0.90)
]

def causal_q(a,window,q,minp=60):
    s=pd.Series(a,dtype=float)
    return s.shift(1).rolling(window,min_periods=min(minp,window)).quantile(q).to_numpy(float)

def simulate(d,pred,y,p:AP,record=False):
    L,S=v2.scores(pred,y)
    best=np.maximum(L,S); edge=np.abs(L-S)
    qb=causal_q(best,p.window,p.q_best)
    qe=causal_q(edge,p.window,p.q_edge)

    pos=0;entry=0.;ei=-1;mfe=0.;mae=0.;tr=[];eq=1.;peak=1.;dd=0.;last_exit=-999
    pending_side=0;pending_count=0
    gate_count=0
    for i,row in d.iterrows():
        if bool(row.gap):
            if pos:
                gross=pos*(float(row.close)/entry-1);net=gross-v2.RT_COST
                tr.append(dict(entry_i=ei,exit_i=i,side=pos,gross=gross,net=net,mfe=mfe,mae=mae,reason="GAP"))
                eq*=max(1e-9,1+net);pos=0;last_exit=i
            pending_side=0;pending_count=0
            peak=max(peak,eq);dd=max(dd,1-eq/peak);continue
        c=float(row.close);hi=float(row.high);lo=float(row.low)
        l=float(L[i]);s=float(S[i]);b=float(best[i]);e=float(edge[i]);candidate=1 if l>s else -1
        entry_thr=max(p.min_score,float(qb[i])) if np.isfinite(qb[i]) else float("inf")
        edge_thr=float(qe[i]) if np.isfinite(qe[i]) else float("inf")
        gate=(b>=entry_thr and e>=edge_thr and b>0)
        if gate: gate_count+=1

        if pos:
            if pos>0:fav=hi/entry-1;adv=lo/entry-1;cur=c/entry-1;own,opp=l,s
            else:fav=1-lo/entry;adv=1-hi/entry;cur=1-c/entry;own,opp=s,l
            mfe=max(mfe,fav);mae=min(mae,adv);recoil=max(0,mfe-cur)
            cap=max(p.gba,p.gbf*max(mfe,0));age=i-ei

            # Score-scale adaptive reverse, but physical MFE/recoil remains frozen V2.
            reverse=age>=p.min_hold and opp>=entry_thr and (opp-own)>=edge_thr and opp>0
            protect=age>=p.min_hold and mfe>=0.0015 and recoil>=cap and own<max(0,entry_thr*0.35)
            weaken=age>=p.min_hold and own<0 and recoil>=p.gba*0.6
            if reverse or protect or weaken:
                reason="REVERSE" if reverse else ("MFE_PROTECT" if protect else "WEAKEN")
                gross=pos*(c/entry-1);net=gross-v2.RT_COST
                before=eq;worst=mae-v2.RT_COST
                peak=max(peak,before);dd=max(dd,1-before*max(1e-9,1+worst)/peak)
                eq*=max(1e-9,1+net);peak=max(peak,eq);dd=max(dd,1-eq/peak)
                tr.append(dict(entry_i=ei,exit_i=i,side=pos,gross=gross,net=net,mfe=mfe,mae=mae,reason=reason,
                               entry_thr=entry_thr,edge_thr=edge_thr))
                np_side=(1 if l>s else -1) if reverse else 0
                pos=0;last_exit=i;mfe=0.;mae=0.;pending_side=0;pending_count=0
                if np_side:
                    pos=np_side;entry=c;ei=i
            continue

        if i-last_exit<1: continue
        if gate:
            if candidate==pending_side:pending_count+=1
            else:pending_side=candidate;pending_count=1
            if pending_count>=p.confirm:
                pos=candidate;entry=c;ei=i;mfe=0.;mae=0.;pending_side=0;pending_count=0
        else:
            pending_side=0;pending_count=0

    if pos:
        c=float(d.iloc[-1].close);gross=pos*(c/entry-1);net=gross-v2.RT_COST
        tr.append(dict(entry_i=ei,exit_i=len(d)-1,side=pos,gross=gross,net=net,mfe=mfe,mae=mae,reason="END",
                       entry_thr=float(qb[-1]) if np.isfinite(qb[-1]) else None,
                       edge_thr=float(qe[-1]) if np.isfinite(qe[-1]) else None))
        eq*=max(1e-9,1+net)

    n=len(tr);wins=sum(z["net"]>0 for z in tr);gp=sum(max(0,z["net"]) for z in tr);gl=-sum(min(0,z["net"]) for z in tr)
    caps=[z["gross"]/z["mfe"] for z in tr if z["mfe"]>1e-9];gbs=[max(0,z["mfe"]-z["gross"]) for z in tr]
    days=max(1,(float(d.ts_ms.iloc[-1])-float(d.ts_ms.iloc[0]))/86400000)
    return dict(
        equity=eq,total_return=eq-1,max_drawdown=dd,trades=n,trades_per_day=n/days,
        win_rate=wins/n if n else 0,profit_factor=gp/gl if gl else (99 if gp else 0),
        median_mfe_capture=statistics.median(caps) if caps else 0,
        median_mfe_giveback=statistics.median(gbs) if gbs else 0,
        mean_net_trade=statistics.fmean([z["net"] for z in tr]) if tr else 0,
        gate_minutes=gate_count,trades_rows=tr if record else None
    )

def obj(m):
    if m["trades"]<12 or m["equity"]<=1.0 or m["profit_factor"]<1.15:return -1e9
    return math.log(m["equity"])-2.25*m["max_drawdown"]+0.08*max(-1,min(1,m["median_mfe_capture"]))-0.0001*m["trades"]

def load_block(root,rel):
    d=v2.load(root/rel);x=v2.features(d);y=v2.targets(d,x);return d,x,y

def enrich(d,trades,period):
    out=[]
    for z in trades:
        a=d.iloc[int(z["entry_i"])];b=d.iloc[int(z["exit_i"])]
        q=dict(z);q.update(period=period,entry_ts_ms=int(a.ts_ms),exit_ts_ms=int(b.ts_ms),
                           entry_price=float(a.close),exit_price=float(b.close),
                           side_name="LONG" if z["side"]>0 else "SHORT",
                           mfe_giveback=max(0,z["mfe"]-z["gross"]),
                           mfe_capture=(z["gross"]/z["mfe"] if z["mfe"]>1e-9 else None))
        out.append(q)
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--master-root",type=Path,required=True)
    ap.add_argument("--recent-compact",type=Path)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)

    blocks={}
    for name,rel in v2.PERIODS:
        blocks[name]=load_block(a.master_root,rel)
    model=v2.train([blocks["TRAIN_JUL12_AUG07"],blocks["TRAIN_AUG08_SEP01"]])
    preds={n:model.predict(x) for n,(d,x,y) in blocks.items()}

    vd,vx,vy=blocks["VALIDATE_SEP01_OCT01"]
    scored=[]
    for p in PRESETS:
        m=simulate(vd,preds["VALIDATE_SEP01_OCT01"],vy,p,False)
        scored.append((obj(m),p,m))
    scored.sort(key=lambda z:z[0],reverse=True)
    score,bp,bv=scored[0]

    report={
      "version":"HYPE-MOVEMENT-V2.3-CAUSAL-PERCENTILE",
      "research_only":True,"real_orders":False,
      "train":["Jul12-Aug07","Aug08-Sep01"],"validation":"Sep01-Oct01",
      "selection":"27 predeclared causal rolling-percentile gates; selected on Sep validation only",
      "winner":bp.__dict__,
      "validation_metrics":{k:v for k,v in bv.items() if k!="trades_rows"},
      "all_presets":[{"score":s,**p.__dict__,**{k:v for k,v in m.items() if k!="trades_rows"}} for s,p,m in scored],
      "period_metrics":{},
      "nov_forward":None,
      "warning":"Research only; Nov is never used for fit or threshold selection."
    }
    alltr=[]
    for n,(d,x,y) in blocks.items():
        m=simulate(d,preds[n],y,bp,True)
        report["period_metrics"][n]={k:v for k,v in m.items() if k!="trades_rows"}
        alltr += enrich(d,m["trades_rows"],n)

    if a.recent_compact and a.recent_compact.exists():
        d,x,y=load_block(Path("."),a.recent_compact) if False else (None,None,None)
        d=v2.load(a.recent_compact);x=v2.features(d);y=v2.targets(d,x)
        pred=model.predict(x)
        m=simulate(d,pred,y,bp,True)
        rows=enrich(d,m["trades_rows"],"NOV08_NOV10_FORWARD")
        HIGH_TS=1794144000000;LOW_TS=1794211320000;HIGH_PRICE=78.133;LOW_PRICE=72.391
        leg=[z for z in rows if z["side"]<0 and z["entry_ts_ms"]>=HIGH_TS and z["entry_ts_ms"]<LOW_TS]
        first=sorted(leg,key=lambda z:z["entry_ts_ms"])[0] if leg else None
        report["nov_forward"]={
          "metrics":{k:v for k,v in m.items() if k!="trades_rows"},
          "control_leg":{
             "oracle_drop_pct":(1-LOW_PRICE/HIGH_PRICE)*100,
             "short_trades":len(leg),
             "compound_net_underlying_pct":(float(np.prod([1+z["net"] for z in leg])-1)*100 if leg else 0.0),
             "first_short":None if first is None else {
                "entry_iso":pd.to_datetime(first["entry_ts_ms"],unit="ms",utc=True).isoformat(),
                "entry_price":first["entry_price"],
                "distance_below_high_pct":(1-first["entry_price"]/HIGH_PRICE)*100,
                "exit_iso":pd.to_datetime(first["exit_ts_ms"],unit="ms",utc=True).isoformat(),
                "exit_price":first["exit_price"],
                "net_pct":first["net"]*100,"mfe_pct":first["mfe"]*100,"mae_pct":first["mae"]*100,
                "giveback_pct":first["mfe_giveback"]*100,"reason":first["reason"]
             }
          }
        }
        alltr += rows

    (a.out/"MOVEMENT_V23_REPORT.json").write_text(json.dumps(report,indent=2)+"\n")
    pd.DataFrame(alltr).to_csv(a.out/"MOVEMENT_V23_TRADES.csv",index=False)
    print(json.dumps(report,indent=2))

if __name__=="__main__":main()
