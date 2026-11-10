#!/usr/bin/env python3
from __future__ import annotations

import argparse, gzip, json, math, statistics
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor

PERIODS = [
    ("DEV_JUL12_AUG07", "01_JUL12_AUG07_FULL_MICRO/compact_1m.jsonl.gz"),
    ("VAL_AUG08_SEP01", "02_AUG08_SEP01/compact_1m.jsonl.gz"),
    ("TEST_SEP01_OCT01", "03_SEP01_OCT01/compact_1m.jsonl.gz"),
    ("HOLDOUT_OCT04_NOV03", "04_OCT04_NOV03/compact_1m.jsonl.gz"),
]
HORIZONS = (5, 15, 30, 60)
RT_COST = 0.0012
ADVERSE_PENALTY = 0.70
WEIGHTS = np.array([0.15, 0.35, 0.30, 0.20], dtype=float)


def load_jsonl_gz(path: Path) -> pd.DataFrame:
    rows=[]
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    df=pd.DataFrame(rows)
    df=df.sort_values("ts_ms").drop_duplicates("ts_ms").reset_index(drop=True)
    for c in ("open","high","low","close","buy_notional","sell_notional","buy_count","sell_count",
              "trade_count","turnover","volume","max_trade_notional","flow_imbalance"):
        if c in df:
            df[c]=pd.to_numeric(df[c],errors="coerce")
    df["gap"]=df.get("gap",False).fillna(False).astype(bool)
    return df


