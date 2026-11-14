"""Research-only execution manifest gate for HYPE post-H1-local trades.
No public trade print is treated as a private fill. No live orders.
Run: python research/hype_terminal_local_strategy/trade_manifest_gate_research.py [manifest.json]
"""
import json
import math
import sys

COMMON = ("trade_id", "side", "local_type", "local_ts_ms",
          "signal_available_ts_ms", "order_submit_ts_ms", "entry_fill_ts_ms",
          "entry_fill_price", "entry_fill_source", "entry_notional",
          "stop_price", "exit_reason", "exit_ts_ms", "exit_fill_price",
          "exit_fill_source", "fees_paid", "funding_paid",
          "mark_path_source", "l50_path_source", "public_trades_source",
          "event_sequence_source", "coverage_complete",
          "protective_stop_order_source")
STOP_FIELDS = ("stop_trigger_ts_ms", "stop_fill_ts_ms", "stop_fill_price",
               "stop_fill_source")
OPPOSITE_FIELDS = ("opposite_local_ts_ms", "opposite_signal_available_ts_ms",
                   "exit_order_submit_ts_ms")

def gate(row):
    missing = [k for k in COMMON if k not in row or row[k] is None]
    if missing:
        return {"status": "UNVERIFIED_MISSING_FIELDS", "missing": missing}
    side, reason = row["side"], row["exit_reason"]
    if (side, row["local_type"]) not in (("LONG", "LOW"), ("SHORT", "HIGH")):
        return {"status": "REJECT_SIDE_LOCAL_MISMATCH"}
    if reason not in ("STOP", "OPPOSITE_LOCAL"):
        return {"status": "UNVERIFIED_EXIT_REASON"}
    needed = STOP_FIELDS if reason == "STOP" else OPPOSITE_FIELDS
    missing = [k for k in needed if k not in row or row[k] is None]
    if missing:
        return {"status": "UNVERIFIED_MISSING_EXIT_FIELDS", "missing": missing}
    if reason == "OPPOSITE_LOCAL" and any(row.get(k) is not None for k in STOP_FIELDS):
        return {"status": "UNVERIFIED_CONFLICTING_STOP_EVENTS"}
    times = [row[k] for k in ("local_ts_ms", "signal_available_ts_ms",
                              "order_submit_ts_ms", "entry_fill_ts_ms", "exit_ts_ms")]
    if not all(type(t) is int for t in times) or not all(a < b for a, b in zip(times, times[1:])):
        return {"status": "REJECT_CAUSAL_TIME"}
    entry, exit_time = times[3], times[4]
    if reason == "STOP":
        trigger, fill = row["stop_trigger_ts_ms"], row["stop_fill_ts_ms"]
        if type(trigger) is not int or type(fill) is not int:
            return {"status": "REJECT_STOP_TIME"}
        if not (entry < trigger < fill <= exit_time):
            return {"status": "UNVERIFIED_STOP_EVENT_ORDER"}
        if fill != exit_time:
            return {"status": "UNVERIFIED_STOP_EXIT_MISMATCH"}
    else:
        local, available, submit = (row[k] for k in OPPOSITE_FIELDS)
        if not all(type(t) is int for t in (local, available, submit)):
            return {"status": "REJECT_OPPOSITE_TIME"}
        if not (entry < local < available < submit < exit_time):
            return {"status": "UNVERIFIED_OPPOSITE_EVENT_ORDER"}
    try:
        p, stop, notional, ep = (float(row[k]) for k in
                                ("entry_fill_price", "stop_price", "entry_notional",
                                 "exit_fill_price"))
        fees, funding = float(row["fees_paid"]), float(row["funding_paid"])
        sf = float(row["stop_fill_price"]) if reason == "STOP" else None
    except (TypeError, ValueError, OverflowError):
        return {"status": "REJECT_NUMERIC"}
    nums = [p, stop, notional, ep, fees, funding] + ([sf] if sf is not None else [])
    if not all(math.isfinite(v) for v in nums) or min(p, stop, notional, ep) <= 0 or fees < 0:
        return {"status": "REJECT_NUMERIC"}
    if sf is not None and sf <= 0:
        return {"status": "REJECT_NUMERIC"}
    if (side == "LONG" and stop >= p) or (side == "SHORT" and stop <= p):
        return {"status": "REJECT_PRICE_GEOMETRY"}
    sources = ("entry_fill_source", "exit_fill_source", "mark_path_source",
               "l50_path_source", "public_trades_source",
               "event_sequence_source", "protective_stop_order_source")
    if reason == "STOP":
        sources += ("stop_fill_source",)
    if row["coverage_complete"] is not True or any(not row[k] for k in sources):
        return {"status": "UNVERIFIED_SOURCE_COVERAGE"}
    if reason == "STOP" and abs(ep - sf) > max(1e-9, abs(ep) * 1e-9):
        return {"status": "UNVERIFIED_STOP_EXIT_MISMATCH"}
    signed = (ep / p - 1) * (1 if side == "LONG" else -1)
    result = {"status": "EXECUTION_FIELDS_COMPLETE_NOT_LIQUIDATION_VERIFIED",
              "exit_reason": reason,
              "observed_net_pnl_quote": round(notional * signed - fees - funding, 10)}
    if reason == "STOP":
        result["stop_gap_fraction"] = round((stop - sf) / stop if side == "LONG" else (sf - stop) / stop, 10)
    return result

