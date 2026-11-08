from engine import Decision, Evidence, FalseLocalEntryEngine, PositionRouter, ReversalState


def e(**kw):
    base=dict(
        side="LOW",
        survival_s=600,
        swing_atr_mult=3.0,
        retrace_fraction=.13,
        edge_recovery_60m=.35,
        edge_recovery_6h=.22,
        rev_return_180s=.002,
        rev_return_300s=.001,
        rev_flow_180s=.2,
        rev_flow_3m=.15,
        rev_eff_300s=.002,
        macd_hist_rev_bps=2.0,
        macd_slope3_rev_bps=1.0,
    )
    base.update(kw)
    return Evidence(**base)


def test_invalidation_wins():
    d=FalseLocalEntryEngine().evaluate(e(same_side_extreme_broken=True))
    assert d.state == ReversalState.INVALIDATED
    assert d.target_paper_fraction == 0.0


def test_early_is_small_probe():
    d=FalseLocalEntryEngine().evaluate(e())
    assert d.state == ReversalState.EARLY_PROBE
    assert d.target_paper_fraction == .10


def test_30m_confirmation_is_partial():
    d=FalseLocalEntryEngine().evaluate(e(survival_s=1800))
    assert d.state == ReversalState.CONFIRMED
    assert d.target_paper_fraction == .35


def test_60m_hard_gate():
    d=FalseLocalEntryEngine().evaluate(
        e(survival_s=3600, swing_atr_mult=3.8, retrace_fraction=.18)
    )
    assert d.state == ReversalState.HARD_CONFIRMED
    assert d.target_paper_fraction == .70


def test_early_opposite_does_not_flip_core():
    router=PositionRouter()
    decision=Decision(ReversalState.EARLY_PROBE,.10,True,"probe")
    side,f=router.desired_fraction("LONG",decision,"HIGH")
    assert side == "LONG"
    assert f == 1.0


def test_hard_opposite_can_flip():
    router=PositionRouter()
    decision=Decision(ReversalState.HARD_CONFIRMED,.70,True,"hard")
    side,f=router.desired_fraction("LONG",decision,"HIGH")
    assert side == "SHORT"
    assert f == .70
