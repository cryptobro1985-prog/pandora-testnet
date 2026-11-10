#!/usr/bin/env python3
from __future__ import annotations
import argparse,gzip,json,math,statistics
from pathlib import Path
import numpy as np,pandas as pd

MOVE=.008
ADV=.0035
H=60
RT_COST=.0012

# Frozen on Jul/Aug feature distributions, required stable lift in Jul/Aug/Sep/Oct.
LONG_RET240_MAX=-1.0632321402270533
LONG_EFF5_MIN=0.008174651851675081
SHORT_EFF5_MIN=0.008174651851675081
SHORT_EFF120_MAX=-0.03765468290410372

def load(path):
    rows=[]
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip(): rows.append(json.loads(line))
    d=pd.DataFrame(rows).sort_values("ts_ms").drop_duplicates("ts_ms").reset_index(drop=True)
    for c in ("open","high","low","close","buy_notional","sell_notional","trade_count","turnover","max_trade_notional","buy_count","sell_count"):
        d[c]=pd.to_numeric(d[c],errors="coerce")
    d["gap"]=d.get("gap",False).fillna(False).astype(bool)
    return d

def features(d):
    x=pd.DataFrame(index=d.index)
    c=d.close.astype(float); b=d.buy_notional.clip(lower=0).astype(float); s=d.sell_notional.clip(lower=0).astype(float)
    r=c.pct_change(); vol240=r.rolling(240,min_periods=60).std()
    for h in (5,120,240):
        ret=c/c.shift(h)-1
        bb=b.rolling(h,min_periods=max(2,h//3)).sum(); ss=s.rolling(h,min_periods=max(2,h//3)).sum()
        flow=(bb-ss)/(bb+ss).replace(0,np.nan)
        x[f"ret{h}"]=(ret/(vol240*np.sqrt(h)+1e-5)).clip(-10,10)
        x[f"eff{h}"]=(ret/(flow.abs()+.08)).clip(-.25,.25)
    x["gap_recent"]=d.gap.astype(float).rolling(15,min_periods=1).max()
    return x.replace([np.inf,-np.inf],np.nan)

def fut(s,h,ma):
    z=s.shift(-1).iloc[::-1].rolling(h,min_periods=h)
    return (z.max() if ma else z.min()).iloc[::-1]

def labels(d):
    c=d.close.astype(float)
    up=fut(d.high.astype(float),H,True)/c-1
    dn=1-fut(d.low.astype(float),H,False)/c
    valid=up.notna()&dn.notna()
    yl=(up>=MOVE)&(dn<=ADV)&valid
    ys=(dn>=MOVE)&(up<=ADV)&valid
    return yl,ys,valid,up,dn

def stats(mask,y,base):
    n=int(mask.sum()); tp=int((mask&y).sum())
    p=tp/n if n else 0.0
    return {"signals":n,"true":tp,"precision":p,"base_rate":base,"lift":p/base if base else 0.0}

def simulate(d,long_sig,short_sig):
    pos=0;entry=0.;ei=-1;mfe=0.;mae=0.;tr=[];last_exit=-999
    for i,row in d.iterrows():
        if bool(row.gap):
            pos=0;last_exit=i;continue
        c=float(row.close);hi=float(row.high);lo=float(row.low)
        ls=bool(long_sig.iloc[i]);ss=bool(short_sig.iloc[i])
        if pos:
            if pos>0:
                fav=hi/entry-1;adv=lo/entry-1;cur=c/entry-1;opp=ss
            else:
                fav=1-lo/entry;adv=1-hi/entry;cur=1-c/entry;opp=ls
            mfe=max(mfe,fav);mae=min(mae,adv);age=i-ei
            recoil=max(0,mfe-cur)
            reverse=age>=3 and opp
            protect=age>=3 and mfe>=.004 and recoil>=max(.0015,.30*mfe)
            timeout=age>=60
            if reverse or protect or timeout:
                gross=pos*(c/entry-1);net=gross-RT_COST
                tr.append({"entry_i":ei,"exit_i":i,"side":pos,"gross":gross,"net":net,"mfe":mfe,"mae":mae,"reason":"REVERSE" if reverse else ("MFE_PROTECT" if protect else "TIMEOUT")})
                old=pos;pos=0;last_exit=i;mfe=0.;mae=0.
                if reverse:
                    pos=-old;entry=c;ei=i
            continue
        if i-last_exit<3: continue
        if ls and not ss: pos=1;entry=c;ei=i;mfe=0.;mae=0.
        elif ss and not ls: pos=-1;entry=c;ei=i;mfe=0.;mae=0.
    if pos:
        c=float(d.iloc[-1].close);gross=pos*(c/entry-1);tr.append({"entry_i":ei,"exit_i":len(d)-1,"side":pos,"gross":gross,"net":gross-RT_COST,"mfe":mfe,"mae":mae,"reason":"END"})
    eq=1.;gp=0.;gl=0.;peak=1.;dd=0.
    for z in tr:
        eq*=max(1e-9,1+z["net"]);peak=max(peak,eq);dd=max(dd,1-eq/peak);gp+=max(0,z["net"]);gl-=min(0,z["net"])
    days=max(1,(float(d.ts_ms.iloc[-1])-float(d.ts_ms.iloc[0]))/86400000)
    caps=[z["gross"]/z["mfe"] for z in tr if z["mfe"]>1e-9]
    return {
        "equity":eq,"return":eq-1,"trades":len(tr),"trades_per_day":len(tr)/days,
        "win_rate":sum(z["net"]>0 for z in tr)/len(tr) if tr else 0.0,
        "profit_factor":gp/gl if gl else (99 if gp else 0.0),
        "max_drawdown":dd,
        "median_mfe":statistics.median([z["mfe"] for z in tr]) if tr else 0.0,
        "median_mae":statistics.median([z["mae"] for z in tr]) if tr else 0.0,
        "median_mfe_capture":statistics.median(caps) if caps else 0.0,
        "trades_rows":tr,
    }

def leverage(trades,L,margin=.20):
    exposure=L*margin;liq_thr=max(.005,1/L-.005);eq=1.;liqs=0
    for z in trades:
        if -z["mae"]>=liq_thr:r=-margin;liqs+=1
        else:r=exposure*z["net"]
        eq*=max(1e-9,1+r)
    return {"leverage":L,"equity_multiple":eq,"return":eq-1,"approx_liquidations":liqs}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--compact",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    d=load(a.compact);x=features(d);yl,ys,valid,up,dn=labels(d)
    good=(x.gap_recent.fillna(1)==0)&valid
    long_sig=good&(x.ret240<=LONG_RET240_MAX)&(x.eff5>=LONG_EFF5_MIN)
    short_sig=good&(x.eff5>=SHORT_EFF5_MIN)&(x.eff120<=SHORT_EFF120_MAX)
    ls=stats(long_sig,yl,float(yl[good].mean()));ss=stats(short_sig,ys,float(ys[good].mean()))
    sim=simulate(d,long_sig,short_sig);tr=sim.pop("trades_rows")
    report={
      "version":"HYPE-UNIVERSAL-TRIGGER-NOV-OOS-V1","frozen_before_nov":True,
      "window":[int(d.ts_ms.iloc[0]),int(d.ts_ms.iloc[-1])],
      "target":{"horizon_minutes":H,"favorable_move":MOVE,"max_adverse":ADV},
      "rules":{
        "LONG":{"ret240_le":LONG_RET240_MAX,"eff5_ge":LONG_EFF5_MIN},
        "SHORT":{"eff5_ge":SHORT_EFF5_MIN,"eff120_le":SHORT_EFF120_MAX},
      },
      "event_quality":{"LONG":ls,"SHORT":ss},
      "simulation":sim,
      "leverage":[leverage(tr,L) for L in (1,5,10,25)],
      "note":"No Local High/Low labels or local detector used in decisions. Nov thresholds frozen before scoring."
    }
    (a.out/"NOV_OOS_TRIGGER_REPORT.json").write_text(json.dumps(report,indent=2)+"\n")
    pd.DataFrame(tr).to_csv(a.out/"NOV_OOS_TRIGGER_TRADES.csv",index=False)
    print(json.dumps(report,indent=2))
if __name__=="__main__":main()
