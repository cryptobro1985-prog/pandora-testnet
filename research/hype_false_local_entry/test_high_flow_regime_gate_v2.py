from research.hype_false_local_entry.high_flow_regime_gate_v2 import (
    MIN_CANDIDATE_RANGE_BPS,MIN_TREND_TO_VOL,contract,regime_metrics,
)

def make_bars(ret_per_min=0.0001,candidate_range_bps=20):
    rows=[];price=100.0
    for i in range(181):
        start=i*60_000;op=price
        if i<180: price*=1+ret_per_min
        close=price
        half=candidate_range_bps/20_000 if i==180 else 0.0002
        rows.append({"start_ms":start,"bar_end_ms":start+60_000,"ts_ms":start+60_000,
                     "open":op,"close":close,"high":close*(1+half),"low":close*(1-half)})
    return rows

def test_contract_is_frozen_before_late_august_score():
    c=contract()
    assert c["min_trend_to_vol"]==MIN_TREND_TO_VOL==10.0
    assert c["min_candidate_range_bps"]==MIN_CANDIDATE_RANGE_BPS==10.0
    assert c["core_flip_authorized"] is False
    assert c["sealed_validation_period_not_scored_when_frozen"]=="2026-08-08..2026-09-01"

def test_candidate_minute_must_be_nontrivial():
    rows=make_bars(candidate_range_bps=4)
    m=regime_metrics(candidate_ts_ms=180*60_000+10_000,completed_m1_rows=rows)
    assert not m["checks"]["nontrivial_candidate_minute"]

def test_missing_history_never_fabricates_gate():
    rows=make_bars()[-30:]
    m=regime_metrics(candidate_ts_ms=180*60_000+10_000,completed_m1_rows=rows)
    assert not m["ready"]
    assert m["reason"]=="insufficient_causal_m1_history"
