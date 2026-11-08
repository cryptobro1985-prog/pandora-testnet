from research.hype_false_local_entry.high_flow_shadow import (
    FLOW_CAPTURE_GRACE_MS, HighFlowShadowState, capture_flow15, contract,
    should_emit_shadow,
)


def trades(start_ms, *, buy_n=40, sell_n=80, notional=100.0):
    rows=[]
    span=15*60_000
    total=buy_n+sell_n
    for i in range(total):
        rows.append({
            "ts_ms":start_ms+1+int(i*(span-2)/max(1,total-1)),
            "side":1 if i<buy_n else -1,
            "notional":notional,
        })
    return rows


def test_capture_uses_15_complete_minutes_after_candidate_minute():
    candidate_ts=30_123
    start=60_000
    end=start+15*60_000
    s=HighFlowShadowState("H")
    out=capture_flow15(s,candidate_ts_ms=candidate_ts,
        trades=trades(start,buy_n=40,sell_n=80),observed_ms=end)
    assert out["ready"]
    assert s.flow_15 < -0.3
    assert s.flow_15_trade_count==120
    assert s.flow_15_sample_end_ms==end


def test_flow_window_is_never_reconstructed_after_long_delay():
    candidate_ts=0
    end=60_000+15*60_000
    s=HighFlowShadowState("H")
    out=capture_flow15(s,candidate_ts_ms=candidate_ts,trades=[],
        observed_ms=end+FLOW_CAPTURE_GRACE_MS+1)
    assert out["missed"]
    assert s.flow_15_missed


def test_shadow_only_fills_fraction_gap_with_seller_flow():
    s=HighFlowShadowState("H",flow_15=-0.20,flow_15_trade_count=500)
    ok,m=should_emit_shadow(
        side="HIGH",primary_emitted=False,expected_side_ok=True,
        checkpoint_fresh=True,retrace_bps=80,
        retrace_fraction_pre_180=.38,state=s)
    assert ok
    assert m["checks"]["seller_flow"]


def test_shadow_does_not_duplicate_primary_or_relax_to_low():
    s=HighFlowShadowState("H",flow_15=-0.20,flow_15_trade_count=500)
    ok,_=should_emit_shadow(side="HIGH",primary_emitted=True,
        expected_side_ok=True,checkpoint_fresh=True,retrace_bps=80,
        retrace_fraction_pre_180=.38,state=s)
    assert not ok
    ok,_=should_emit_shadow(side="LOW",primary_emitted=False,
        expected_side_ok=True,checkpoint_fresh=True,retrace_bps=80,
        retrace_fraction_pre_180=.38,state=s)
    assert not ok


def test_shadow_requires_fraction_below_primary_and_strong_seller_flow():
    s=HighFlowShadowState("H",flow_15=-0.04,flow_15_trade_count=500)
    ok,_=should_emit_shadow(side="HIGH",primary_emitted=False,
        expected_side_ok=True,checkpoint_fresh=True,retrace_bps=80,
        retrace_fraction_pre_180=.38,state=s)
    assert not ok
    s.flow_15=-0.20
    ok,_=should_emit_shadow(side="HIGH",primary_emitted=False,
        expected_side_ok=True,checkpoint_fresh=True,retrace_bps=80,
        retrace_fraction_pre_180=.46,state=s)
    assert not ok


def test_contract_is_shadow_only():
    c=contract()
    assert c["name"]=="HARD120_HIGH_FLOW_SHADOW_V1"
    assert c["core_flip_authorized"] is False
    assert c["primary_contract_unchanged"] is True
    assert c["historical_status"]=="CROSS_PERIOD_TUNED_NOT_OOS"
