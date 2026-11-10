#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math,statistics
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd
from research.hype_movement_signature import replay_normalized_v2 as v2

RT_COST=v2.RT_COST
PERIODS=v2.PERIODS

@dataclass
class P:
    lookback:int
    qbest:float
    qedge:float
    gba:float
    gbf:float
    min_hold:int
    confirm:int
    cooldown:int

def load_block(root,rel):
    d=v2.load(root/rel);x=v2.features(d);y=v2.targets(d,x);return d,x,y

def thresholds(L,S,p:P):
    best=np.maximum(L,S);edge=np.abs(L-S)
    bs=pd.Series(best)
    es=pd.Series(edge)
    # Strictly causal: rolling distribution excludes current minute.
    bthr=bs.shift(1).rolling(p.lookback,min_periods=max(120,p.lookback//4)).quantile(p.qbest).to_numpy(float)
    ethr=es.shift(1).rolling(p.lookback,min_periods=max(120,p.lookback//4)).quantile(p.qedge).to_numpy(float)
    # Never allow negative required expected value; costs already in scores.
    bthr=np.maximum(bthr,0.0)
    ethr=np.maximum(ethr,0.0)
    return best,edge,bthr,ethr

def simulate(d,pred,y,p:P,record=False):
    L,S=v2.scores(pred,y)
    best,edge,bthr,ethr=thresholds(L,S,p)
    pos=0;entry=0.;ei=-1;mfe=0.;mae=0.;tr=[];eq=1.;peak=1.;dd=0.;last_exit=-999
    pending=0;pc=0
    for i,row in d.iterrows():
        if bool(row.gap):
            if pos:
                c=float(row.close);gross=pos*(c/entry-1);net=gross-RT_COST
                tr.append(dict(entry_i=ei,exit_i=i,side=pos,gross=gross,net=net,mfe=mfe,mae=mae,reason="GAP"))
                eq*=max(1e-9,1+net);pos=0;last_exit=i
            pending=0;pc=0;continue
        c=float(row.close);hi=float(row.high);lo=float(row.low)
        l=float(L[i]);s=float(S[i]);cand=1 if l>s else -1
        bt=float(bthr[i]) if np.isfinite(bthr[i]) else np.inf
        et=float(ethr[i]) if np.isfinite(ethr[i]) else np.inf
        qualifies=np.isfinite(bt) and np.isfinite(et) and best[i]>=bt and edge[i]>=et and best[i]>0
        if pos:
            if pos>0:fav=hi/entry-1;adv=lo/entry-1;cur=c/entry-1;own,opp=l,s
            else:fav=1-lo/entry;adv=1-hi/entry;cur=1-c/entry;own,opp=s,l
            mfe=max(mfe,fav);mae=min(mae,adv);recoil=max(0,mfe-cur);age=i-ei
            cap=max(p.gba,p.gbf*max(mfe,0))
            reverse=age>=p.min_hold and cand==-pos and qualifies
            protect=age>=p.min_hold and mfe>0 and recoil>=cap and own<max(0,bt*.35)
            weaken=age>=p.min_hold and own<0 and recoil>=p.gba*.6
            if reverse or protect or weaken:
                reason="REVERSE" if reverse else ("MFE_PROTECT" if protect else "WEAKEN")
                gross=pos*(c/entry-1);net=gross-RT_COST
                before=eq;worst=mae-RT_COST;peak=max(peak,before)
                dd=max(dd,1-before*max(1e-9,1+worst)/peak)
                eq*=max(1e-9,1+net);peak=max(peak,eq);dd=max(dd,1-eq/peak)
                tr.append(dict(entry_i=ei,exit_i=i,side=pos,gross=gross,net=net,mfe=mfe,mae=mae,reason=reason,
                               best=float(best[i]),best_thr=bt,edge=float(edge[i]),edge_thr=et))
                pos=0;last_exit=i;mfe=0.;mae=0.;pending=0;pc=0
                if reverse:
                    pos=cand;entry=c;ei=i
            continue
        if i-last_exit<p.cooldown:continue
        if qualifies:
            if cand==pending:pc+=1
            else:pending=cand;pc=1
            if pc>=p.confirm:
                pos=cand;entry=c;ei=i;mfe=0.;mae=0.;pending=0;pc=0
        else:pending=0;pc=0
    if pos:
        c=float(d.iloc[-1].close);gross=pos*(c/entry-1);net=gross-RT_COST
        tr.append(dict(entry_i=ei,exit_i=len(d)-1,side=pos,gross=gross,net=net,mfe=mfe,mae=mae,reason="END"))
        eq*=max(1e-9,1+net)
    n=len(tr);wins=sum(z["net"]>0 for z in tr);gp=sum(max(0,z["net"]) for z in tr);gl=-sum(min(0,z["net"]) for z in tr)
    caps=[z["gross"]/z["mfe"] for z in tr if z["mfe"]>1e-9];gbs=[max(0,z["mfe"]-z["gross"]) for z in tr]
    days=max(1,(float(d.ts_ms.iloc[-1])-float(d.ts_ms.iloc[0]))/86400000)
    return dict(equity=eq,total_return=eq-1,max_drawdown=dd,trades=n,trades_per_day=n/days,
      win_rate=wins/n if n else 0,profit_factor=gp/gl if gl else (99 if gp else 0),
      median_mfe_capture=statistics.median(caps) if caps else 0,
      median_mfe_giveback=statistics.median(gbs) if gbs else 0,
      mean_net_trade=statistics.fmean([z["net"] for z in tr]) if tr else 0,
      trades_rows=tr if record else None)

def obj(m):
    if m["trades"]<12 or m["equity"]<=1 or m["profit_factor"]<=1.10:return -1e9
    return math.log(m["equity"])-2.5*m["max_drawdown"]+0.10*max(-1,min(1,m["median_mfe_capture"]))-0.0001*m["trades"]

def tune(d,pred,y):
    best=None;rows=[]
    for lookback in (720,1440,2880):
      for qb in (.80,.90,.95):
       for qe in (.50,.70,.85):
        for gba in (.0015,.0025):
         for gbf in (.25,.40):
          for confirm in (1,):
           p=P(lookback,qb,qe,gba,gbf,2,confirm,1)
           m=simulate(d,pred,y,p,False);v=obj(m)
           rows.append({"score":v,**p.__dict__,**{k:q for k,q in m.items() if k!="trades_rows"}})
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
    model=v2.train([blocks["TRAIN_JUL12_AUG07"],blocks["TRAIN_AUG08_SEP01"]])
    preds={n:model.predict(x) for n,(d,x,y) in blocks.items()}
    vd,vx,vy=blocks["VALIDATE_SEP01_OCT01"];best,grid=tune(vd,preds["VALIDATE_SEP01_OCT01"],vy)
    score,p,val=best
    metrics={};alltr=[]
    for n,(d,x,y) in blocks.items():
        m=simulate(d,preds[n],y,p,True);metrics[n]={k:v for k,v in m.items() if k!="trades_rows"};alltr+=enrich(d,m["trades_rows"],n)
    htr=[z for z in alltr if z["period"]=="HOLDOUT_OCT04_NOV03"]
    rep={"version":"HYPE-MOVEMENT-ADAPTIVE-RANK-V6-FAST","research_only":True,"real_orders":False,
      "train":["Jul12-Aug07","Aug08-Sep01"],"validation":"Sep01-Oct01",
      "mechanism":"V2 direction/value model with strictly causal rolling rank thresholds; no Nov tuning",
      "params":p.__dict__,"validation_metrics":{k:v for k,v in val.items() if k!="trades_rows"},
      "period_metrics":metrics,"oct_leverage":[leverage(htr,L) for L in (1,5,10,25)],
      "warning":"Oct is diagnostic after V2 inspection. Nov must remain frozen forward-like evaluation."}
    (a.out/"ADAPTIVE_RANK_V6_REPORT.json").write_text(json.dumps(rep,indent=2)+"\n")
    pd.DataFrame(alltr).to_csv(a.out/"ADAPTIVE_RANK_V6_TRADES.csv",index=False)
    pd.DataFrame(grid).sort_values("score",ascending=False).head(300).to_csv(a.out/"ADAPTIVE_RANK_V6_GRID_TOP.csv",index=False)
    print(json.dumps(rep,indent=2))
if __name__=="__main__":main()
