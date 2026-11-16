"""Fail-closed per-trade event coverage gate for frozen post-H1-local entries.
Research only; input JSON episodes with timestamps in UTC milliseconds.
Never treats OHLC, missing mark, or unverified stop fill as a real execution.
Usage: python trade_event_coverage_gate_20261116.py episodes.json
"""
import json, sys
from collections import Counter

STREAMS=("public_trades","mark_price","orderbook_l50")
OPTIONAL=("oi","liquidations","cvd")
def audit(e):
    ident=e.get("id","UNKNOWN")
    side=e.get("side")
    if side not in ("LONG","SHORT"): return {"id":ident,"status":"INVALID_SIDE"}
    try:
        local=int(e["local_extreme_ts_ms"])
        confirmed=int(e["local_confirmed_ts_ms"])
        entry=int(e["entry_ts_ms"])
        exit_=int(e["exit_ts_ms"])
    except (KeyError,ValueError,TypeError):
        return {"id":ident,"status":"MISSING_TIMESTAMPS"}
    if not (local<=confirmed<=entry<exit_):
        return {"id":ident,"status":"CAUSALITY_VIOLATION"}
    if e.get("entry_rule")!="FROZEN_D250":
        return {"id":ident,"status":"ENTRY_RULE_NOT_FROZEN"}
    if entry<local+250*60_000:
        return {"id":ident,"status":"BEFORE_D250"}
    if e.get("same_side_extreme_before_entry") is not False:
        return {"id":ident,"status":"LOCAL_INVALIDATION_UNKNOWN"}
    if e.get("opposite_local_confirmed_before_entry") is not False:
        return {"id":ident,"status":"OPPOSITE_ALREADY_CONFIRMED_OR_UNKNOWN"}
    streams=e.get("streams",{})
    missing=[]; gaps={}; stale={}
    for name in STREAMS:
        s=streams.get(name)
        if not isinstance(s,dict) or not isinstance(s.get("timestamps_ms"),list):
            missing.append(name); continue
        ts=s["timestamps_ms"]
        if not ts or any(not isinstance(t,int) for t in ts) or ts!=sorted(set(ts)):
            missing.append(name); continue
        if ts[0]>entry or ts[-1]<exit_:
            missing.append(name); continue
        max_gap=s.get("max_permitted_gap_ms")
        if not isinstance(max_gap,int) or max_gap<=0:
            missing.append(name); continue
        worst=max((b-a for a,b in zip(ts,ts[1:]) if b>entry and a<exit_),default=0)
        if worst>max_gap: gaps[name]=worst
        if name=="orderbook_l50" and s.get("valid_book_checks") is not True:
            stale[name]="NO_VALID_BOOK_PROOF"
    if missing or gaps or stale:
        return {"id":ident,"status":"UNKNOWN_EVENT_COVERAGE","missing":missing,"gaps":gaps,"invalid":stale}
    # Coverage is NOT a fill, fee, liquidation, or PnL verdict.
    return {"id":ident,"status":"COVERAGE_GATE_PASS_ONLY",
            "optional_missing":[n for n in OPTIONAL if n not in streams],
            "fill_verified":False,"liquidations":None,"net_pnl":None}
def self_test():
    x={"id":"synthetic","side":"LONG","local_extreme_ts_ms":0,
       "local_confirmed_ts_ms":60_000,"entry_ts_ms":15_000_000,
       "exit_ts_ms":15_120_000,"entry_rule":"FROZEN_D250",
       "same_side_extreme_before_entry":False,
       "opposite_local_confirmed_before_entry":False,
       "streams":{n:{"timestamps_ms":[15_000_000,15_060_000,15_120_000],
                     "max_permitted_gap_ms":60_000,
                     **({"valid_book_checks":True} if n=="orderbook_l50" else {})}
                  for n in STREAMS}}
    assert audit(x)["status"]=="COVERAGE_GATE_PASS_ONLY"
    y=json.loads(json.dumps(x)); y["streams"]["mark_price"]["timestamps_ms"]=[15_000_000,15_120_000]
    assert audit(y)["status"]=="UNKNOWN_EVENT_COVERAGE"
    y=json.loads(json.dumps(x)); y["entry_ts_ms"]=14_999_999
    assert audit(y)["status"]=="BEFORE_D250"
    y=json.loads(json.dumps(x)); y["local_confirmed_ts_ms"]=15_000_001
    assert audit(y)["status"]=="CAUSALITY_VIOLATION"
    y=json.loads(json.dumps(x)); del y["streams"]["orderbook_l50"]["valid_book_checks"]
    assert audit(y)["status"]=="UNKNOWN_EVENT_COVERAGE"
    print("PASS 5 synthetic coverage/causality tests; zero historical fills verified")
if __name__=="__main__":
    if len(sys.argv)==1: self_test()
    else:
        rows=[audit(x) for x in json.load(open(sys.argv[1],encoding="utf8"))]
        for row in rows: print(json.dumps(row,sort_keys=True))
        print(json.dumps({"summary":dict(Counter(x["status"] for x in rows))}))
