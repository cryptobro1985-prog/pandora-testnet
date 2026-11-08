from research.hype_false_local_entry.hard_survival_gate import (
    HARD_AGE_S, HardCandidate, contract, maybe_start_or_extend,
    pre_move_180_bps, should_emit,
)


def bars(n=180):
    return [
        {"start_ms":i*60_000,"bar_end_ms":(i+1)*60_000,
         "high":110.0-i*.01,"low":100.0-i*.01}
        for i in range(n)
    ]


def test_pre_move_uses_only_completed_prior_rows():
    rows=bars(180)
    # Future row must be ignored.
    rows.append({"start_ms":180*60_000,"bar_end_ms":181*60_000,"high":999,"low":1})
    v=pre_move_180_bps("LOW",98.0,rows,180*60_000)
    assert 0 < v < 2_000


def test_stale_refresh_does_not_reset_hard_lineage():
    c=maybe_start_or_extend(None,side="LOW",price=100,ts_ms=1_000,
        candidate_id="L-1",windows=["6h"],completed_m1_rows=bars())
    same=maybe_start_or_extend(c,side="LOW",price=101,ts_ms=3_601_000,
        candidate_id="L-stale",windows=["6h"],completed_m1_rows=bars())
    assert same is c
    assert same.candidate_id=="L-1"


def test_more_extreme_6h_candidate_resets_clock():
    c=maybe_start_or_extend(None,side="LOW",price=100,ts_ms=1_000,
        candidate_id="L-1",windows=["6h"],completed_m1_rows=bars())
    newer=maybe_start_or_extend(c,side="LOW",price=99,ts_ms=2_000,
        candidate_id="L-2",windows=["6h"],completed_m1_rows=bars())
    assert newer is not c
    assert newer.candidate_id=="L-2"
    assert newer.extreme_ts_ms==2_000


def test_non_6h_candidate_never_starts_hard_lineage():
    c=maybe_start_or_extend(None,side="HIGH",price=100,ts_ms=1_000,
        candidate_id="H-1",windows=["5m","60m"],completed_m1_rows=bars())
    assert c is None


def test_hard120_requires_age_retrace_fraction_and_expected_side():
    c=HardCandidate("LOW",100.0,0,"L",200.0,["6h"])
    ok,m=should_emit(c,now_ms=(HARD_AGE_S-1)*1000,mark_price=101.0,expected_side="LOW")
    assert not ok and not m["age_ready"]
    # 100 bps retrace / 200 bps pre-move = 50%, so it passes after 120m.
    ok,m=should_emit(c,now_ms=HARD_AGE_S*1000,mark_price=101.0,expected_side="LOW")
    assert ok
    assert m["retrace_bps"] >= 99
    assert m["retrace_fraction_pre_180"] >= .49
    blocked,_=should_emit(c,now_ms=HARD_AGE_S*1000,mark_price=101.0,expected_side="HIGH")
    assert not blocked


def test_contract_is_paper_only_and_never_core_flip():
    c=contract()
    assert c["role"]=="TACTICAL_HARD_PAPER_ONLY"
    assert c["core_flip_authorized"] is False
    assert c["stale_refresh_resets_clock"] is False
