from research.hype_false_local_entry.early60_strong_reversal_shadow import (
    Early60State, AGE_S, capture_flow15, checkpoint_sample, evaluate_once, metrics,
)


def bars(candidate_ts, n=70, close=101.0):
    out=[]
    base=(candidate_ts//60_000)*60_000
    for i in range(1,n+1):
        start=base+i*60_000
        out.append({"start_ms":start,"bar_end_ms":start+60_000,
                    "high":close+0.1,"low":close-0.1,"close":close})
    return out


def trades(candidate_ts, side="LOW", count=120):
    start=(candidate_ts//60_000)*60_000+60_000
    out=[]
    for i in range(count):
        # LOW reversal = buyer dominant; HIGH reversal = seller dominant.
        buy=(side=="LOW")
        out.append({"ts_ms":start+(i%(15*60))*1000,
                    "notional":100.0,"side":1 if buy else -1})
    return out


def test_low_and_high_reversal_flow_direction():
    ts=10_000
    for side in ("LOW","HIGH"):
        s=Early60State("x")
        cap=capture_flow15(s,candidate_ts_ms=ts,trades=trades(ts,side),observed_ms=16*60_000)
        assert cap["ready"]
        m=metrics(side=side,extreme_price=100,pre_move_180_bps=120,
                  mark_price=101 if side=="LOW" else 99,state=s,expected_side=side)
        assert m["reversal_flow_15"]==1.0
        assert m["flow_ready"]


def test_exact_60m_checkpoint_emits_once():
    ts=10_000;s=Early60State("x")
    capture_flow15(s,candidate_ts_ms=ts,trades=trades(ts,"LOW"),observed_ms=16*60_000)
    rows=bars(ts,70,close=101.0)
    sample=checkpoint_sample(ts,rows,observed_ms=61*60_000)
    assert sample is not None and sample["fresh_observation"]
    ok,m=evaluate_once(s,side="LOW",extreme_price=100,pre_move_180_bps=120,
                       sample=sample,expected_side="LOW")
    assert ok and m["ready"] and s.emitted
    ok2,m2=evaluate_once(s,side="LOW",extreme_price=100,pre_move_180_bps=120,
                         sample=sample,expected_side="LOW")
    assert not ok2 and m2["reason"]=="already_emitted"


def test_wrong_expected_side_never_emits():
    ts=10_000;s=Early60State("x")
    capture_flow15(s,candidate_ts_ms=ts,trades=trades(ts,"LOW"),observed_ms=16*60_000)
    sample=checkpoint_sample(ts,bars(ts),observed_ms=61*60_000)
    ok,m=evaluate_once(s,side="LOW",extreme_price=100,pre_move_180_bps=120,
                       sample=sample,expected_side="HIGH")
    assert not ok and not m["expected_side_ok"]
    assert s.checkpoint_evaluated


def test_long_restart_consumes_checkpoint_without_retro_signal():
    ts=10_000;s=Early60State("x")
    capture_flow15(s,candidate_ts_ms=ts,trades=trades(ts,"LOW"),observed_ms=16*60_000)
    sample=checkpoint_sample(ts,bars(ts),observed_ms=70*60_000)
    assert sample is not None and not sample["fresh_observation"]
    ok,m=evaluate_once(s,side="LOW",extreme_price=100,pre_move_180_bps=120,
                       sample=sample,expected_side="LOW")
    assert not ok and m["checkpoint_missed"]
    assert s.checkpoint_evaluated and not s.emitted
