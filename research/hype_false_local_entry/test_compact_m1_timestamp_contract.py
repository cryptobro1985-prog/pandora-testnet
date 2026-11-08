from research.hype_false_local_entry.causal_sequential_engine import CausalReversalMachine
from research.hype_false_local_entry.dense_causal_reachability import dense_completed_m1_candidates


def compact_bar(i, low=99.0, high=101.0, close=100.0):
    start=i*60_000
    end=start+60_000
    return {
        "start_ms":start,
        "bar_end_ms":end,
        "ts_ms":end,
        "low_ts_ms":start+10_000,
        "high_ts_ms":start+40_000,
        "low":low,
        "high":high,
        "close":close,
        "buy_notional":100.0,
        "sell_notional":90.0,
    }


def test_dense_accepts_canonical_compact_ts_equals_bar_end():
    bars=[compact_bar(0),compact_bar(1)]
    ev=list(dense_completed_m1_candidates(bars))
    assert len(ev)==4
    assert ev[0]["signal_ts_ms"]==60_000
    assert ev[0]["extreme_ts_ms"]==10_000


def test_sequential_engine_accepts_adjacent_canonical_compact_minutes():
    m=CausalReversalMachine()
    for i in range(35):
        m.on_bar(compact_bar(i))
    assert m.last_ts==35*60_000


def test_dense_still_rejects_true_overlap():
    a=compact_bar(0)
    b=compact_bar(1)
    b["start_ms"]=30_000
    try:
        list(dense_completed_m1_candidates([a,b]))
    except ValueError:
        return
    assert False,"overlap was accepted"
