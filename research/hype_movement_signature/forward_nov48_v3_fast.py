#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd

from research.hype_movement_signature import replay_strength_v3_fast as v3

HIGH_TS=1794144000000
HIGH_PRICE=78.133
LOW_TS=1794211320000
LOW_PRICE=72.391
DROP_SIMPLE=1.0-LOW_PRICE/HIGH_PRICE
SHORT_ORACLE=HIGH_PRICE/LOW_PRICE-1.0


def block(path:Path):
    d=v3.load(path); x=v3.features(d); y=v3.targets(d,x); return d,x,y


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--master-root",type=Path,required=True)
    ap.add_argument("--recent-compact",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)

    p1=block(a.master_root/"01_JUL12_AUG07_FULL_MICRO/compact_1m.jsonl.gz")
    p2=block(a.master_root/"02_AUG08_SEP01/compact_1m.jsonl.gz")
    val=block(a.master_root/"03_SEP01_OCT01/compact_1m.jsonl.gz")
    recent=block(a.recent_compact)

    model=v3.train([p1,p2])
    vp=model.predict(val[1])
    _,params,validation=v3.tune(val[0],val[1],vp,val[2])

    d,x,y=recent
    pred=model.predict(x)
    m=v3.simulate(d,x,pred,y,params,True)
    trades=v3.enrich(d,m["trades_rows"],"NOV08_NOV10_FORWARD")
    rows=[]
    for z in trades:
        q=dict(z);ei=int(z["entry_i"]);xi=int(z["exit_i"])
        q["entry_price"]=float(d.iloc[ei].close);q["exit_price"]=float(d.iloc[xi].close)
        q["entry_iso"]=pd.to_datetime(int(q["entry_ts_ms"]),unit="ms",utc=True).isoformat()
        q["exit_iso"]=pd.to_datetime(int(q["exit_ts_ms"]),unit="ms",utc=True).isoformat()
        q["inside_control_short_leg"]=bool(q["side"]<0 and HIGH_TS<=int(q["entry_ts_ms"])<LOW_TS)
        rows.append(q)
    t=pd.DataFrame(rows)
    leg=t[t["inside_control_short_leg"]==True].copy() if len(t) else pd.DataFrame()
    first=None
    if len(leg):
        z=leg.sort_values("entry_ts_ms").iloc[0]
        first={
          "entry_ts_ms":int(z.entry_ts_ms),"entry_iso":z.entry_iso,"entry_price":float(z.entry_price),
          "distance_from_high_pct":float((1-float(z.entry_price)/HIGH_PRICE)*100),
          "exit_ts_ms":int(z.exit_ts_ms),"exit_iso":z.exit_iso,"exit_price":float(z.exit_price),
          "gross_return_pct":float(z.gross*100),"net_return_pct":float(z.net*100),
          "mfe_pct":float(z.mfe*100),"mae_pct":float(z.mae*100),
          "mfe_giveback_pct":float(max(0,z.mfe-z.gross)*100),"reason":str(z.reason)
        }
    lev=[v3.leverage(rows,L) for L in (1,5,10,25)]
    report={
      "version":"HYPE-MOVEMENT-STRENGTH-V3-FAST-NOV08-NOV10",
      "research_only":True,"real_orders":False,
      "anti_leakage":{
        "model_train":["Jul12-Aug07","Aug08-Sep01"],
        "policy_selection":"Sep01-Oct01 only",
        "nov_retrained":False,"nov_retuned":False,"local_teacher_predictor":False
      },
      "params":params.__dict__,
      "validation":{k:v for k,v in validation.items() if k!="trades_rows"},
      "nov_metrics":{k:v for k,v in m.items() if k!="trades_rows"},
      "leverage_approx":lev,
      "control_leg":{
        "high":HIGH_PRICE,"low":LOW_PRICE,
        "simple_price_drop_pct":DROP_SIMPLE*100,
        "short_oracle_return_pct":SHORT_ORACLE*100,
        "short_trades_started_inside_leg":int(len(leg)),
        "compound_net_underlying_pct":float((np.prod(1+leg.net.to_numpy())-1)*100) if len(leg) else 0.0,
        "first_short":first
      },
      "warning":"Nov8-10 is not used for fit or threshold selection. 25x remains an approximate exposure stress, not exact Bybit liquidation-tier simulation."
    }
    (a.out/"MOVEMENT_V3_FAST_NOV48_REPORT.json").write_text(json.dumps(report,indent=2)+"\n")
    t.to_csv(a.out/"MOVEMENT_V3_FAST_NOV48_TRADES.csv",index=False)
    print(json.dumps(report,indent=2))

if __name__=="__main__":main()
