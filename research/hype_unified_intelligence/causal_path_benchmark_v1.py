#!/usr/bin/env python3
"""HYPE causal price-vs-flow research benchmark (no real orders).

Reproduce the historical diagnostic using the saved HYPE master ZIP.
Future candles are used for LABELS only; predictors use completed minute bars.
Absolute PnL cannot be inferred from first-barrier event classification.
"""
import argparse,gzip,io,json,hashlib,zipfile
from pathlib import Path
import numpy as np
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression

PERIODS={"train":"01_JUL12_AUG07_FULL_MICRO","dev":"02_AUG08_SEP01",
         "validation":"03_SEP01_OCT01","holdout":"04_OCT04_NOV03"}
HORIZON=60
STEP=5
RETURN_BPS=50.0
ADVERSE_BPS=35.0
TRAIN_FEATURES=["ret5","ret15","ret60","ret360","ret480",
                "vol60","vol15","atr14","eff15","eff60"]
FLOW_FEATURES=["flow5","flow15","flow60","volatility_flow_15",
               "flow_price5","flow_price15","flow_price60",
               "trade_intensity15","turnover60"]

def load_period(z,folder):
    with gzip.open(io.BytesIO(z.read(f"{folder}/compact_1m.jsonl.gz")),"rt") as f:
        rows=[json.loads(line) for line in f if line.strip()]
    return sorted(rows,key=lambda r:int(r["bar_end_ms"]))

def rolling_sum(x,n):
    cs=np.r_[0.0,np.cumsum(x,dtype=float)]
    out=np.full(len(x),np.nan)
    out[n-1:]=cs[n:]-cs[:-n]
    return out

def materialize(rows):
    n=len(rows)
    end=np.array([int(r["bar_end_ms"]) for r in rows],dtype=np.int64)
    close=np.array([float(r["close"]) for r in rows])
    high=np.array([float(r["high"]) for r in rows])
    low=np.array([float(r["low"]) for r in rows])
    buy=np.array([float(r.get("buy_notional") or 0.0) for r in rows])
    sell=np.array([float(r.get("sell_notional") or 0.0) for r in rows])
    count=np.array([float(r.get("trade_count") or 0.0) for r in rows])
    gap=np.array([bool(r.get("gap",False)) for r in rows])
    valid=(close>0)&(high>=close)&(low<=close)&(low>0)
    diff=np.diff(end,prepend=end[0]-60000)
    bad=(diff!=60000)|gap|(~valid)
    segment=np.cumsum(bad)
    ret1=np.r_[0.0,np.diff(np.log(np.maximum(close,1e-12)))]
    v={}
    for m in (5,15,60,360,480):
        v[f"ret{m}"]=np.r_[np.full(m,np.nan),close[m:]/close[:-m]-1.0]
    for m in (15,60):
        v[f"vol{m}"]=np.sqrt(np.maximum(rolling_sum(ret1**2,m),0.0))
        den=rolling_sum(np.abs(ret1),m)
        v[f"eff{m}"]=np.where(den>1e-12,np.abs(v[f"ret{m}"])/den,0.0)
    tr=(high-low)/np.maximum(close,1e-12)
    v["atr14"]=rolling_sum(tr,14)/14
    for m in (5,15,60):
        bs=rolling_sum(buy,m);ss=rolling_sum(sell,m)
        v[f"flow{m}"]=np.where(bs+ss>0,(bs-ss)/(bs+ss),0.0)
        v[f"flow_price{m}"]=v[f"flow{m}"]*v[f"ret{m}"]
    v["volatility_flow_15"]=np.abs(v["flow5"]-v["flow15"])
    v["trade_intensity15"]=np.log1p(rolling_sum(count,15))
    v["turnover60"]=np.log1p(rolling_sum(buy+sell,60))
    X=np.column_stack([v[k] for k in TRAIN_FEATURES+FLOW_FEATURES])
    ix=np.arange(480,n-HORIZON,STEP)
    # Historical quality gate applies to BOTH lookback and future targets.
    ix=ix[(segment[ix]==segment[ix-480])&(segment[ix]==segment[ix+HORIZON])]
    ix=ix[np.isfinite(X[ix]).all(axis=1)]
    outX=X[ix]
    labels=np.zeros((len(ix),2),dtype=np.int8)
    mfs=np.zeros((len(ix),2));mas=np.zeros((len(ix),2))
    for j,i in enumerate(ix):
        up=(high[i+1:i+HORIZON+1]/close[i]-1.0)*10000
        down=(1.0-low[i+1:i+HORIZON+1]/close[i])*10000
        mfs[j]=[max(0.0,float(up.max())),max(0.0,float(down.max()))]
        mas[j]=[max(0.0,float(down.max())),max(0.0,float(up.max()))]
        def firsthit(good,bad):
            y=np.flatnonzero(good>=RETURN_BPS)
            z=np.flatnonzero(bad>=ADVERSE_BPS)
            # If both hit in the same minute, mark NOT successful:
            # minute bars cannot prove favorable-first execution order.
            return bool(len(y) and (not len(z) or y[0]<z[0]))
        labels[j,0]=firsthit(up,down)
        labels[j,1]=firsthit(down,up)
    return {"X":outX,"y":labels,"mfe":mfs,"mae":mas,"t":end[ix],
            "raw_bars":n,"eligible_rows":len(ix),
            "invalid_or_gap_minutes":int(bad.sum())}

