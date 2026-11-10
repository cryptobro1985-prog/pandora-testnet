#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math,statistics
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

from research.hype_movement_signature import replay_normalized_v2 as v2

RT_COST=0.0012
PERIODS=v2.PERIODS

@dataclass
class P:
    entry:float
    exit:float
    trail_abs:float
    trail_frac:float
    stop_abs:float
    confirm:int
    cooldown:int

def load_block(root,rel):
    d=v2.load(root/rel);x=v2.features(d);return d,x

def safe(a):
    return np.nan_to_num(np.asarray(a,dtype=float),nan=0.0,posinf=0.0,neginf=0.0)

def strength(x:pd.DataFrame):
    # All components are causal/current-state. No future target or Local teacher.
    r=(0.10*np.tanh(safe(x.ret_norm_3)/2)
       +0.15*np.tanh(safe(x.ret_norm_5)/2)
       +0.20*np.tanh(safe(x.ret_norm_15)/2)
       +0.25*np.tanh(safe(x.ret_norm_30)/2)
       +0.20*np.tanh(safe(x.ret_norm_60)/2))
    f=(0.10*safe(x.flow_3)+0.15*safe(x.flow_5)+0.20*safe(x.flow_15)
       +0.25*safe(x.flow_30)+0.30*safe(x.flow_60))
    p=(0.10*(2*safe(x.persist_3)-1)+0.15*(2*safe(x.persist_5)-1)
       +0.20*(2*safe(x.persist_15)-1)+0.25*(2*safe(x.persist_30)-1)
       +0.30*(2*safe(x.persist_60)-1))
    e=(0.10*np.tanh(safe(x.eff_norm_3)/5)+0.15*np.tanh(safe(x.eff_norm_5)/5)
       +0.20*np.tanh(safe(x.eff_norm_15)/5)+0.25*np.tanh(safe(x.eff_norm_30)/5)
       +0.30*np.tanh(safe(x.eff_norm_60)/5))
    a=(0.55*np.tanh(safe(x.accel_3v15)/2)+0.45*np.tanh(safe(x.accel_5v30)/2))
    # Price is primary; flow confirms rather than dominates.
    score=.42*r+.14*f+.22*p+.14*e+.08*a
    return score,dict(ret=r,flow=f,persist=p,eff=e,accel=a)

def simulate(d,x,p:P,record=False):
    sc,parts=strength(x)
    pos=0;entry=0.;ei=-1;mfe=0.;mae=0.;tr=[];eq=1.;peak=1.;dd=0.;last_exit=-999
    pending=0;pc=0
    for i,row in d.iterrows():
        if bool(row.gap):
            if pos:
                c=float(row.close);gross=pos*(c/entry-1);net=gross-RT_COST
                tr.append(dict(entry_i=ei,exit_i=i,side=pos,gross=gross,net=net,mfe=mfe,mae=mae,reason="GAP"))
                eq*=max(1e-9,1+net);pos=0;last_exit=i
            pending=0;pc=0;continue
        c=float(row.close);hi=float(row.high);lo=float(row.low);s=float(sc[i])
        cand=1 if s>0 else -1
        if pos:
            if pos>0:fav=hi/entry-1;adv=lo/entry-1;cur=c/entry-1
            else:fav=1-lo/entry;adv=1-hi/entry;cur=1-c/entry
            mfe=max(mfe,fav);mae=min(mae,adv);recoil=max(0,mfe-cur);age=i-ei
            directional=pos*s
            reverse=age>=2 and directional<=-p.entry
            stop=age>=1 and cur<=-p.stop_abs
            trail=age>=2 and mfe>=p.trail_abs and recoil>=max(p.trail_abs,p.trail_frac*mfe) and directional<p.entry*.55
            weaken=age>=2 and directional<=p.exit
            if reverse or stop or trail or weaken:
                reason="REVERSE" if reverse else ("ADVERSE_STOP" if stop else ("MFE_PROTECT" if trail else "WEAKEN"))
                gross=pos*(c/entry-1);net=gross-RT_COST
                before=eq;worst=mae-RT_COST;peak=max(peak,before)
                dd=max(dd,1-before*max(1e-9,1+worst)/peak)
                eq*=max(1e-9,1+net);peak=max(peak,eq);dd=max(dd,1-eq/peak)
                tr.append(dict(entry_i=ei,exit_i=i,side=pos,gross=gross,net=net,mfe=mfe,mae=mae,reason=reason,
                               entry_strength=float(sc[ei]),exit_strength=s))
                pos=0;last_exit=i;mfe=0.;mae=0.;pending=0;pc=0
                if reverse:
                    pos=cand;entry=c;ei=i
            continue
        if i-last_exit<p.cooldown:continue
        if abs(s)>=p.entry:
            if cand==pending:pc+=1
            else:pending=cand;pc=1
            if pc>=p.confirm:
                pos=cand;entry=c;ei=i;mfe=0.;mae=0.;pending=0;pc=0
        else:pending=0;pc=0
    if pos:
        c=float(d.iloc[-1].close);gross=pos*(c/entry-1);net=gross-RT_COST
        tr.append(dict(entry_i=ei,exit_i=len(d)-1,side=pos,gross=gross,net=net,mfe=mfe,mae=mae,reason="END",
                       entry_strength=float(sc[ei]),exit_strength=float(sc[-1])))
        eq*=max(1e-9,1+net)
    n=len(tr);wins=sum(z["net"]>0 for z in tr);gp=sum(max(0,z["net"]) for z in tr);gl=-sum(min(0,z["net"]) for z in tr)
    caps=[z["gross"]/z["mfe"] for z in tr if z["mfe"]>1e-9];gbs=[max(0,z["mfe"]-z["gross"]) for z in tr]
    days=max(1,(float(d.ts_ms.iloc[-1])-float(d.ts_ms.iloc[0]))/86400000)
    return dict(equity=eq,total_return=eq-1,max_drawdown=dd,trades=n,trades_per_day=n/days,
      win_rate=wins/n if n else 0,profit_factor=gp/gl if gl else (99 if gp else 0),
      median_mfe_capture=statistics.median(caps) if caps else 0,
      median_mfe_giveback=statistics.median(gbs) if gbs else 0,
      mean_net_trade=statistics.fmean([z["net"] for z in tr]) if tr else 0,
      trades_rows=tr if record else None,
      score_stats={"p50_abs":float(np.quantile(np.abs(sc),.5)),"p90_abs":float(np.quantile(np.abs(sc),.9)),"max_abs":float(np.max(np.abs(sc)))})

