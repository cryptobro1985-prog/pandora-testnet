#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math, statistics
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

from research.hype_movement_signature import replay_normalized_v2 as base

RT_COST=0.0012
PERIODS=[
 ("JUL12_AUG07","01_JUL12_AUG07_FULL_MICRO/compact_1m.jsonl.gz"),
 ("AUG08_SEP01","02_AUG08_SEP01/compact_1m.jsonl.gz"),
 ("SEP01_OCT01","03_SEP01_OCT01/compact_1m.jsonl.gz"),
 ("OCT04_NOV03","04_OCT04_NOV03/compact_1m.jsonl.gz"),
]
HS=(3,5,10,15,30,60)
HW={3:.08,5:.18,10:.20,15:.22,30:.20,60:.12}

@dataclass(frozen=True)
class P:
    entry:float
    consensus:float
    confirm:int
    hold:float
    mfe_arm:float
    giveback_abs:float
    giveback_frac:float
    stop_abs:float
    cooldown:int


def strength(x:pd.DataFrame)->np.ndarray:
    out=np.zeros(len(x),float)
    for h in HS:
        r=np.tanh(x[f"ret_norm_{h}"].fillna(0).to_numpy(float)/1.75)
        persist=(2*x[f"persist_{h}"].fillna(.5).to_numpy(float)-1).clip(-1,1)
        flow=x[f"flow_{h}"].fillna(0).to_numpy(float).clip(-1,1)
        eff=np.tanh(x[f"eff_norm_{h}"].fillna(0).to_numpy(float)/3.0)
        # Prior research: price response / efficiency transfer more robust than raw imbalance.
        component=.48*r+.27*persist+.10*flow+.15*eff
        out += HW[h]*component
    # Small acceleration term; still entirely causal.
    accel=np.tanh(x["accel_5v30"].fillna(0).to_numpy(float)/2.0)
    out=.92*out+.08*accel
    return np.clip(out,-1,1)


def arrays(d:pd.DataFrame,x:pd.DataFrame):
    return dict(
      close=d.close.to_numpy(float),high=d.high.to_numpy(float),low=d.low.to_numpy(float),
      gap=d.gap.to_numpy(bool),ts=d.ts_ms.to_numpy(np.int64),
      s=strength(x),
      consensus=x.ret_consensus.fillna(0).to_numpy(float).clip(-1,1),
      flow_cons=x.flow_consensus.fillna(0).to_numpy(float).clip(-1,1),
    )


