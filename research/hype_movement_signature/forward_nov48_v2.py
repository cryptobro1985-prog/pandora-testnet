#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
import pandas as pd
import numpy as np

from research.hype_movement_signature import replay_normalized_v2 as v2

FROZEN_PARAMS=v2.P(entry=0.0015,edge=0.0005,gba=0.0015,gbf=0.25,min_hold=2,confirm=1)
HIGH_TS=1794144000000
HIGH_PRICE=78.133
LOW_TS=1794211320000
LOW_PRICE=72.391
ORACLE_DROP=(HIGH_PRICE/LOW_PRICE-1.0)


def load_block(path:Path):
    d=v2.load(path); x=v2.features(d); y=v2.targets(d,x); return d,x,y


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--master-root",type=Path,required=True)
    ap.add_argument("--recent-compact",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args(); a.out.mkdir(parents=True,exist_ok=True)

    p1=load_block(a.master_root/"01_JUL12_AUG07_FULL_MICRO/compact_1m.jsonl.gz")
    p2=load_block(a.master_root/"02_AUG08_SEP01/compact_1m.jsonl.gz")
    recent=load_block(a.recent_compact)

    # Exact V2 historical training scope. No Nov data enters fit/tuning.
    model=v2.train([p1,p2])
    d,x,y=recent
    pred=model.predict(x)
    m=v2.simulate(d,pred,y,FROZEN_PARAMS,True)
    trades=v2.enrich(d,m["trades_rows"],"NOV08_NOV10_FROZEN_FORWARD")

    # Attach prices and overlap/control-leg diagnostics.
    rows=[]
    for z in trades:
        q=dict(z)
        ei=int(z["entry_i"]); xi=int(z["exit_i"])
        q["entry_price"]=float(d.iloc[ei].close)
        q["exit_price"]=float(d.iloc[xi].close)
        q["entry_iso"]=pd.to_datetime(int(q["entry_ts_ms"]),unit="ms",utc=True).isoformat()
        q["exit_iso"]=pd.to_datetime(int(q["exit_ts_ms"]),unit="ms",utc=True).isoformat()
        q["inside_78_133_to_72_391_leg"]=bool(
            q["side"]<0 and int(q["entry_ts_ms"])>=HIGH_TS and int(q["entry_ts_ms"])<LOW_TS
        )
        rows.append(q)
    tdf=pd.DataFrame(rows)

    leg=tdf[tdf["inside_78_133_to_72_391_leg"]==True].copy() if len(tdf) else pd.DataFrame()
    leg_compound=float(np.prod(1.0+leg["net"].to_numpy())-1.0) if len(leg) else 0.0
    leg_gross_sum=float(leg["gross"].sum()) if len(leg) else 0.0
    first_short=None
    if len(leg):
        z=leg.sort_values("entry_ts_ms").iloc[0]
        first_short={
            "entry_ts_ms":int(z.entry_ts_ms),
            "entry_iso":z.entry_iso,
            "entry_price":float(z.entry_price),
            "distance_below_high_pct":float((HIGH_PRICE/float(z.entry_price)-1)*100),
            "exit_ts_ms":int(z.exit_ts_ms),
            "exit_iso":z.exit_iso,
            "exit_price":float(z.exit_price),
            "gross_return_pct":float(z.gross*100),
            "net_return_pct":float(z.net*100),
            "mfe_pct":float(z.mfe*100),
            "mae_pct":float(z.mae*100),
            "mfe_giveback_pct":float(max(0,z.mfe-z.gross)*100),
            "reason":str(z.reason),
        }

    lev=[v2.leverage(rows,L) for L in (1,5,10,25)]
    daily={str(L):v2.daily_stats(d,m["trades_rows"],exposure=L*.20) for L in (1,5,10,25)}
    mm={k:v for k,v in m.items() if k!="trades_rows"}

    report={
        "version":"HYPE-MOVEMENT-V2-FROZEN-NOV08-NOV10",
        "research_only":True,
        "real_orders":False,
        "anti_leakage":{
            "model_train":["2026-07-12..2026-08-07","2026-08-08..2026-09-01"],
            "policy_params":"frozen from MOVEMENT_V2_REPORT before Nov8-10",
            "nov_retrained":False,
            "nov_threshold_retuned":False,
            "teacher_local_used_for_decision":False,
        },
        "window":[
            pd.to_datetime(int(d.ts_ms.iloc[0]),unit="ms",utc=True).isoformat(),
            pd.to_datetime(int(d.ts_ms.iloc[-1]),unit="ms",utc=True).isoformat(),
        ],
        "frozen_params":FROZEN_PARAMS.__dict__,
        "metrics":mm,
        "leverage_approx":lev,
        "daily_exit_day_stats":daily,
        "control_leg":{
            "high_ts_ms":HIGH_TS,"high_price":HIGH_PRICE,
            "low_ts_ms":LOW_TS,"low_price":LOW_PRICE,
            "oracle_drop_pct":ORACLE_DROP*100,
            "short_trades_started_inside_leg":int(len(leg)),
            "compound_net_underlying_return_pct":leg_compound*100,
            "sum_gross_underlying_return_pct":leg_gross_sum*100,
            "first_short":first_short,
        },
        "warning":"Frozen forward-like replay on preserved Nov8-10 data. 25x is only an exposure/liquidation approximation, not exact Bybit margin-tier math."
    }
    (a.out/"MOVEMENT_V2_NOV48_REPORT.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    tdf.to_csv(a.out/"MOVEMENT_V2_NOV48_TRADES.csv",index=False)
    print(json.dumps(report,indent=2))

if __name__=="__main__": main()
