#!/usr/bin/env python3
from __future__ import annotations
import argparse, gzip, json, math, statistics
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor

PERIODS=[
 ("TRAIN_JUL12_AUG07","01_JUL12_AUG07_FULL_MICRO/compact_1m.jsonl.gz"),
 ("TRAIN_AUG08_SEP01","02_AUG08_SEP01/compact_1m.jsonl.gz"),
 ("VALIDATE_SEP01_OCT01","03_SEP01_OCT01/compact_1m.jsonl.gz"),
 ("HOLDOUT_OCT04_NOV03","04_OCT04_NOV03/compact_1m.jsonl.gz"),
]
HORIZONS=(5,15,30,60)
WEIGHTS=np.array([0.15,0.35,0.30,0.20])
RT_COST=0.0012
ADVERSE=0.85

def load(path):
    rows=[]
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip(): rows.append(json.loads(line))
    d=pd.DataFrame(rows).sort_values("ts_ms").drop_duplicates("ts_ms").reset_index(drop=True)
    for c in ("open","high","low","close","buy_notional","sell_notional","buy_count","sell_count","trade_count","turnover","volume","max_trade_notional","flow_imbalance"):
        if c in d:d[c]=pd.to_numeric(d[c],errors="coerce")
    d["gap"]=d.get("gap",False).fillna(False).astype(bool)
    return d