def sim(a,p:P,record=False):
    close,high,low,gap,ts,s,cons=a["close"],a["high"],a["low"],a["gap"],a["ts"],a["s"],a["consensus"]
    pos=0;entry=0.;ei=-1;mfe=0.;mae=0.;last_exit=-999999
    pending=0;pc=0;tr=[];eq=1.;peak=1.;dd=0.
    for i in range(len(close)):
        if gap[i]:
            if pos:
                cur=pos*(close[i]/entry-1);net=cur-RT_COST
                tr.append((ei,i,pos,cur,net,mfe,mae,"GAP"))
                eq*=max(1e-9,1+net);peak=max(peak,eq);dd=max(dd,1-eq/peak)
                pos=0;last_exit=i
            pending=0;pc=0;continue
        st=float(s[i]); candidate=1 if st>0 else -1
        directional_cons=candidate*float(cons[i])
        if pos:
            if pos>0:
                fav=high[i]/entry-1;adv=low[i]/entry-1;cur=close[i]/entry-1
            else:
                fav=1-low[i]/entry;adv=1-high[i]/entry;cur=1-close[i]/entry
            mfe=max(mfe,fav);mae=min(mae,adv);recoil=max(0.,mfe-cur)
            own=pos*st;opp=-pos*st;age=i-ei
            reason=None;reverse=False
            if age>=2 and opp>=p.entry and (-pos)*cons[i]>=p.consensus:
                reason="CONTROL_FLIP";reverse=True
            elif age>=2 and mfe>=p.mfe_arm and recoil>=max(p.giveback_abs,p.giveback_frac*mfe):
                reason="MFE_PROTECT"
            elif age>=2 and own<=p.hold and recoil>=p.giveback_abs*.65:
                reason="WEAKEN"
            elif age>=1 and cur<=-p.stop_abs:
                reason="ADVERSE_STOP"
            if reason:
                net=cur-RT_COST
                before=eq;worst=mae-RT_COST
                peak=max(peak,before);dd=max(dd,1-before*max(1e-9,1+worst)/peak)
                eq*=max(1e-9,1+net);peak=max(peak,eq);dd=max(dd,1-eq/peak)
                tr.append((ei,i,pos,cur,net,mfe,mae,reason))
                new=-pos if reverse else 0
                pos=0;last_exit=i;mfe=0.;mae=0.;pending=0;pc=0
                if new and abs(st)>=p.entry and new*cons[i]>=p.consensus:
                    pos=new;entry=close[i];ei=i
            continue
        if i-last_exit<p.cooldown:continue
        if abs(st)>=p.entry and directional_cons>=p.consensus:
            if candidate==pending:pc+=1
            else:pending=candidate;pc=1
            if pc>=p.confirm:
                pos=candidate;entry=close[i];ei=i;mfe=0.;mae=0.;pending=0;pc=0
        else:
            pending=0;pc=0
    if pos:
        cur=pos*(close[-1]/entry-1);net=cur-RT_COST
        tr.append((ei,len(close)-1,pos,cur,net,mfe,mae,"END"))
        eq*=max(1e-9,1+net);peak=max(peak,eq);dd=max(dd,1-eq/peak)
    n=len(tr);wins=sum(z[4]>0 for z in tr);gp=sum(max(0,z[4]) for z in tr);gl=-sum(min(0,z[4]) for z in tr)
    caps=[z[3]/z[5] for z in tr if z[5]>1e-9];gbs=[max(0,z[5]-z[3]) for z in tr]
    days=max(1,(ts[-1]-ts[0])/86400000)
    m=dict(equity=eq,total_return=eq-1,max_drawdown=dd,trades=n,trades_per_day=n/days,
           win_rate=wins/n if n else 0,profit_factor=gp/gl if gl else (99 if gp else 0),
           median_mfe_capture=statistics.median(caps) if caps else 0,
           median_mfe_giveback=statistics.median(gbs) if gbs else 0,
           mean_net_trade=statistics.fmean([z[4] for z in tr]) if tr else 0)
    if record:m["trades_rows"]=tr
    return m


def robust_obj(metrics):
    if sum(m["trades"] for m in metrics)<45:return -999
    logs=np.array([math.log(max(m["equity"],1e-9)) for m in metrics])
    dds=np.array([m["max_drawdown"] for m in metrics])
    tpd=np.mean([m["trades_per_day"] for m in metrics])
    neg=sum(m["total_return"]<0 for m in metrics)
    return float(logs.sum()-1.8*dds.sum()-0.70*logs.std()-0.20*neg+0.05*min(1,tpd/2.0))


def tune(blocks):
    # Stage 1: entry/state detection. Exit defaults deliberately moderate.
    best=[]
    for entry in (.16,.20,.24,.28,.32,.36):
      for consensus in (.25,.50,.75):
       for confirm in (1,2):
        p=P(entry,consensus,confirm,.08,.004,.002,.35,.006,2)
        ms=[sim(a,p) for a in blocks]
        best.append((robust_obj(ms),p,ms))
    best.sort(key=lambda z:z[0],reverse=True)
    # Stage 2: MFE/exit. Search around top 3 entry configurations.
    out=[]
    for _,q,_ in best[:3]:
      for hold in (.00,.06,.12):
       for arm in (.0025,.004,.006):
        for gba in (.0015,.0025,.0035):
         for gbf in (.20,.35,.50):
          for stop in (.004,.006,.009):
           for cooldown in (1,3):
            p=P(q.entry,q.consensus,q.confirm,hold,arm,gba,gbf,stop,cooldown)
            ms=[sim(a,p) for a in blocks]
            out.append((robust_obj(ms),p,ms))
    out.sort(key=lambda z:z[0],reverse=True)
    return out[0],out[:30]


