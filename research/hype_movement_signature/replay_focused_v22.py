#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math
from pathlib import Path
import pandas as pd

from research.hype_movement_signature import replay_strength_v3_microgrid as v3

PERIODS=v3.PERIODS

PRESETS=[
 ("V2_EQUIV", v3.P(.0015,.0005,-9.0,.0015,.25,.050,2,1,1)),
 ("S15_TIGHT",v3.P(.0012,.00035,.15,.0010,.20,.0060,2,1,2)),
 ("S30_TIGHT",v3.P(.0012,.00035,.30,.0010,.20,.0060,2,1,2)),
 ("S45_TIGHT",v3.P(.0012,.00035,.45,.0010,.20,.0060,2,1,2)),
 ("S15_FAST",v3.P(.0008,.00025,.15,.0010,.20,.0060,2,1,2)),
 ("S30_FAST",v3.P(.0008,.00025,.30,.0010,.20,.0060,2,1,2)),
 ("S45_FAST",v3.P(.0008,.00025,.45,.0010,.20,.0060,2,1,2)),
 ("S30_TRAIL15",v3.P(.0010,.00030,.30,.0010,.15,.0060,2,1,2)),
 ("S30_TRAIL30",v3.P(.0010,.00030,.30,.0015,.30,.0075,2,1,2)),
 ("S45_TRAIL15",v3.P(.0010,.00030,.45,.0010,.15,.0060,2,1,2)),
 ("S45_CONFIRM2",v3.P(.0010,.00030,.45,.0010,.20,.0060,2,2,2)),
 ("S30_CONFIRM2",v3.P(.0010,.00030,.30,.0010,.20,.0060,2,2,2)),
 ("S20_MID",v3.P(.0015,.00050,.20,.0010,.20,.0060,2,1,2)),
 ("S35_MID",v3.P(.0015,.00050,.35,.0010,.20,.0060,2,1,2)),
 ("S50_MID",v3.P(.0015,.00050,.50,.0010,.20,.0060,2,1,2)),
]

def load_block(root,rel):
    d=v3.load(root/rel); x=v3.features(d); y=v3.targets(d,x); return d,x,y

def metric_core(m):
    return {k:v for k,v in m.items() if k!="trades_rows"}

def objective(m):
    if m["trades"]<8 or m["equity"]<=1.0 or m["profit_factor"]<=1.10:return -1e9
    return (
      math.log(m["equity"])
      -2.75*m["max_drawdown"]
      +0.12*max(-1,min(1,m["median_mfe_capture"]))
      +0.025*min(1,m["trades_per_day"]/1.5)
    )

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--master-root",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)

    blocks={n:load_block(a.master_root,rel) for n,rel in PERIODS}
    model=v3.train([blocks["TRAIN_JUL12_AUG07"],blocks["TRAIN_AUG08_SEP01"]])
    preds={n:model.predict(x) for n,(d,x,y) in blocks.items()}

    vd,vx,vy=blocks["VALIDATE_SEP01_OCT01"]
    scored=[]
    for name,p in PRESETS:
        m=v3.simulate(vd,vx,preds["VALIDATE_SEP01_OCT01"],vy,p,False)
        scored.append((objective(m),name,p,m))
    scored.sort(key=lambda z:z[0],reverse=True)
    best=scored[0]
    _,best_name,best_p,best_val=best

    rows=[]
    for score,name,p,m in scored:
        rows.append({"preset":name,"score":score,**p.__dict__,**metric_core(m)})
    pd.DataFrame(rows).to_csv(a.out/"FOCUSED_VALIDATION_PRESETS.csv",index=False)

    metrics={}
    alltr=[]
    for n,(d,x,y) in blocks.items():
        m=v3.simulate(d,x,preds[n],y,best_p,True)
        metrics[n]=metric_core(m)
        alltr += v3.enrich(d,m["trades_rows"],n)

    hd,hx,hy=blocks["HOLDOUT_OCT04_NOV03"]
    hm=v3.simulate(hd,hx,preds["HOLDOUT_OCT04_NOV03"],hy,best_p,True)
    htr=v3.enrich(hd,hm["trades_rows"],"HOLDOUT_OCT04_NOV03")
    lev=[v3.leverage(htr,L) for L in (1,5,10,25)]
    daily={str(L):v3.daily_stats(hd,hm["trades_rows"],exposure=L*.20) for L in (1,5,10,25)}

    rep={
      "version":"HYPE-MOVEMENT-STRENGTH-FOCUSED-V2.2",
      "research_only":True,"real_orders":False,
      "selection":"15 predeclared movement-strength presets; select only on Sep01-Oct01 validation",
      "train":["Jul12-Aug07","Aug08-Sep01"],
      "validation":"Sep01-Oct01",
      "oct04_nov03_status":"diagnostic_after_prior_V2_inspection_not_pristine",
      "winner":best_name,
      "params":best_p.__dict__,
      "validation_metrics":metric_core(best_val),
      "period_metrics":metrics,
      "oct_diagnostic_leverage":lev,
      "oct_diagnostic_daily":daily,
      "all_validation_presets":rows,
      "warning":"Research only. 25x figures are exposure approximations and do not prove future returns."
    }
    (a.out/"FOCUSED_MOVEMENT_REPORT.json").write_text(json.dumps(rep,indent=2)+"\n")
    pd.DataFrame(alltr).to_csv(a.out/"FOCUSED_MOVEMENT_TRADES.csv",index=False)
    print(json.dumps(rep,indent=2))

if __name__=="__main__":main()
