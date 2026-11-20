"""Research-only fail-closed promotion overlay for frozen D250 quote gate.
No detector changes, no orders, no assertions of actual Bybit fills.
"""
from dataclasses import replace
from research.hype_terminal_local_strategy.execution_event_integrity_gate_20261120 import validate, Quote, Trade

def audit(t, quotes):
    original=validate(t,quotes)
    failures=list(original.get("failures",[]))
    if isinstance(t.opposite_extreme_ts_ms,int) and t.opposite_extreme_ts_ms<=t.entry_fill_ts_ms:
        failures.append("OPPOSITE_EXTREME_PRE_ENTRY")
    if not quotes or any(not isinstance(q.source,str) or not q.source.startswith("bybit:") or q.source=="bybit:" for q in quotes):
        failures.append("UNVERIFIED_SOURCE")
    if original.get("observed_mark_liquidation_boundary_cross"):
        failures.append("MARK_LIQUIDATION_DANGER")
    if any(q.ts_ms<t.entry_fill_ts_ms or q.ts_ms>t.opposite_confirmed_ts_ms for q in quotes):
        failures.append("OUTSIDE_TRADE_WINDOW")
    return {"status":"BLOCKED" if failures else "QUOTE_PROVENANCE_ONLY",
            "failures":sorted(set(failures)),
            "fill_verified":False, "liquidation_verified":False,
            "notional_cap":original.get("notional_cap") if not failures else None}

def _tests():
    t=Trade("LONG",0,14_000_000,15_000_000,15_000_001,15_000_002,
            100,100,.005,.01,.0015,.02,90,14_500_000,15_120_000)
    q=[Quote(ts,100,100.1,100,2,2,"synthetic")
       for ts in range(15_000_002,15_120_001,60_000)]
    q.append(Quote(15_120_000,100,100.1,100,2,2,"synthetic"))
    assert "OPPOSITE_EXTREME_PRE_ENTRY" in audit(t,q)["failures"]
    assert "UNVERIFIED_SOURCE" in audit(t,q)["failures"]
    assert "MARK_LIQUIDATION_DANGER" in audit(t,[replace(x,mark=89) for x in q])["failures"]
    assert "OPPOSITE_EXTREME_PRE_ENTRY" in audit(replace(t,side="SHORT",liquidation_mark=110),q)["failures"]
    clean=replace(t,opposite_extreme_ts_ms=15_100_000)
    trusted=[replace(x,source="bybit:archive") for x in q]
    assert audit(clean,trusted)["status"]=="QUOTE_PROVENANCE_ONLY"
    assert audit(clean,trusted)["fill_verified"] is False
    print("Five synthetic gate assertions passed; zero historical fills verified")

if __name__=="__main__":
    _tests()