def obj(m):
    if m["trades"]<20 or m["equity"]<=1 or m["profit_factor"]<=1.10:return -1e9
    return math.log(m["equity"])-2.25*m["max_drawdown"]+0.10*max(-1,min(1,m["median_mfe_capture"]))-0.00008*m["trades"]

def tune(d,x):
    best=None; rows=[]
    for entry in (.12,.18,.24,.30):
      for exit in (-.04,.02,.08):
       for ta in (.0015,.0030):
        for tf in (.20,.40):
         for stop in (.0045,.0075):
          for confirm in (1,):
           p=P(entry,exit,ta,tf,stop,confirm,2)
           m=simulate(d,x,p,False);v=obj(m)
           rows.append({"score":v,**p.__dict__,**{k:q for k,q in m.items() if k not in ("trades_rows","score_stats")}})
           if best is None or v>best[0]:best=(v,p,m)
    return best,rows

def enrich(d,tr,period):
    out=[]
    for z in tr:
        q=dict(z);a=d.iloc[int(z["entry_i"])];b=d.iloc[int(z["exit_i"])]
        q.update(period=period,entry_ts_ms=int(a.ts_ms),exit_ts_ms=int(b.ts_ms),
                 entry_price=float(a.close),exit_price=float(b.close),
                 side_name="LONG" if z["side"]>0 else "SHORT",
                 mfe_capture=(z["gross"]/z["mfe"] if z["mfe"]>1e-9 else None),
                 mfe_giveback=max(0,z["mfe"]-z["gross"]))
        out.append(q)
    return out

def leverage(trades,L,margin=.20):
    exposure=L*margin;liq_thr=max(.005,1/L-.005);eq=1.;peak=1.;dd=0.;liqs=0
    for z in trades:
        before=eq
        if -z["mae"]>=liq_thr:r=-margin;worst=-margin;liqs+=1
        else:r=exposure*z["net"];worst=exposure*(z["mae"]-RT_COST)
        peak=max(peak,before);dd=max(dd,1-before*max(1e-9,1+worst)/peak)
        eq*=max(1e-9,1+r);peak=max(peak,eq);dd=max(dd,1-eq/peak)
    return dict(leverage=L,exposure_x_equity=exposure,equity_multiple=eq,total_return=eq-1,max_drawdown=dd,approx_liquidations=liqs)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--master-root",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    blocks={n:load_block(a.master_root,rel) for n,rel in PERIODS}
    vd,vx=blocks["VALIDATE_SEP01_OCT01"];best,grid=tune(vd,vx)
    score,p,val=best
    metrics={};alltr=[]
    for n,(d,x) in blocks.items():
        m=simulate(d,x,p,True);metrics[n]={k:v for k,v in m.items() if k!="trades_rows"};alltr+=enrich(d,m["trades_rows"],n)
    htr=[z for z in alltr if z["period"]=="HOLDOUT_OCT04_NOV03"]
    rep={"version":"HYPE-DIRECT-MOVEMENT-STRENGTH-V5-FAST","research_only":True,"real_orders":False,
      "inputs":"causal current-state momentum+flow+persistence+efficiency+acceleration; no Local teacher, no future predictor",
      "selection":"thresholds tuned on Sep01-Oct01 only; Oct04-Nov03 diagnostic because prior variants already inspected",
      "params":p.__dict__,"validation_metrics":{k:v for k,v in val.items() if k!="trades_rows"},
      "period_metrics":metrics,"oct_leverage":[leverage(htr,L) for L in (1,5,10,25)],
      "warning":"Historical research only. Direct-state V5 is a development candidate, not proven future edge."}
    (a.out/"DIRECT_STRENGTH_V5_REPORT.json").write_text(json.dumps(rep,indent=2)+"\n")
    pd.DataFrame(alltr).to_csv(a.out/"DIRECT_STRENGTH_V5_TRADES.csv",index=False)
    pd.DataFrame(grid).sort_values("score",ascending=False).head(200).to_csv(a.out/"DIRECT_STRENGTH_V5_GRID_TOP.csv",index=False)
    print(json.dumps(rep,indent=2))

if __name__=="__main__":main()