def enriched(d,a,trades,period):
    rows=[]
    for ei,xi,side,gross,net,mfe,mae,reason in trades:
        rows.append(dict(period=period,entry_i=ei,exit_i=xi,side=side,side_name="LONG" if side>0 else "SHORT",
          entry_ts_ms=int(a["ts"][ei]),exit_ts_ms=int(a["ts"][xi]),
          entry_price=float(a["close"][ei]),exit_price=float(a["close"][xi]),
          strength_entry=float(a["s"][ei]),consensus_entry=float(a["consensus"][ei]),
          gross=gross,net=net,mfe=mfe,mae=mae,reason=reason,
          mfe_giveback=max(0,mfe-gross),mfe_capture=(gross/mfe if mfe>1e-9 else None)))
    return rows


def leverage(trades,L,margin=.20):
    exposure=L*margin;liq_thr=max(.005,1/L-.005);eq=peak=1.;dd=0.;liqs=0
    for z in trades:
        if -z["mae"]>=liq_thr:r=-margin;worst=-margin;liqs+=1
        else:r=exposure*z["net"];worst=exposure*(z["mae"]-RT_COST)
        before=eq;peak=max(peak,before);dd=max(dd,1-before*max(1e-9,1+worst)/peak)
        eq*=max(1e-9,1+r);peak=max(peak,eq);dd=max(dd,1-eq/peak)
    return dict(leverage=L,exposure_x_equity=exposure,equity_multiple=eq,total_return=eq-1,max_drawdown=dd,approx_liquidations=liqs)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--master-root",type=Path,required=True)
    ap.add_argument("--recent-compact",type=Path)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)

    dev=[];devmeta=[]
    for name,rel in PERIODS:
        d=base.load(a.master_root/rel);x=base.features(d);ar=arrays(d,x)
        dev.append(ar);devmeta.append((name,d,x,ar))
    (score,p,ms),top=tune(dev)
    alltr=[];period_metrics={}
    for (name,d,x,ar),m in zip(devmeta,ms):
        rr=sim(ar,p,True);period_metrics[name]={k:v for k,v in rr.items() if k!="trades_rows"}
        alltr+=enriched(d,ar,rr["trades_rows"],name)

    report=dict(version="HYPE-DIRECT-MOVEMENT-STRENGTH-V4",research_only=True,real_orders=False,
      development_periods=[x[0] for x in PERIODS],feature_policy="causal observed price+persistence+efficiency+low-weight flow; no Local and no future-value model",
      params=p.__dict__,development_objective=score,development_metrics=period_metrics,
      top_candidates=[dict(objective=s,params=q.__dict__,metrics=mm) for s,q,mm in top[:10]])

    if a.recent_compact:
        d=base.load(a.recent_compact);x=base.features(d);ar=arrays(d,x);rm=sim(ar,p,True)
        rtr=enriched(d,ar,rm["trades_rows"],"NOV08_NOV10_FORWARD")
        report["forward_nov08_nov10"]={k:v for k,v in rm.items() if k!="trades_rows"}
        report["forward_leverage"]=[leverage(rtr,L) for L in (1,5,10,25)]
        H=78.133;LO=72.391;ht=1794144000000;lt=1794211320000
        leg=[z for z in rtr if z["side"]<0 and ht<=z["entry_ts_ms"]<lt]
        report["control_leg"]=dict(high=H,low=LO,simple_drop_pct=(1-LO/H)*100,short_oracle_pct=(H/LO-1)*100,
          short_entries=len(leg),compound_net_underlying_pct=(np.prod([1+z["net"] for z in leg])-1)*100 if leg else 0,
          first_short=(leg[0] if leg else None))
        alltr+=rtr

    report["warning"]="V4 uses all Jul-Nov3 history as development. Nov8-10 is frozen forward control and must not be used to retune this version."
    (a.out/"MOVEMENT_V4_REPORT.json").write_text(json.dumps(report,indent=2)+"\n")
    pd.DataFrame(alltr).to_csv(a.out/"MOVEMENT_V4_TRADES.csv",index=False)
    print(json.dumps(report,indent=2))

if __name__=="__main__":main()