def causal_features(df: pd.DataFrame) -> pd.DataFrame:
    x=pd.DataFrame(index=df.index)
    close=df["close"].astype(float)
    high=df["high"].astype(float)
    low=df["low"].astype(float)
    op=df["open"].astype(float)
    turnover=df["turnover"].clip(lower=0).astype(float)
    buy=df["buy_notional"].clip(lower=0).astype(float)
    sell=df["sell_notional"].clip(lower=0).astype(float)
    tc=df["trade_count"].clip(lower=0).astype(float)
    maxtr=df["max_trade_notional"].clip(lower=0).astype(float)
    total=(buy+sell).replace(0,np.nan)
    flow=(buy-sell)/total
    r1=close.pct_change()

    x["body_1m"]=close/op-1
    x["range_1m"]=high/low-1
    x["close_pos_1m"]=(close-low)/(high-low).replace(0,np.nan)
    x["flow_1m"]=flow
    x["log_turnover_1m"]=np.log1p(turnover)
    x["log_trade_count_1m"]=np.log1p(tc)
    x["max_trade_share_1m"]=maxtr/turnover.replace(0,np.nan)
    x["buy_count_share_1m"]=df["buy_count"]/(df["buy_count"]+df["sell_count"]).replace(0,np.nan)

    for h in (3,5,10,15,30,60,120,240):
        ret=close/close.shift(h)-1
        x[f"ret_{h}m"]=ret
        b=buy.rolling(h,min_periods=max(2,h//3)).sum()
        s=sell.rolling(h,min_periods=max(2,h//3)).sum()
        den=(b+s).replace(0,np.nan)
        fi=(b-s)/den
        x[f"flow_{h}m"]=fi
        x[f"eff_{h}m"]=ret/(fi.abs()+0.05)
        x[f"flow_price_align_{h}m"]=np.sign(ret)*fi
        x[f"log_turnover_{h}m"]=np.log1p(turnover.rolling(h,min_periods=max(2,h//3)).sum())
        x[f"trade_intensity_{h}m"]=np.log1p(tc.rolling(h,min_periods=max(2,h//3)).sum())
        x[f"persistence_up_{h}m"]=(r1>0).rolling(h,min_periods=max(2,h//3)).mean()
        x[f"vol_{h}m"]=r1.rolling(h,min_periods=max(3,h//3)).std()
        rh=high.rolling(h,min_periods=max(2,h//3)).max()
        rl=low.rolling(h,min_periods=max(2,h//3)).min()
        span=(rh-rl).replace(0,np.nan)
        x[f"range_pos_{h}m"]=(close-rl)/span
        x[f"dist_high_{h}m"]=close/rh-1
        x[f"dist_low_{h}m"]=close/rl-1

    x["accel_3v15"]=x["ret_3m"] - x["ret_15m"]*(3/15)
    x["accel_5v30"]=x["ret_5m"] - x["ret_30m"]*(5/30)
    x["ret_agree_3_5_15"]=(np.sign(x["ret_3m"])+np.sign(x["ret_5m"])+np.sign(x["ret_15m"]))/3
    x["flow_agree_3_5_15"]=(np.sign(x["flow_3m"])+np.sign(x["flow_5m"])+np.sign(x["flow_15m"]))/3
    x["flow_transition_5v30"]=x["flow_5m"]-x["flow_30m"]
    x["eff_transition_5v30"]=x["eff_5m"]-x["eff_30m"]

    for h in (60,240):
        rh=high.rolling(h,min_periods=h//2).max()
        rl=low.rolling(h,min_periods=h//2).min()
        span=(rh-rl).replace(0,np.nan)
        x[f"retrace_from_high_frac_{h}m"]=(rh-close)/span
        x[f"retrace_from_low_frac_{h}m"]=(close-rl)/span

    x["gap_now"]=df["gap"].astype(float)
    x["gap_recent_15m"]=df["gap"].astype(float).rolling(15,min_periods=1).max()
    return x.replace([np.inf,-np.inf],np.nan)


def future_targets(df: pd.DataFrame) -> pd.DataFrame:
    y=pd.DataFrame(index=df.index)
    c=df["close"].astype(float)
    hpx=df["high"].astype(float)
    lpx=df["low"].astype(float)
    for h in HORIZONS:
        fh=hpx.shift(-1).iloc[::-1].rolling(h,min_periods=h).max().iloc[::-1]
        fl=lpx.shift(-1).iloc[::-1].rolling(h,min_periods=h).min().iloc[::-1]
        y[f"up_{h}m"]=fh/c-1
        y[f"down_{h}m"]=1-fl/c
    return y


def make_dataset(root: Path):
    blocks={}
    for name,rel in PERIODS:
        df=load_jsonl_gz(root/rel)
        x=causal_features(df)
        y=future_targets(df)
        blocks[name]=(df,x,y)
    return blocks


class ModelBundle:
    def __init__(self,feature_names,medians,model):
        self.feature_names=feature_names
        self.medians=medians
        self.model=model

    def predict(self,x):
        z=x[self.feature_names].copy().fillna(self.medians)
        pred=self.model.predict(z.to_numpy(dtype=float))
        out={}
        for j,h in enumerate(HORIZONS):
            out[f"up_{h}m"]=pred[:,2*j]
            out[f"down_{h}m"]=pred[:,2*j+1]
        return pd.DataFrame(out,index=x.index)


def train_bundle(parts, seed=42):
    xs=[];ys=[]
    for df,x,y in parts:
        mask=(x["gap_recent_15m"].fillna(1)==0)
        mask &= y.notna().all(axis=1)
        mask &= np.arange(len(x))%2==0
        xs.append(x.loc[mask])
        ys.append(y.loc[mask])
    X=pd.concat(xs,ignore_index=True)
    Y=pd.concat(ys,ignore_index=True)
    features=[c for c in X.columns if c!="gap_now"]
    med=X[features].median(numeric_only=True)
    Xn=X[features].fillna(med).to_numpy(dtype=float)
    cols=[]
    for h in HORIZONS:
        cols += [f"up_{h}m",f"down_{h}m"]
    Yn=Y[cols].to_numpy(dtype=float)
    model=ExtraTreesRegressor(
        n_estimators=160,max_depth=14,min_samples_leaf=24,max_features=0.72,
        n_jobs=-1,random_state=seed
    )
    model.fit(Xn,Yn)
    return ModelBundle(features,med,model)


def score_predictions(pred):
    longs=[];shorts=[]
    for h in HORIZONS:
        u=np.maximum(pred[f"up_{h}m"].to_numpy(float),0)
        d=np.maximum(pred[f"down_{h}m"].to_numpy(float),0)
        longs.append(u-ADVERSE_PENALTY*d-RT_COST)
        shorts.append(d-ADVERSE_PENALTY*u-RT_COST)
    L=np.vstack(longs).T@WEIGHTS
    S=np.vstack(shorts).T@WEIGHTS
    return L,S


@dataclass
class Params:
    entry: float
    edge: float
    giveback_abs: float
    giveback_frac: float
    min_hold: int


def simulate(df,pred,params:Params,record=True):
    L,S=score_predictions(pred)
    pos=0
    entry=0.
    entry_i=-1
    mfe=0.
    mae=0.
    trades=[]
    eq=1.
    peak_eq=1.
    maxdd=0.
    last_exit_i=-999

    for i,row in df.iterrows():
        if bool(row.get("gap",False)):
            if pos:
                gross=pos*(float(row.close)/entry-1)
                net=gross-RT_COST
                eq*=max(1e-9,1+net)
                trades.append(dict(entry_i=entry_i,exit_i=i,side=pos,entry=entry,exit=float(row.close),
                                   gross=gross,net=net,mfe=mfe,mae=mae,reason="GAP"))
                pos=0
                last_exit_i=i
            peak_eq=max(peak_eq,eq)
            maxdd=max(maxdd,1-eq/peak_eq)
            continue

        close=float(row.close)
        hi=float(row.high)
        lo=float(row.low)
        long=float(L[i])
        short=float(S[i])
        edge=abs(long-short)

        if pos:
            if pos>0:
                fav=hi/entry-1
                adv=lo/entry-1
                cur=close/entry-1
                own,opp=long,short
            else:
                fav=1-lo/entry
                adv=1-hi/entry
                cur=1-close/entry
                own,opp=short,long
            mfe=max(mfe,fav)
            mae=min(mae,adv)
            recoil=max(0.,mfe-cur)
            cap=max(params.giveback_abs,params.giveback_frac*max(mfe,0.0))
            age=i-entry_i
            reverse=(age>=params.min_hold and opp>=params.entry and (opp-own)>=params.edge)
            protect=(age>=params.min_hold and mfe>params.entry and recoil>=cap and own<params.entry)
            weaken=(age>=params.min_hold and own<0 and recoil>=params.giveback_abs*0.5)
            if reverse or protect or weaken:
                reason="REVERSE" if reverse else ("MFE_PROTECT" if protect else "WEAKEN")
                gross=pos*(close/entry-1)
                net=gross-RT_COST
                eq_before=eq
                worst=mae-RT_COST
                worst_eq=eq_before*max(1e-9,1+worst)
                peak_eq=max(peak_eq,eq_before)
                maxdd=max(maxdd,1-worst_eq/peak_eq)
                eq*=max(1e-9,1+net)
                peak_eq=max(peak_eq,eq)
                maxdd=max(maxdd,1-eq/peak_eq)
                trades.append(dict(entry_i=entry_i,exit_i=i,side=pos,entry=entry,exit=close,
                                   gross=gross,net=net,mfe=mfe,mae=mae,reason=reason))
                newpos=0
                if reverse:
                    newpos=1 if long>short else -1
                pos=0
                last_exit_i=i
                if newpos:
                    pos=newpos
                    entry=close
                    entry_i=i
                    mfe=0.
                    mae=0.
            continue

        if i-last_exit_i<1:
            continue
        best=max(long,short)
        if best>=params.entry and edge>=params.edge:
            pos=1 if long>short else -1
            entry=close
            entry_i=i
            mfe=0.
            mae=0.

    if pos:
        close=float(df.iloc[-1].close)
        gross=pos*(close/entry-1)
        net=gross-RT_COST
        eq_before=eq
        worst_eq=eq_before*max(1e-9,1+mae-RT_COST)
        peak_eq=max(peak_eq,eq_before)
        maxdd=max(maxdd,1-worst_eq/peak_eq)
        eq*=max(1e-9,1+net)
        trades.append(dict(entry_i=entry_i,exit_i=len(df)-1,side=pos,entry=entry,exit=close,
                           gross=gross,net=net,mfe=mfe,mae=mae,reason="END"))

    n=len(trades)
    wins=sum(t["net"]>0 for t in trades)
    gp=sum(max(0,t["net"]) for t in trades)
    gl=-sum(min(0,t["net"]) for t in trades)
    captures=[max(-2,min(2,t["gross"]/t["mfe"])) for t in trades if t["mfe"]>1e-9]
    givebacks=[max(0,t["mfe"]-t["gross"]) for t in trades]
    days=max(1,(float(df.ts_ms.iloc[-1])-float(df.ts_ms.iloc[0]))/86400000)
    return {
        "equity":eq,
        "total_return":eq-1,
        "max_drawdown":maxdd,
        "trades":n,
        "trades_per_day":n/days,
        "win_rate":wins/n if n else None,
        "profit_factor":gp/gl if gl>0 else (99 if gp>0 else None),
        "median_mfe_capture":statistics.median(captures) if captures else None,
        "median_mfe_giveback":statistics.median(givebacks) if givebacks else None,
        "mean_net_trade":statistics.fmean([t["net"] for t in trades]) if trades else None,
        "trades_rows":trades if record else None,
    }


def objective(m):
    if m["trades"]<8 or m["total_return"]<=-0.5:
        return -999
    return math.log(max(m["equity"],1e-9)) - 1.75*m["max_drawdown"] - 0.00035*m["trades"]


def tune(df,pred):
    best=None
    for entry in (0.0015,0.0025,0.0040,0.0060):
      for edge in (0.0010,0.0020,0.0035):
       for gba in (0.0015,0.0025,0.0040,0.0060):
        for gbf in (0.25,0.40,0.55):
         p=Params(entry,edge,gba,gbf,2)
         m=simulate(df,pred,p,record=False)
         s=objective(m)
         if best is None or s>best[0]:
             best=(s,p,m)
    return best


def leverage_sim(trades, leverage, margin_fraction=0.20):
    exposure=leverage*margin_fraction
    liq_threshold=max(0.005,1.0/leverage-0.005)
    eq=1.
    peak=1.
    maxdd=0.
    liq=0
    rets=[]
    for t in trades:
        before=eq
        if -float(t["mae"])>=liq_threshold:
            r=-margin_fraction
            liq+=1
            worst=-margin_fraction
        else:
            r=exposure*float(t["net"])
            worst=exposure*(float(t["mae"])-RT_COST)
        worst_eq=before*max(1e-9,1+worst)
        peak=max(peak,before)
        maxdd=max(maxdd,1-worst_eq/peak)
        eq*=max(1e-9,1+r)
        peak=max(peak,eq)
        maxdd=max(maxdd,1-eq/peak)
        rets.append(r)
    return {
        "leverage":leverage,
        "margin_fraction":margin_fraction,
        "exposure_x_equity":exposure,
        "ending_equity_multiple":eq,
        "return":eq-1,
        "max_drawdown":maxdd,
        "approx_liquidations":liq,
        "mean_account_trade_return":statistics.fmean(rets) if rets else None,
    }


def enrich_trades(df,trades,period):
    out=[]
    for t in trades:
        a=df.iloc[int(t["entry_i"])]
        b=df.iloc[int(t["exit_i"])]
        z=dict(t)
        z.update(
            period=period,
            entry_ts_ms=int(a.ts_ms),
            exit_ts_ms=int(b.ts_ms),
            side_name="LONG" if t["side"]>0 else "SHORT",
            mfe_capture=(t["gross"]/t["mfe"] if t["mfe"]>1e-9 else None),
            mfe_giveback=max(0,t["mfe"]-t["gross"]),
        )
        out.append(z)
    return out


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--master-root",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)

    blocks=make_dataset(args.master_root)
    dev=blocks["DEV_JUL12_AUG07"]
    model=train_bundle([dev])
    preds={name:model.predict(x) for name,(df,x,y) in blocks.items()}

    _,params,valm=tune(blocks["VAL_AUG08_SEP01"][0],preds["VAL_AUG08_SEP01"])

    frozen={}
    all_trades=[]
    for name,(df,x,y) in blocks.items():
        m=simulate(df,preds[name],params,record=True)
        frozen[name]={k:v for k,v in m.items() if k!="trades_rows"}
        all_trades += enrich_trades(df,m["trades_rows"],name)

    walk={}
    train_parts=[blocks["DEV_JUL12_AUG07"],blocks["VAL_AUG08_SEP01"]]
    for name in ("TEST_SEP01_OCT01","HOLDOUT_OCT04_NOV03"):
        b=train_bundle(train_parts)
        df,x,y=blocks[name]
        pp=b.predict(x)
        m=simulate(df,pp,params,record=True)
        walk[name]={k:v for k,v in m.items() if k!="trades_rows"}
        train_parts.append(blocks[name])

    test_trades=[t for t in all_trades if t["period"] in ("TEST_SEP01_OCT01","HOLDOUT_OCT04_NOV03")]
    leverage=[leverage_sim(test_trades,l) for l in (1,5,10,25)]
    imp=sorted(zip(model.feature_names,model.model.feature_importances_),key=lambda z:z[1],reverse=True)[:40]

    report={
      "version":"HYPE-MOVEMENT-SIGNATURE-COMMON-CAUSAL-V1",
      "research_only":True,
      "real_orders":False,
      "data":"compact_1m Jul12-Nov03; no Local labels used",
      "feature_count":len(model.feature_names),
      "horizons_minutes":list(HORIZONS),
      "round_trip_cost":RT_COST,
      "adverse_penalty":ADVERSE_PENALTY,
      "tuned_only_on":"VAL_AUG08_SEP01",
      "params":params.__dict__,
      "validation_objective":objective(valm),
      "frozen_model_transfer":frozen,
      "walk_forward":walk,
      "test_plus_holdout_leverage_scenarios":leverage,
      "top_feature_importance":[{"feature":a,"importance":float(b)} for a,b in imp],
      "warning":"25x calculation is an isolated-margin approximation; it is not a liquidation-engine replica and does not include funding/slippage beyond the round-trip cost floor."
    }
    (args.out/"MOVEMENT_REPLAY_REPORT.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    pd.DataFrame(all_trades).to_csv(args.out/"MOVEMENT_REPLAY_TRADES.csv",index=False)

    lines=[
      "# HYPE Movement Signature — common-causal chronological replay",
      "",
      "No Local labels were used as predictors or entry gates.",
      "Frozen parameters were tuned on Aug08-Sep01 only: "+json.dumps(params.__dict__),
      "",
      "## Frozen-model transfer",
    ]
    for name,m in frozen.items():
      lines.append(
        f"- {name}: return {m['total_return']:.2%}, maxDD {m['max_drawdown']:.2%}, "
        f"trades {m['trades']}, trades/day {m['trades_per_day']:.2f}, win {m['win_rate']:.2%}, "
        f"PF {m['profit_factor']:.2f}, median MFE capture {m['median_mfe_capture']:.2%}, "
        f"median giveback {m['median_mfe_giveback']:.2%}."
      )
    lines += ["","## Test+holdout leverage overlay"]
    for z in leverage:
      lines.append(
        f"- {z['leverage']}x leverage / 20% margin: equity x{z['ending_equity_multiple']:.3f}, "
        f"maxDD {z['max_drawdown']:.2%}, approx liquidation events {z['approx_liquidations']}."
      )
    lines += [
      "",
      "## Statistical status",
      "This is a research replay. Thresholds were tuned only on the validation block, but model/feature design remains researcher-selected. Forward full-116 shadow validation is required before any production claim."
    ]
    (args.out/"MOVEMENT_REPLAY_REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__=="__main__":
    main()
