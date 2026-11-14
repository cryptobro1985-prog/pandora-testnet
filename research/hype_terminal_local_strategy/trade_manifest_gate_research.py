"""Research-only gate for matched HYPE post-local execution rows. No orders.
Run: python research/hype_terminal_local_strategy/trade_manifest_gate_research.py
Input optional: python .../trade_manifest_gate_research.py manifest.json
Never treats a backtest price or public trade print as an executable fill.
"""
import json,sys
from datetime import datetime,timezone

REQUIRED=("trade_id","side","local_type","local_ts_ms","signal_available_ts_ms",
          "order_submit_ts_ms","entry_fill_ts_ms","entry_fill_price",
          "entry_fill_source","entry_notional","stop_price","stop_trigger_ts_ms",
          "stop_fill_ts_ms","stop_fill_price","stop_fill_source","exit_ts_ms",
          "exit_fill_price","exit_fill_source","fees_paid","funding_paid",
          "mark_path_source","l50_path_source","public_trades_source",
          "event_sequence_source","coverage_complete")
def gate(row):
    missing=[k for k in REQUIRED if k not in row or row[k] is None]
    if missing:return {"status":"UNVERIFIED_MISSING_FIELDS","missing":missing}
    side=row["side"]
    if (side,row["local_type"]) not in (("LONG","LOW"),("SHORT","HIGH")):
        return {"status":"REJECT_SIDE_LOCAL_MISMATCH"}
    t=[row[k] for k in ("local_ts_ms","signal_available_ts_ms","order_submit_ts_ms","entry_fill_ts_ms","exit_ts_ms")]
    if not all(isinstance(x,int) for x in t) or not all(a<=b for a,b in zip(t,t[1:])):
        return {"status":"REJECT_CAUSAL_TIME"}
    if row["stop_trigger_ts_ms"] is not None and row["stop_fill_ts_ms"] is not None:
        if not (t[3] < row["stop_trigger_ts_ms"] <= row["stop_fill_ts_ms"] <= t[4]):
            return {"status":"REJECT_STOP_TIME"}
    if row["stop_trigger_ts_ms"] is None or row["stop_fill_ts_ms"] is None:
        return {"status":"UNVERIFIED_STOP_EXECUTION"}
    try:
        p=float(row["entry_fill_price"]); s=float(row["stop_price"])
        q=float(row["entry_notional"]); ep=float(row["exit_fill_price"])
        sf=float(row["stop_fill_price"])
        costs=float(row["fees_paid"])+float(row["funding_paid"])
    except (TypeError,ValueError):return {"status":"REJECT_NUMERIC"}
    if min(p,s,q,ep,sf)<=0 or (side=="LONG" and s>=p) or (side=="SHORT" and s<=p):
        return {"status":"REJECT_PRICE_GEOMETRY"}
    if not row["coverage_complete"] or any(not row[k] for k in (
        "entry_fill_source","stop_fill_source","exit_fill_source","mark_path_source",
        "l50_path_source","public_trades_source","event_sequence_source")):
        return {"status":"UNVERIFIED_SOURCE_COVERAGE"}
    if row["entry_fill_ts_ms"]==row["stop_trigger_ts_ms"]:
        return {"status":"UNVERIFIED_SAME_TIMESTAMP"}
    # Cost-aware observed trade PnL only; mark-to-market DD and liquidation still require replay.
    signed=(ep/p-1)*(1 if side=="LONG" else -1)
    return {"status":"EXECUTION_FIELDS_COMPLETE_NOT_LIQUIDATION_VERIFIED",
            "observed_net_pnl_quote":round(q*signed-costs,10),
            "stop_gap_fraction":round((s-sf)/s if side=="LONG" else (sf-s)/s,10)}
def self_test():
    base=dict(trade_id="T1",side="LONG",local_type="LOW",local_ts_ms=10,
       signal_available_ts_ms=20,order_submit_ts_ms=21,entry_fill_ts_ms=22,
       entry_fill_price=100,entry_fill_source="fill-log",entry_notional=100,
       stop_price=99,stop_trigger_ts_ms=30,stop_fill_ts_ms=31,
       stop_fill_price=98.8,stop_fill_source="fill-log",exit_ts_ms=31,
       exit_fill_price=98.8,exit_fill_source="fill-log",fees_paid=.15,
       funding_paid=0,mark_path_source="mark",l50_path_source="l50",
       public_trades_source="tape",event_sequence_source="seq",coverage_complete=True)
    assert gate(base)["status"]=="EXECUTION_FIELDS_COMPLETE_NOT_LIQUIDATION_VERIFIED"
    assert abs(gate(base)["observed_net_pnl_quote"]+1.35)<1e-8
    assert gate({**base,"side":"SHORT","local_type":"HIGH","stop_price":101,
                 "stop_fill_price":101.2,"exit_fill_price":101.2})["status"]=="EXECUTION_FIELDS_COMPLETE_NOT_LIQUIDATION_VERIFIED"
    assert gate({**base,"side":"SHORT"})["status"]=="REJECT_SIDE_LOCAL_MISMATCH"
    assert gate({**base,"signal_available_ts_ms":25})["status"]=="REJECT_CAUSAL_TIME"
    assert gate({**base,"stop_trigger_ts_ms":22})["status"]=="REJECT_STOP_TIME"
    assert gate({**base,"coverage_complete":False})["status"]=="UNVERIFIED_SOURCE_COVERAGE"
    assert gate({**base,"entry_fill_source":""})["status"]=="UNVERIFIED_SOURCE_COVERAGE"
    assert gate({**base,"stop_fill_ts_ms":None})["status"]=="UNVERIFIED_STOP_EXECUTION"
    assert gate({**base,"fees_paid":None})["status"]=="UNVERIFIED_MISSING_FIELDS"
    assert gate({**base,"stop_price":101})["status"]=="REJECT_PRICE_GEOMETRY"
    return 10
if __name__=="__main__":
    print("synthetic tests:",self_test())
    if len(sys.argv)>1:
        with open(sys.argv[1],encoding="utf-8") as f: rows=json.load(f)
        if not isinstance(rows,list):raise ValueError("manifest must be a JSON list")
        results=[dict(trade_id=r.get("trade_id"),**gate(r)) for r in rows]
        print(json.dumps(results,ensure_ascii=False,indent=2))
