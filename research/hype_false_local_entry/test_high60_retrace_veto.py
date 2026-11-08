from research.hype_false_local_entry.high60_retrace_veto import (
    sample_retrace60,high_primary_confirmed,MIN_HIGH_RETRACE_60_BPS,
)

def bars(close):
    return [{"bar_end_ms":3_600_000,"close":close}]

def test_high_requires_50bps_at_60m():
    s=sample_retrace60(side="HIGH",candidate_ts_ms=0,extreme_price=100.0,
                       completed_m1_rows=bars(99.4),observed_ms=3_600_000)
    ok,m=high_primary_confirmed(side="HIGH",sample=s)
    assert ok and m["retrace_60_bps"]>=MIN_HIGH_RETRACE_60_BPS

def test_high_rejects_weak_60m_retrace():
    s=sample_retrace60(side="HIGH",candidate_ts_ms=0,extreme_price=100.0,
                       completed_m1_rows=bars(99.7),observed_ms=3_600_000)
    ok,m=high_primary_confirmed(side="HIGH",sample=s)
    assert not ok and m["retrace_60_bps"]<MIN_HIGH_RETRACE_60_BPS

def test_low_primary_is_unchanged():
    ok,m=high_primary_confirmed(side="LOW",sample=None)
    assert ok and not m["applies"]
