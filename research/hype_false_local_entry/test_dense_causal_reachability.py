from research.hype_false_local_entry.dense_causal_reachability import (
    dense_completed_m1_candidates, evaluate_reachability,
)


def test_dense_covers_non_breakout_internal_turn():
    rows = [
        {"ts_ms": 0, "bar_end_ms": 60000, "low": 10, "high": 20},
        {"ts_ms": 60000, "bar_end_ms": 120000, "low": 12, "high": 18},
        {"ts_ms": 120000, "bar_end_ms": 180000, "low": 11, "high": 19},
    ]
    events = list(dense_completed_m1_candidates(rows))
    assert len(events) == 6
    assert all(e["signal_ts_ms"] >= e["extreme_ts_ms"] for e in events)
    assert all(not e["entry_signal"] for e in events)
    labels = [{"label_id": 7, "side": "LOW",
               "extreme_interval_start_ms": 60000,
               "extreme_interval_end_ms": 120000}]
    assert evaluate_reachability(events, labels, tolerance_ms=0)["covered"] == 1


def test_dense_rejects_future_extreme():
    rows = [{"ts_ms": 0, "bar_end_ms": 60000, "low": 10, "high": 20,
             "low_ts_ms": 90000}]
    try:
        list(dense_completed_m1_candidates(rows))
    except ValueError:
        return
    assert False, "future timestamp was accepted"
