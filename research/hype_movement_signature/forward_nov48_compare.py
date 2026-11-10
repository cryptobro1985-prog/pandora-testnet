#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, importlib
from pathlib import Path
import numpy as np
import pandas as pd

HIGH_TS=1794144000000
HIGH_PRICE=78.133
LOW_TS=1794211320000
LOW_PRICE=72.391
ORACLE_SHORT_RETURN=1.0-LOW_PRICE/HIGH_PRICE

SPECS=[
    {
      "name":"V2",
      "module":"research.hype_movement_signature.replay_normalized_v2",
      "report":"research/hype_movement_signature/results_v2/MOVEMENT_V2_REPORT.json",
      "needs_x":False,
    },
    {
      "name":"V3_MICROGRID",
      "module":"research.hype_movement_signature.replay_strength_v3_microgrid",
      "report":"research/hype_movement_signature/results_v3_microgrid/MOVEMENT_V2_REPORT.json",
      "needs_x":True,
    },
    {
      "name":"V4_PATH_AWARE",
      "module":"research.hype_movement_signature.replay_path_aware_v4",
      "report":"research/hype_movement_signature/results_v4/MOVEMENT_V2_REPORT.json",
      "needs_x":True,
    },
]

def build_block(mod,path):
    d=mod.load(path); x=mod.features(d); y=mod.targets(d,x)
    return d,x,y

def enrich_extra(d, rows, period):
    out=[]
    for z in rows:
        q=dict(z)
        ei=int(q["entry_i"]); xi=int(q["exit_i"])
        q["period"]=period
        q["entry_ts_ms"]=int(d.iloc[ei].ts_ms)
        q["exit_ts_ms"]=int(d.iloc[xi].ts_ms)
        q["entry_iso"]=pd.to_datetime(q["entry_ts_ms"],unit="ms",utc=True).isoformat()
        q["exit_iso"]=pd.to_datetime(q["exit_ts_ms"],unit="ms",utc=True).isoformat()
        q["entry_price"]=float(d.iloc[ei].close)
        q["exit_price"]=float(d.iloc[xi].close)
        q["side_name"]="LONG" if int(q["side"])>0 else "SHORT"
        q["mfe_giveback"]=max(0.0,float(q["mfe"])-float(q["gross"]))
        q["mfe_capture"]=(float(q["gross"])/float(q["mfe"]) if float(q["mfe"])>1e-9 else None)
        q["inside_control_short_leg"]=bool(
            int(q["side"])<0 and q["entry_ts_ms"]>=HIGH_TS and q["entry_ts_ms"]<LOW_TS
        )
        out.append(q)
    return out

def score_one(spec,master_root,recent_path,repo_root):
    rp=repo_root/spec["report"]
    if not rp.exists():
        return {"name":spec["name"],"available":False,"reason":"historical_result_missing"},[]
    rep=json.loads(rp.read_text())
    mod=importlib.import_module(spec["module"])
    p1=build_block(mod,master_root/"01_JUL12_AUG07_FULL_MICRO/compact_1m.jsonl.gz")
    p2=build_block(mod,master_root/"02_AUG08_SEP01/compact_1m.jsonl.gz")
    recent=build_block(mod,recent_path)
    model=mod.train([p1,p2])
    d,x,y=recent
    pred=model.predict(x)
    params=mod.P(**rep["params"])
    if spec["needs_x"]:
        m=mod.simulate(d,x,pred,y,params,True)
    else:
        m=mod.simulate(d,pred,y,params,True)
    rows=enrich_extra(d,m["trades_rows"],"NOV08_NOV10_FORWARD")
    leg=[z for z in rows if z["inside_control_short_leg"]]
    leg_sorted=sorted(leg,key=lambda z:z["entry_ts_ms"])
    first=leg_sorted[0] if leg_sorted else None
    compound=float(np.prod([1.0+float(z["net"]) for z in leg])-1.0) if leg else 0.0
    lev=[mod.leverage(rows,L) for L in (1,5,10,25)]
    core={k:v for k,v in m.items() if k!="trades_rows"}
    return {
       "name":spec["name"],
       "available":True,
       "historical_version":rep.get("version"),
       "params":rep["params"],
       "metrics":core,
       "leverage_approx":lev,
       "control_leg":{
          "oracle_short_return_pct":ORACLE_SHORT_RETURN*100,
          "short_trades":len(leg),
          "compound_net_underlying_pct":compound*100,
          "first_short":None if first is None else {
              "entry_iso":first["entry_iso"],
              "entry_price":first["entry_price"],
              "distance_below_high_pct":(1.0-first["entry_price"]/HIGH_PRICE)*100,
              "exit_iso":first["exit_iso"],
              "exit_price":first["exit_price"],
              "net_pct":float(first["net"])*100,
              "mfe_pct":float(first["mfe"])*100,
              "mae_pct":float(first["mae"])*100,
              "giveback_pct":float(first["mfe_giveback"])*100,
              "reason":first["reason"],
          }
       }
    },rows

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--master-root",type=Path,required=True)
    ap.add_argument("--recent-compact",type=Path,required=True)
    ap.add_argument("--repo-root",type=Path,default=Path("."))
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    results=[];allrows=[]
    for spec in SPECS:
        z,rows=score_one(spec,a.master_root,a.recent_compact,a.repo_root)
        results.append(z)
        for r in rows:r["strategy"]=spec["name"]
        allrows+=rows
    report={
       "version":"HYPE-MOVEMENT-NOV8-10-FROZEN-COMPARATOR-V1",
       "research_only":True,
       "real_orders":False,
       "window":["2026-11-08T00:00:00+00:00","2026-11-10T00:00:00+00:00"],
       "anti_leakage":"No Nov data used to fit models or choose frozen historical parameters. Missing strategies are skipped until their historical result exists.",
       "control_leg":{"high":HIGH_PRICE,"low":LOW_PRICE,"short_return_pct":ORACLE_SHORT_RETURN*100},
       "strategies":results,
       "warning":"Historical/forward-like research only; leverage numbers are approximations, not exact Bybit liquidation-tier accounting."
    }
    (a.out/"MOVEMENT_NOV48_COMPARATOR.json").write_text(json.dumps(report,indent=2)+"\n")
    pd.DataFrame(allrows).to_csv(a.out/"MOVEMENT_NOV48_COMPARATOR_TRADES.csv",index=False)
    print(json.dumps(report,indent=2))

if __name__=="__main__":main()
