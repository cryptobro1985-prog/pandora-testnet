#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math, statistics
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor

from research.hype_movement_signature import replay_normalized_v2 as base

PERIODS = base.PERIODS
RT_COST = base.RT_COST
HORIZONS = (5, 15, 30, 60, 120)
WEIGHTS = np.array([0.10, 0.25, 0.30, 0.25, 0.10], dtype=float)

@dataclass
class Params:
    min_score: float
    min_ratio: float
    min_edge: float
    confirm: int
    min_hold: int
    cooldown: int
    mfe_arm: float
    giveback_abs: float
    giveback_frac: float
    reverse_score: float

def load_block(root: Path, rel: str):
    d = base.load(root / rel)
    x = features(d)
    y = targets(d)
    return d, x, y

def zscore(s: pd.Series, w: int):
    m = s.rolling(w, min_periods=max(30, w//4)).mean()
    sd = s.rolling(w, min_periods=max(30, w//4)).std().replace(0, np.nan)
    return ((s-m)/sd).clip(-8, 8)

def features(d: pd.DataFrame):
    x = base.features(d).copy()
    c = d.close.astype(float)
    hi = d.high.astype(float)
    lo = d.low.astype(float)
    b = d.buy_notional.astype(float).clip(lower=0)
    s = d.sell_notional.astype(float).clip(lower=0)
    tc = d.trade_count.astype(float).clip(lower=0)
    turn = d.turnover.astype(float).clip(lower=0)
    r1 = c.pct_change()
    flow1 = (b-s)/(b+s).replace(0,np.nan)

    # Explicit direction/efficiency families derived only from completed history.
    for h in (3,5,10,15,30,60,120,240):
        ret = c/c.shift(h)-1
        bb = b.rolling(h, min_periods=max(2,h//3)).sum()
        ss = s.rolling(h, min_periods=max(2,h//3)).sum()
        flow = (bb-ss)/(bb+ss).replace(0,np.nan)
        abs_flow = flow.abs()+0.08
        x[f"px_flow_eff_{h}"] = (ret/abs_flow).clip(-0.25,0.25)
        x[f"flow_x_ret_{h}"] = (flow*ret).clip(-0.05,0.05)
        x[f"turn_z_{h}"] = zscore(np.log1p(turn.rolling(h,min_periods=max(2,h//3)).sum()), 240)
        x[f"trade_z_{h}"] = zscore(np.log1p(tc.rolling(h,min_periods=max(2,h//3)).sum()), 240)
        x[f"up_persist_{h}"] = (r1>0).rolling(h,min_periods=max(2,h//3)).mean()
        x[f"down_persist_{h}"] = (r1<0).rolling(h,min_periods=max(2,h//3)).mean()

    x["flow_accel_5_30"] = x["flow_5"] - x["flow_30"]
    x["flow_accel_15_60"] = x["flow_15"] - x["flow_60"]
    x["eff_accel_5_30"] = x["px_flow_eff_5"] - x["px_flow_eff_30"]
    x["eff_accel_15_60"] = x["px_flow_eff_15"] - x["px_flow_eff_60"]
    x["price_accel_5_30"] = x["ret_norm_5"] - x["ret_norm_30"]*math.sqrt(5/30)
    x["price_accel_15_60"] = x["ret_norm_15"] - x["ret_norm_60"]*math.sqrt(15/60)

    # Causal squeeze/expansion geometry, not Local labels.
    vol = r1.rolling(60,min_periods=20).std()
    for h in (30,60,120,240):
        rh = hi.rolling(h,min_periods=max(10,h//3)).max()
        rl = lo.rolling(h,min_periods=max(10,h//3)).min()
        span = (rh-rl).replace(0,np.nan)
        x[f"range_width_{h}"] = ((rh/rl)-1)/(vol*np.sqrt(h)+1e-6)
        x[f"range_pos_raw_{h}"] = (c-rl)/span

    x["flow_sign_stability_15"] = np.sign(flow1).rolling(15,min_periods=5).mean().abs()
    x["flow_sign_stability_60"] = np.sign(flow1).rolling(60,min_periods=20).mean().abs()
    return x.replace([np.inf,-np.inf],np.nan)

def future_roll(s: pd.Series, h: int, fn: str):
    z = s.shift(-1).iloc[::-1].rolling(h,min_periods=h)
    out = z.max() if fn=="max" else z.min()
    return out.iloc[::-1]

def targets(d: pd.DataFrame):
    y = pd.DataFrame(index=d.index)
    c = d.close.astype(float)
    hi = d.high.astype(float)
    lo = d.low.astype(float)
    r1 = c.pct_change()
    vol60 = r1.rolling(60,min_periods=20).std()
    range60 = hi.rolling(60,min_periods=20).max()/lo.rolling(60,min_periods=20).min()-1

    for h in HORIZONS:
        fh = future_roll(hi,h,"max")
        fl = future_roll(lo,h,"min")
        up = (fh/c-1).clip(lower=0)
        dn = (1-fl/c).clip(lower=0)
        scale = np.maximum(vol60*np.sqrt(h), range60*np.sqrt(h/60)*0.18)
        scale = pd.Series(np.maximum(scale,0.0008),index=d.index)
        y[f"upn_{h}"] = (up/scale).clip(0,20)
        y[f"dnn_{h}"] = (dn/scale).clip(0,20)
        y[f"scale_{h}"] = scale
    return y

class Model:
    def __init__(self, feats, med, reg):
        self.feats=feats; self.med=med; self.reg=reg
    def predict(self,x):
        z=x[self.feats].fillna(self.med).to_numpy(float)
        p=self.reg.predict(z)
        out={}
        j=0
        for h in HORIZONS:
            out[f"upn_{h}"]=p[:,j]; j+=1
            out[f"dnn_{h}"]=p[:,j]; j+=1
        return pd.DataFrame(out,index=x.index)

def train(parts):
    XX=[]; YY=[]
    target_cols=[]
    for h in HORIZONS: target_cols += [f"upn_{h}",f"dnn_{h}"]
    for d,x,y in parts:
        m=(x["gap_recent"].fillna(1)==0) & y[target_cols].notna().all(axis=1)
        # sample every 2 minutes: enough coverage, less serial duplication
        m &= (np.arange(len(x)) % 2 == 0)
        XX.append(x.loc[m]); YY.append(y.loc[m,target_cols])
    X=pd.concat(XX,ignore_index=True); Y=pd.concat(YY,ignore_index=True)
    feats=[c for c in X.columns if c not in ("scale","gap_recent")]
    med=X[feats].median()
    reg=ExtraTreesRegressor(
        n_estimators=260,max_depth=12,min_samples_leaf=45,max_features=0.70,
        n_jobs=-1,random_state=20261110
    )
    reg.fit(X[feats].fillna(med).to_numpy(float),Y.to_numpy(float))
    return Model(feats,med,reg)

def score_vectors(pred: pd.DataFrame, y: pd.DataFrame):
    long_parts=[]; short_parts=[]; long_ratio=[]; short_ratio=[]
    for h,w in zip(HORIZONS,WEIGHTS):
        scale=y[f"scale_{h}"].to_numpy(float)
        up=np.maximum(pred[f"upn_{h}"].to_numpy(float),0)*scale
        dn=np.maximum(pred[f"dnn_{h}"].to_numpy(float),0)*scale
        l=(up-0.90*dn-RT_COST)
        s=(dn-0.90*up-RT_COST)
        long_parts.append(w*l); short_parts.append(w*s)
        long_ratio.append(w*(up/(dn+RT_COST)))
        short_ratio.append(w*(dn/(up+RT_COST)))
    L=np.sum(np.vstack(long_parts),axis=0)
    S=np.sum(np.vstack(short_parts),axis=0)
    LR=np.sum(np.vstack(long_ratio),axis=0)
    SR=np.sum(np.vstack(short_ratio),axis=0)
    return L,S,LR,SR

def summarize(trades, d):
    n=len(trades)
    gp=sum(max(0,z["net"]) for z in trades)
    gl=-sum(min(0,z["net"]) for z in trades)
    eq=1.0; peak=1.0; dd=0.0
    for z in trades:
        eq*=max(1e-9,1+z["net"])
        peak=max(peak,eq); dd=max(dd,1-eq/peak)
    days=max(1,(float(d.ts_ms.iloc[-1])-float(d.ts_ms.iloc[0]))/86400000)
    wins=sum(z["net"]>0 for z in trades)
    caps=[z["gross"]/z["mfe"] for z in trades if z["mfe"]>1e-9]
    return {
        "equity":eq,"total_return":eq-1,"max_drawdown":dd,
        "trades":n,"trades_per_day":n/days,
        "win_rate":wins/n if n else 0.0,
        "profit_factor":gp/gl if gl else (99.0 if gp else 0.0),
        "mean_net_trade":statistics.fmean([z["net"] for z in trades]) if trades else 0.0,
        "median_mfe":statistics.median([z["mfe"] for z in trades]) if trades else 0.0,
        "median_mae":statistics.median([z["mae"] for z in trades]) if trades else 0.0,
        "median_mfe_capture":statistics.median(caps) if caps else 0.0,
    }

def simulate(d,pred,y,p:Params,record=False):
    L,S,LR,SR=score_vectors(pred,y)
    pos=0; entry=0.; ei=-1; mfe=0.; mae=0.; last_exit=-999
    pending=0; pc=0; trades=[]
    for i,row in d.iterrows():
        if bool(row.gap):
            if pos:
                c=float(row.close); gross=pos*(c/entry-1); net=gross-RT_COST
                trades.append(dict(entry_i=ei,exit_i=i,side=pos,gross=gross,net=net,mfe=mfe,mae=mae,reason="GAP"))
            pos=0; pending=0; pc=0; last_exit=i; continue
        c=float(row.close); hi=float(row.high); lo=float(row.low)
        l=float(L[i]); s=float(S[i]); lr=float(LR[i]); sr=float(SR[i])
        cand=1 if l>s else -1
        own_score=max(l,s); opp_score=min(l,s)
        own_ratio=lr if cand>0 else sr
        edge=abs(l-s)
        qualifies=(own_score>=p.min_score and own_ratio>=p.min_ratio and edge>=p.min_edge)

        if pos:
            if pos>0:
                fav=hi/entry-1; adv=lo/entry-1; cur=c/entry-1; own=l; opp=s; ownr=lr; oppr=sr
            else:
                fav=1-lo/entry; adv=1-hi/entry; cur=1-c/entry; own=s; opp=l; ownr=sr; oppr=lr
            mfe=max(mfe,fav); mae=min(mae,adv); age=i-ei
            recoil=max(0,mfe-cur)
            cap=max(p.giveback_abs,p.giveback_frac*max(mfe,0))
            reverse=(age>=p.min_hold and opp>=p.reverse_score and oppr>=p.min_ratio and opp-own>=p.min_edge)
            protect=(age>=p.min_hold and mfe>=p.mfe_arm and recoil>=cap and own<max(0,p.min_score*0.45))
            decay=(age>=p.min_hold and own<=0 and ownr<1.0 and recoil>=p.giveback_abs*0.5)
            if reverse or protect or decay:
                reason="REVERSE" if reverse else ("MFE_PROTECT" if protect else "DECAY")
                gross=pos*(c/entry-1); net=gross-RT_COST
                trades.append(dict(entry_i=ei,exit_i=i,side=pos,gross=gross,net=net,mfe=mfe,mae=mae,reason=reason))
                oldpos=pos; pos=0; last_exit=i; mfe=0.; mae=0.; pending=0; pc=0
                if reverse:
                    pos=-oldpos; entry=c; ei=i
            continue

        if i-last_exit < p.cooldown: continue
        if qualifies:
            if cand==pending: pc+=1
            else: pending=cand; pc=1
            if pc>=p.confirm:
                pos=cand; entry=c; ei=i; mfe=0.; mae=0.; pending=0; pc=0
        else:
            pending=0; pc=0

    if pos:
        c=float(d.iloc[-1].close); gross=pos*(c/entry-1); net=gross-RT_COST
        trades.append(dict(entry_i=ei,exit_i=len(d)-1,side=pos,gross=gross,net=net,mfe=mfe,mae=mae,reason="END"))
    m=summarize(trades,d)
    m["trades_rows"]=trades if record else None
    return m

def objective(m):
    # Reject noisy churn and pathological low-frequency overfit.
    if m["trades"]<12 or m["trades_per_day"]<0.35 or m["trades_per_day"]>8: return -1e9
    if m["profit_factor"]<1.15 or m["median_mfe"]<=0: return -1e9
    return (
        math.log(max(m["equity"],1e-9))
        - 2.8*m["max_drawdown"]
        + 0.30*min(2.0,max(0.0,m["profit_factor"]-1.0))
        + 0.15*max(-1.0,min(1.0,m["median_mfe_capture"]))
        - 0.05*abs(m["trades_per_day"]-2.5)
    )

def tune(d,pred,y):
    best=None; rows=[]
    for score in (0.0005,0.0008,0.0010,0.0013,0.0016):
      for ratio in (1.5,2.0,2.5,3.0):
       for edge in (0.0003,0.0005,0.0008):
        for confirm in (1,2,3):
         for arm in (0.0025,0.0040,0.0060):
          p=Params(score,ratio,edge,confirm,3,2,arm,0.0015,0.35,score)
          m=simulate(d,pred,y,p,False); v=objective(m)
          row={"objective":v,**p.__dict__,**{k:z for k,z in m.items() if k!="trades_rows"}}
          rows.append(row)
          if best is None or v>best[0]: best=(v,p,m)
    return best,rows

def enrich(d,tr,period):
    out=[]
    for z in tr:
        a=d.iloc[int(z["entry_i"])]; b=d.iloc[int(z["exit_i"])]
        q=dict(z)
        q.update(
            period=period,
            entry_ts_ms=int(a.ts_ms),exit_ts_ms=int(b.ts_ms),
            entry_price=float(a.close),exit_price=float(b.close),
            side_name="LONG" if z["side"]>0 else "SHORT",
            mfe_capture=(z["gross"]/z["mfe"] if z["mfe"]>1e-9 else None),
            mfe_giveback=max(0,z["mfe"]-z["gross"]),
        )
        out.append(q)
    return out

def leverage(trades,L,margin=.20):
    exposure=L*margin; liq_thr=max(.005,1/L-.005)
    eq=1.; peak=1.; dd=0.; liqs=0
    for z in trades:
        if -z["mae"]>=liq_thr:
            r=-margin; liqs+=1
        else:
            r=exposure*z["net"]
        eq*=max(1e-9,1+r); peak=max(peak,eq); dd=max(dd,1-eq/peak)
    return {"leverage":L,"margin_fraction":margin,"exposure_x_equity":exposure,
            "equity_multiple":eq,"total_return":eq-1,"max_drawdown":dd,
            "approx_liquidations":liqs}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--master-root",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args(); a.out.mkdir(parents=True,exist_ok=True)

    blocks={n:load_block(a.master_root,rel) for n,rel in PERIODS}
    model=train([blocks["TRAIN_JUL12_AUG07"],blocks["TRAIN_AUG08_SEP01"]])
    preds={n:model.predict(x) for n,(d,x,y) in blocks.items()}

    vd,vx,vy=blocks["VALIDATE_SEP01_OCT01"]
    best,grid=tune(vd,preds["VALIDATE_SEP01_OCT01"],vy)
    score,p,val=best

    metrics={}; alltr=[]
    for n,(d,x,y) in blocks.items():
        m=simulate(d,preds[n],y,p,True)
        metrics[n]={k:v for k,v in m.items() if k!="trades_rows"}
        alltr += enrich(d,m["trades_rows"],n)

    hold=[z for z in alltr if z["period"]=="HOLDOUT_OCT04_NOV03"]
    imp=sorted(zip(model.feats,model.reg.feature_importances_),key=lambda z:z[1],reverse=True)[:50]
    report={
        "version":"HYPE-UNIVERSAL-MOVEMENT-SIGNATURE-V1",
        "research_only":True,"real_orders":False,
        "local_dependency":False,
        "teacher_local_used_for_decision":False,
        "train_periods":["Jul12-Aug07","Aug08-Sep01"],
        "validation":"Sep01-Oct01",
        "untouched_holdout":"Oct04-Nov03",
        "target":"future favorable/adverse excursion LONG/SHORT, not Local labels",
        "params":p.__dict__,
        "validation_metrics":{k:v for k,v in val.items() if k!="trades_rows"},
        "period_metrics":metrics,
        "holdout_leverage":[leverage(hold,L) for L in (1,5,10,25)],
        "top_features":[{"feature":k,"importance":float(v)} for k,v in imp],
        "anti_leakage":{
            "uses_only_completed_historical_minutes":True,
            "target_eval_83_110_forbidden":True,
            "no_local_high_low_features":True,
            "validation_used_only_for_policy_selection":True,
            "holdout_not_used_for_tuning":True,
        },
        "warning":"Research simulation only. 25x liquidation is approximate and not exact Bybit tier/margin math."
    }
    (a.out/"UNIVERSAL_MOVEMENT_V1_REPORT.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    pd.DataFrame(alltr).to_csv(a.out/"UNIVERSAL_MOVEMENT_V1_TRADES.csv",index=False)
    pd.DataFrame(grid).sort_values("objective",ascending=False).head(500).to_csv(a.out/"UNIVERSAL_MOVEMENT_V1_GRID_TOP.csv",index=False)
    print(json.dumps(report,indent=2))

if __name__=="__main__":
    main()