def pick_events(data,probs,threshold=.58,cooldown=30,diff=.08):
    events=[];last=-10**18
    for i,(t,p) in enumerate(zip(data["t"],probs)):
        if int(t)-last<cooldown*60000:continue
        side=int(np.argmax(p))
        if p[side]<threshold or p[side]-p[1-side]<diff:continue
        events.append((i,side));last=int(t)
    return events

def score(data,probs,threshold):
    events=pick_events(data,probs,threshold)
    if not events:
        return {"events":0,"precision":None,"long":0,"short":0,
                "median_mfe_bps":None,"median_mae_bps":None,
                "net_at_barrier_bps_proxy":None}
    ix=np.asarray([i for i,s in events])
    side=np.asarray([s for i,s in events])
    success=data["y"][ix,side]
    mfe=data["mfe"][ix,side];mae=data["mae"][ix,side]
    proxy=(success*RETURN_BPS+(1-success)*(-ADVERSE_BPS))-12.0
    return {"events":len(events),"correct":int(success.sum()),
            "precision":round(float(success.mean()),4),
            "long":int((side==0).sum()),"short":int((side==1).sum()),
            "long_precision":round(float(success[side==0].mean()),4) if (side==0).any() else None,
            "short_precision":round(float(success[side==1].mean()),4) if (side==1).any() else None,
            "median_mfe_bps":round(float(np.median(mfe)),2),
            "median_mae_bps":round(float(np.median(mae)),2),
            "net_at_barrier_bps_proxy":round(float(proxy.sum()),2),
            "warning":"Barrier proxy assumes exact price; NOT executable PnL"}

def run(master):
    with zipfile.ZipFile(master) as z:
        allp={key:materialize(load_period(z,folder)) for key,folder in PERIODS.items()}
    result={}
    for name,inds in (("price_only",list(range(len(TRAIN_FEATURES)))),
                      ("price_flow",list(range(len(TRAIN_FEATURES+FLOW_FEATURES))))):
        models=[]
        for side in (0,1):
            m=make_pipeline(StandardScaler(),
                            LogisticRegression(C=.2,max_iter=400,random_state=20261111))
            m.fit(allp["train"]["X"][:,inds],allp["train"]["y"][:,side])
            models.append(m)
        probs={k:np.column_stack([m.predict_proba(v["X"][:,inds])[:,1]
                                 for m in models]) for k,v in allp.items()}
        tested=[(score(allp["dev"],probs["dev"],float(th)),float(th))
                for th in (.40,.45,.50,.55,.60,.65,.70,.75,.80)]
        eligible=[(x,th) for x,th in tested if x["events"]>=12]
        if eligible:
            best=max(eligible,key=lambda z:(z[0]["net_at_barrier_bps_proxy"],z[0]["precision"]))
        else:
            best=(score(allp["dev"],probs["dev"],.60),.60)
        th=best[1]
        result[name]={
            "threshold_chosen_on_dev":th,
            "train":score(allp["train"],probs["train"],th),
            "dev":best[0],
            "validation":score(allp["validation"],probs["validation"],th),
            "holdout":score(allp["holdout"],probs["holdout"],th),
            "label_base_rates":{
                k:[round(float(d["y"][:,s].mean()),4) for s in (0,1)]
                for k,d in allp.items()
            }
        }
    return {
        "experiment":"HYPE_CAUSAL_PATH_BENCHMARK_V1",
        "data_sha256":hashlib.sha256(Path(master).read_bytes()).hexdigest(),
        "data_periods":{
            k:{q:int(v[q]) for q in ("raw_bars","eligible_rows","invalid_or_gap_minutes")}
            for k,v in allp.items()},
        "point_contract":{"total":116,"allowed_inputs":86,
                          "this_experiment_uses":"price and public trades only; no imputation"},
        "prediction_features":TRAIN_FEATURES+FLOW_FEATURES,
        "future_target":"Within 60m +50bps favorable before 35bps adverse",
        "execution":"Research event classifier; 30m event cooldown, 12bps barrier cost proxy only",
        "split_provenance":"Jul train / Aug dev / Sep validation / Oct historic inspected holdout",
        "results":result,"status":"diagnostic_only_no_live_promotion","real_orders":False
    }

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--master",required=True)
    parser.add_argument("--out",required=True)
    a=parser.parse_args()
    output=run(a.master)
    Path(a.out).write_text(json.dumps(output,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps(output["results"],ensure_ascii=False))
