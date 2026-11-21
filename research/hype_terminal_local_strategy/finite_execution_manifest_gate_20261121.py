"""Fail-closed finite-cost and chronology supplement for historical HYPE trade manifests.
Research only; never routes orders. Run: python finite_execution_manifest_gate_20261121.py
"""
import math
from datetime import datetime, timezone

NUMERIC = ("entry_vwap", "stop_price", "liquidation_price", "fee_entry",
           "fee_exit", "funding", "mark_min", "mark_max")
COUNTS = ("quote_event_count", "mark_event_count", "l50_event_count")
GAPS = ("max_quote_gap_ms", "max_mark_gap_ms", "max_l50_gap_ms")
TIMES = ("anchor_ts_ms", "confirmation_ts_ms", "entry_ts_ms", "exit_ts_ms")

def audit(row):
    reasons = []
    try:
        nums = {k: float(row[k]) for k in NUMERIC}
        if not all(math.isfinite(v) for v in nums.values()):
            reasons.append("NONFINITE_PRICE_COST_OR_MARK")
        if nums["fee_entry"] < 0 or nums["fee_exit"] < 0:
            reasons.append("NEGATIVE_FEE")
        if any(nums[k] <= 0 for k in ("entry_vwap", "stop_price", "liquidation_price")):
            reasons.append("NONPOSITIVE_PRICE")
        if nums["mark_min"] > nums["mark_max"]:
            reasons.append("INVERTED_MARK_RANGE")
        if any(not math.isfinite(float(row[k])) or float(row[k]) != int(float(row[k])) for k in TIMES + COUNTS + GAPS):
            reasons.append("NONINTEGER_EVENT_FIELD")
        times = [int(float(row[k])) for k in TIMES]
        if not (times[0] < times[1] <= times[2] < times[3]):
            reasons.append("NONCAUSAL_TIMELINE")
        if any(int(float(row[k])) < 2 for k in COUNTS):
            reasons.append("MISSING_EVENT_STREAM")
        if any(int(float(row[k])) < 0 or int(float(row[k])) > 60000 for k in GAPS):
            reasons.append("INVALID_OR_UNRESOLVED_GAP")
        side = row["side"]
        p, s, l = (nums[k] for k in ("entry_vwap", "stop_price", "liquidation_price"))
        if side == "LONG":
            if not l < s < p: reasons.append("STOP_NOT_BEFORE_LIQ")
            if nums["mark_min"] <= l: reasons.append("POSSIBLE_LIQUIDATION")
        elif side == "SHORT":
            if not p < s < l: reasons.append("STOP_NOT_BEFORE_LIQ")
            if nums["mark_max"] >= l: reasons.append("POSSIBLE_LIQUIDATION")
        else:
            reasons.append("INVALID_SIDE")
        if not row.get("source_hash") or len(row["source_hash"]) < 16:
            reasons.append("UNVERIFIABLE_SOURCE")
    except (KeyError, ValueError, TypeError, OverflowError, ZeroDivisionError):
        reasons.append("MISSING_OR_INVALID_FIELD")
    return sorted(set(reasons))

if __name__ == "__main__":
    base = dict(side="LONG", anchor_ts_ms=100, confirmation_ts_ms=200,
                entry_ts_ms=201, exit_ts_ms=300, entry_vwap=100,
                stop_price=99, liquidation_price=96, fee_entry=.01,
                fee_exit=.01, funding=0, mark_min=98, mark_max=101,
                quote_event_count=10, mark_event_count=10, l50_event_count=10,
                max_quote_gap_ms=1000, max_mark_gap_ms=1000,
                max_l50_gap_ms=1000, source_hash="0123456789abcdef")
    assert audit(base) == []
    for field, value in [("fee_entry", float("nan")),
                         ("fee_exit", float("inf")),
                         ("funding", float("-inf")),
                         ("entry_vwap", float("nan")),
                         ("mark_min", float("nan"))]:
        assert "NONFINITE_PRICE_COST_OR_MARK" in audit({**base, field: value})
    assert "INVALID_OR_UNRESOLVED_GAP" in audit({**base, "max_quote_gap_ms": -1})
    assert "NONINTEGER_EVENT_FIELD" in audit({**base, "entry_ts_ms": 201.5})
    assert "INVERTED_MARK_RANGE" in audit({**base, "mark_min": 102})
    print("9 finite/cost/chronology regression checks passed; synthetic only")