def self_test():
    base = dict(trade_id="T1", side="LONG", local_type="LOW",
                local_ts_ms=10, signal_available_ts_ms=20,
                order_submit_ts_ms=21, entry_fill_ts_ms=22,
                entry_fill_price=100, entry_fill_source="private-fill",
                entry_notional=100, stop_price=99, exit_reason="STOP",
                stop_trigger_ts_ms=30, stop_fill_ts_ms=31,
                stop_fill_price=98.8, stop_fill_source="private-fill",
                exit_ts_ms=31, exit_fill_price=98.8,
                exit_fill_source="private-fill", fees_paid=.15, funding_paid=0,
                mark_path_source="mark", l50_path_source="l50",
                public_trades_source="tape", event_sequence_source="sequence",
                coverage_complete=True, protective_stop_order_source="order-log")
    ok = "EXECUTION_FIELDS_COMPLETE_NOT_LIQUIDATION_VERIFIED"
    assert gate(base)["status"] == ok
    assert abs(gate(base)["observed_net_pnl_quote"] + 1.35) < 1e-8
    opposite = {**base, "exit_reason": "OPPOSITE_LOCAL",
                "opposite_local_ts_ms": 40, "opposite_signal_available_ts_ms": 50,
                "exit_order_submit_ts_ms": 51, "exit_ts_ms": 52,
                "exit_fill_price": 103,
                **{k: None for k in STOP_FIELDS}}
    assert gate(opposite)["status"] == ok
    assert gate(opposite)["observed_net_pnl_quote"] == 2.85
    assert "stop_gap_fraction" not in gate(opposite)
    short = {**opposite, "side": "SHORT", "local_type": "HIGH",
             "stop_price": 101, "exit_fill_price": 97}
    assert gate(short)["status"] == ok
    assert gate({**base, "side": "SHORT"})["status"] == "REJECT_SIDE_LOCAL_MISMATCH"
    assert gate({**opposite, "opposite_signal_available_ts_ms": 41,
                 "exit_order_submit_ts_ms": 40})["status"] == "UNVERIFIED_OPPOSITE_EVENT_ORDER"
    assert gate({**opposite, "stop_trigger_ts_ms": 45})["status"] == "UNVERIFIED_CONFLICTING_STOP_EVENTS"
    assert gate({**base, "stop_fill_ts_ms": None})["status"] == "UNVERIFIED_MISSING_EXIT_FIELDS"
    assert gate({**base, "stop_fill_price": 99})["status"] == "UNVERIFIED_STOP_EXIT_MISMATCH"
    assert gate({**opposite, "protective_stop_order_source": ""})["status"] == "UNVERIFIED_SOURCE_COVERAGE"
    assert gate({**base, "signal_available_ts_ms": 22})["status"] == "REJECT_CAUSAL_TIME"
    assert gate({**base, "entry_fill_price": float("nan")})["status"] == "REJECT_NUMERIC"
    assert gate({**base, "exit_reason": "OTHER"})["status"] == "UNVERIFIED_EXIT_REASON"
    return 13

if __name__ == "__main__":
    print("synthetic tests:", self_test())
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            rows = json.load(f)
        if not isinstance(rows, list):
            raise ValueError("manifest must be a JSON list")
        print(json.dumps([{"trade_id": r.get("trade_id"), **gate(r)} for r in rows],
                         ensure_ascii=False, indent=2))