def roll_z(s,w):
    mu=s.rolling(w,min_periods=max(20,w//4)).mean()
    sd=s.rolling(w,min_periods=max(20,w//4)).std().replace(0,np.nan)
    return (s-mu)/sd

def features(d):
    x=pd.DataFrame(index=d.index)
    c=d.close.astype(float); hi=d.high.astype(float); lo=d.low.astype(float); op=d.open.astype(float)
    b=d.buy_notional.clip(lower=0).astype(float); s=d.sell_notional.clip(lower=0).astype(float)
    tot=(b+s).replace(0,np.nan); flow=(b-s)/tot
    r1=c.pct_change()
    vol60=r1.rolling(60,min_periods=20).std()
    vol240=r1.rolling(240,min_periods=60).std()
    range60=(hi.rolling(60,min_periods=20).max()/lo.rolling(60,min_periods=20).min()-1)
    base_scale=np.maximum(vol60*np.sqrt(15),range60*0.20)
    base_scale=pd.Series(np.maximum(base_scale,0.001),index=d.index)
    x["scale"]=base_scale
    x["vol_ratio_60_240"]=vol60/(vol240+1e-8)
    x["body_norm"]=(c/op-1)/(vol60+1e-5)
    x["range_norm"]=(hi/lo-1)/(vol60+1e-5)
    x["close_pos_1m"]=(c-lo)/(hi-lo).replace(0,np.nan)
    x["flow_1m"]=flow
    x["turnover_z_240"]=roll_z(np.log1p(d.turnover.clip(lower=0)),240).clip(-6,6)
    x["trades_z_240"]=roll_z(np.log1p(d.trade_count.clip(lower=0)),240).clip(-6,6)
    x["max_trade_share"]=d.max_trade_notional.clip(lower=0)/d.turnover.replace(0,np.nan)
    x["max_trade_share_z"]=roll_z(x["max_trade_share"],240).clip(-6,6)
    x["buy_count_share"]=d.buy_count/(d.buy_count+d.sell_count).replace(0,np.nan)

    for h in (3,5,10,15,30,60,120,240):
        ret=c/c.shift(h)-1
        rv=r1.rolling(max(h,3),min_periods=max(3,h//3)).std()
        norm=ret/(vol240*np.sqrt(max(h,1))+1e-5)
        bb=b.rolling(h,min_periods=max(2,h//3)).sum(); ss=s.rolling(h,min_periods=max(2,h//3)).sum()
        fi=(bb-ss)/(bb+ss).replace(0,np.nan)
        x[f"ret_norm_{h}"]=norm.clip(-10,10)
        x[f"flow_{h}"]=fi
        x[f"eff_norm_{h}"]=(norm/(fi.abs()+0.10)).clip(-20,20)
        x[f"align_{h}"]=np.sign(ret)*fi
        x[f"persist_{h}"]=(r1>0).rolling(h,min_periods=max(2,h//3)).mean()
        x[f"vol_ratio_{h}"]=rv/(vol240+1e-8)
        rh=hi.rolling(h,min_periods=max(2,h//3)).max(); rl=lo.rolling(h,min_periods=max(2,h//3)).min()
        span=(rh-rl).replace(0,np.nan)
        x[f"range_pos_{h}"]=(c-rl)/span

    x["accel_3v15"]=x["ret_norm_3"]-x["ret_norm_15"]*math.sqrt(3/15)
    x["accel_5v30"]=x["ret_norm_5"]-x["ret_norm_30"]*math.sqrt(5/30)
    x["flow_transition_5v30"]=x["flow_5"]-x["flow_30"]
    x["eff_transition_5v30"]=x["eff_norm_5"]-x["eff_norm_30"]
    x["ret_consensus"]=(np.sign(x["ret_norm_3"])+np.sign(x["ret_norm_5"])+np.sign(x["ret_norm_15"])+np.sign(x["ret_norm_30"]))/4
    x["flow_consensus"]=(np.sign(x["flow_3"])+np.sign(x["flow_5"])+np.sign(x["flow_15"])+np.sign(x["flow_30"]))/4

    # Causal geometry only.
    for h in (60,240):
        rh=hi.rolling(h,min_periods=h//2).max(); rl=lo.rolling(h,min_periods=h//2).min()
        span=(rh-rl).replace(0,np.nan)
        x[f"from_high_frac_{h}"]=(rh-c)/span
        x[f"from_low_frac_{h}"]=(c-rl)/span

    x["gap_recent"]=d.gap.astype(float).rolling(15,min_periods=1).max()
    return x.replace([np.inf,-np.inf],np.nan)

def targets(d,x):
    y=pd.DataFrame(index=d.index)
    c=d.close.astype(float); hi=d.high.astype(float); lo=d.low.astype(float)
    vol=c.pct_change().rolling(60,min_periods=20).std()
    range60=(hi.rolling(60,min_periods=20).max()/lo.rolling(60,min_periods=20).min()-1)
    for h in HORIZONS:
        fh=hi.shift(-1).iloc[::-1].rolling(h,min_periods=h).max().iloc[::-1]
        fl=lo.shift(-1).iloc[::-1].rolling(h,min_periods=h).min().iloc[::-1]
        up=fh/c-1; dn=1-fl/c
        scale=np.maximum(vol*np.sqrt(h),range60*np.sqrt(h/60)*0.20)
        scale=pd.Series(np.maximum(scale,0.0008),index=d.index)
        y[f"upn_{h}"]=(up/scale).clip(0,15)
        y[f"dnn_{h}"]=(dn/scale).clip(0,15)
        y[f"scale_{h}"]=scale
    return y

class Bundle:
    def __init__(self,features,med,model):self.features=features;self.med=med;self.model=model
    def predict(self,x):
        Z=x[self.features].fillna(self.med).to_numpy(float)
        p=self.model.predict(Z)
        out={}
        for j,h in enumerate(HORIZONS):
            out[f"upn_{h}"]=p[:,2*j];out[f"dnn_{h}"]=p[:,2*j+1]
        return pd.DataFrame(out,index=x.index)

def train(parts):
    XX=[];YY=[]
    for d,x,y in parts:
        mask=(x.gap_recent.fillna(1)==0)&y[[f"upn_{h}" for h in HORIZONS]+[f"dnn_{h}" for h in HORIZONS]].notna().all(axis=1)
        mask &= (np.arange(len(x))%3==0)
        XX.append(x.loc[mask]);YY.append(y.loc[mask])
    X=pd.concat(XX,ignore_index=True);Y=pd.concat(YY,ignore_index=True)
    feats=[c for c in X.columns if c not in ("scale","gap_recent")]
    med=X[feats].median()
    cols=[]
    for h in HORIZONS:cols += [f"upn_{h}",f"dnn_{h}"]
    model=ExtraTreesRegressor(n_estimators=180,max_depth=10,min_samples_leaf=70,max_features=0.75,n_jobs=-1,random_state=77)
    model.fit(X[feats].fillna(med).to_numpy(float),Y[cols].to_numpy(float))
    return Bundle(feats,med,model)

def scores(pred,y):
    ls=[];ss=[]
    for h in HORIZONS:
        scale=y[f"scale_{h}"].to_numpy(float)
        up=np.maximum(pred[f"upn_{h}"].to_numpy(float),0)*scale
        dn=np.maximum(pred[f"dnn_{h}"].to_numpy(float),0)*scale
        ls.append(up-ADVERSE*dn-RT_COST)
        ss.append(dn-ADVERSE*up-RT_COST)
    return np.vstack(ls).T@WEIGHTS,np.vstack(ss).T@WEIGHTS

@dataclass
class P:
    entry:float; edge:float; align:float; gba:float; gbf:float; stop_abs:float; min_hold:int; confirm:int; cooldown:int

def simulate(d,x,pred,y,p:P,record=False):
    L,S=scores(pred,y)
    pos=0;entry=0.;ei=-1;mfe=0.;mae=0.;tr=[];eq=1.;peak=1.;dd=0.;last_exit=-999
    pending_side=0;pending_count=0
    for i,row in d.iterrows():
        if bool(row.gap):
            if pos:
                gross=pos*(float(row.close)/entry-1);net=gross-RT_COST
                tr.append(dict(entry_i=ei,exit_i=i,side=pos,gross=gross,net=net,mfe=mfe,mae=mae,reason="GAP"))
                eq*=max(1e-9,1+net);pos=0;last_exit=i
            pending_side=0;pending_count=0
            peak=max(peak,eq);dd=max(dd,1-eq/peak);continue
        c=float(row.close);hi=float(row.high);lo=float(row.low)
        l=float(L[i]);s=float(S[i]);best=max(l,s);candidate=1 if l>s else -1;edge=abs(l-s)
        # Trade movement strength, not predicted reversal. Require the proposed
        # side to agree with already-observed multi-horizon price/flow state.
        rc=float(x.iloc[i].get("ret_consensus",0.0) or 0.0)
        fc=float(x.iloc[i].get("flow_consensus",0.0) or 0.0)
        r5=float(x.iloc[i].get("ret_norm_5",0.0) or 0.0)
        r15=float(x.iloc[i].get("ret_norm_15",0.0) or 0.0)
        r30=float(x.iloc[i].get("ret_norm_30",0.0) or 0.0)
        align_score=candidate*(0.35*rc+0.15*fc+0.20*np.tanh(r5)+0.18*np.tanh(r15)+0.12*np.tanh(r30))
        if pos:
            if pos>0:fav=hi/entry-1;adv=lo/entry-1;cur=c/entry-1;own,opp=l,s
            else:fav=1-lo/entry;adv=1-hi/entry;cur=1-c/entry;own,opp=s,l
            mfe=max(mfe,fav);mae=min(mae,adv);recoil=max(0,mfe-cur)
            cap=max(p.gba,p.gbf*max(mfe,0))
            age=i-ei
            reverse=age>=p.min_hold and opp>=p.entry and opp-own>=p.edge
            stop=age>=1 and cur<=-p.stop_abs
            protect=age>=p.min_hold and mfe>=p.entry and recoil>=cap
            weaken=age>=p.min_hold and own<0 and recoil>=p.gba*0.6
            if reverse or stop or protect or weaken:
                reason="REVERSE" if reverse else ("ADVERSE_STOP" if stop else ("MFE_PROTECT" if protect else "WEAKEN"))
                gross=pos*(c/entry-1);net=gross-RT_COST
                before=eq;worst=mae-RT_COST
                peak=max(peak,before);dd=max(dd,1-before*max(1e-9,1+worst)/peak)
                eq*=max(1e-9,1+net);peak=max(peak,eq);dd=max(dd,1-eq/peak)
                tr.append(dict(entry_i=ei,exit_i=i,side=pos,gross=gross,net=net,mfe=mfe,mae=mae,reason=reason))
                np_side=(1 if l>s else -1) if reverse else 0
                pos=0;last_exit=i;mfe=0.;mae=0.;pending_side=0;pending_count=0
                if np_side:
                    pos=np_side;entry=c;ei=i
            continue
        if i-last_exit<p.cooldown:continue
        if best>=p.entry and edge>=p.edge and align_score>=p.align:
            if candidate==pending_side:pending_count+=1
            else:pending_side=candidate;pending_count=1
            if pending_count>=p.confirm:
                pos=candidate;entry=c;ei=i;mfe=0.;mae=0.;pending_side=0;pending_count=0
        else:
            pending_side=0;pending_count=0
    if pos:
        c=float(d.iloc[-1].close);gross=pos*(c/entry-1);net=gross-RT_COST
        tr.append(dict(entry_i=ei,exit_i=len(d)-1,side=pos,gross=gross,net=net,mfe=mfe,mae=mae,reason="END"));eq*=max(1e-9,1+net)
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
    if m["trades"]<20:return -999
    activity=min(1.0,m["trades_per_day"]/1.5)
    capture=max(-1,min(1,m["median_mfe_capture"]))
    return math.log(max(m["equity"],1e-9))-2.75*m["max_drawdown"]+0.12*capture+0.06*activity-0.00005*m["trades"]

def tune(d,x,pred,y):
    best=None
    for entry in (0.0008,0.0012,0.0018,0.0025):
      for edge in (0.00025,0.0005,0.0010):
       for align in (0.00,0.15,0.30,0.45):
        for gba in (0.0010,0.0015,0.0025):
         for gbf in (0.15,0.25,0.40):
          for stop_abs in (0.004,0.006,0.009):
           for confirm in (1,2):
            p=P(entry,edge,align,gba,gbf,stop_abs,2,confirm,2)
            m=simulate(d,x,pred,y,p,False);v=obj(m)
            if best is None or v>best[0]:best=(v,p,m)
    return best

def enrich(d,trades,period):
    out=[]
    for z in trades:
        a=d.iloc[int(z["entry_i"])];b=d.iloc[int(z["exit_i"])]
        q=dict(z);q.update(period=period,entry_ts_ms=int(a.ts_ms),exit_ts_ms=int(b.ts_ms),
                           side_name="LONG" if z["side"]>0 else "SHORT",
                           mfe_giveback=max(0,z["mfe"]-z["gross"]),
                           mfe_capture=(z["gross"]/z["mfe"] if z["mfe"]>1e-9 else None))
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

def daily_stats(d,trades,exposure=1.0):
    by={}
    for z in trades:
        day=pd.to_datetime(int(d.iloc[int(z["exit_i"])].ts_ms),unit="ms",utc=True).strftime("%Y-%m-%d")
        by.setdefault(day,1.0);by[day]*=max(1e-9,1+exposure*z["net"])
    vals=[v-1 for v in by.values()]
    return dict(days=len(vals),positive_days=sum(v>0 for v in vals),positive_day_rate=(sum(v>0 for v in vals)/len(vals) if vals else 0),
                mean_daily=statistics.fmean(vals) if vals else 0,median_daily=statistics.median(vals) if vals else 0,
                best_daily=max(vals) if vals else 0,worst_daily=min(vals) if vals else 0)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--master-root",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    blocks={}
    for name,rel in PERIODS:
        d=load(a.master_root/rel);x=features(d);y=targets(d,x);blocks[name]=(d,x,y)
    model=train([blocks["TRAIN_JUL12_AUG07"],blocks["TRAIN_AUG08_SEP01"]])
    preds={n:model.predict(x) for n,(d,x,y) in blocks.items()}
    _,params,val=tune(blocks["VALIDATE_SEP01_OCT01"][0],blocks["VALIDATE_SEP01_OCT01"][1],preds["VALIDATE_SEP01_OCT01"],blocks["VALIDATE_SEP01_OCT01"][2])

    metrics={};alltr=[]
    for n,(d,x,y) in blocks.items():
        m=simulate(d,x,preds[n],y,params,True);metrics[n]={k:v for k,v in m.items() if k!="trades_rows"};alltr+=enrich(d,m["trades_rows"],n)
    hd,hx,hy=blocks["HOLDOUT_OCT04_NOV03"];hm=simulate(hd,hx,preds["HOLDOUT_OCT04_NOV03"],hy,params,True)
    htr=enrich(hd,hm["trades_rows"],"HOLDOUT_OCT04_NOV03")
    lev=[leverage(htr,L) for L in (1,5,10,25)]
    ds={str(L):daily_stats(hd,hm["trades_rows"],exposure=L*.20) for L in (1,5,10,25)}
    imp=sorted(zip(model.features,model.model.feature_importances_),key=lambda z:z[1],reverse=True)[:35]
    rep=dict(version="HYPE-MOVEMENT-SIGNATURE-STRENGTH-V3",research_only=True,real_orders=False,
             train_periods=["Jul12-Aug07","Aug08-Sep01"],validation="Sep01-Oct01",untouched_holdout="Oct04-Nov03",
             feature_count=len(model.features),params=params.__dict__,validation_metrics={k:v for k,v in val.items() if k!="trades_rows"},
             period_metrics=metrics,holdout_leverage=lev,holdout_daily=ds,
             top_features=[{"feature":k,"importance":float(v)} for k,v in imp],
             warning="Historical research only. V3 was designed after inspection of V2 holdout failure modes, so Oct04-Nov03 is diagnostic, not pristine untouched OOS. 25x is an isolated-margin approximation, not an exact Bybit liquidation engine.")
    (a.out/"MOVEMENT_V2_REPORT.json").write_text(json.dumps(rep,indent=2),encoding="utf-8")
    pd.DataFrame(alltr).to_csv(a.out/"MOVEMENT_V2_TRADES.csv",index=False)
    print(json.dumps(rep,indent=2))

if __name__=="__main__":main()
