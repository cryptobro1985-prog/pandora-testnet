from research.hype_false_local_entry.hard_survival_gate import (
    CHECKPOINT_GRACE_S, EARLY_HARD_AGE_S, HARD_AGE_S, HardCandidate, contract, maybe_start_or_extend,
    next_signal, pre_move_180_bps, should_emit,
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
    base=181*60_000
    c=maybe_start_or_extend(None,side="LOW",price=100,ts_ms=base,
        candidate_id="L-1",windows=["6h"],completed_m1_rows=bars())
    same=maybe_start_or_extend(c,side="LOW",price=101,ts_ms=base+3_600_000,
        candidate_id="L-stale",windows=["6h"],completed_m1_rows=bars())
    assert same is c
    assert same.candidate_id=="L-1"


def test_more_extreme_6h_candidate_resets_clock():
    base=181*60_000
    c=maybe_start_or_extend(None,side="LOW",price=100,ts_ms=base,
        candidate_id="L-1",windows=["6h"],completed_m1_rows=bars())
    newer=maybe_start_or_extend(c,side="LOW",price=99,ts_ms=base+60_000,
        candidate_id="L-2",windows=["6h"],completed_m1_rows=bars())
    assert newer is not c
    assert newer.candidate_id=="L-2"
    assert newer.extreme_ts_ms==base+60_000


def test_non_6h_candidate_never_starts_hard_lineage():
    c=maybe_start_or_extend(None,side="HIGH",price=100,ts_ms=1_000,
        candidate_id="H-1",windows=["5m","60m"],completed_m1_rows=bars())
    assert c is None


def test_survival_ladder_uses_strict_90m_then_120m_fallback():
    early=HardCandidate("LOW",100.0,0,"L90",200.0,["6h"])
    stage,m=next_signal(early,now_ms=(EARLY_HARD_AGE_S-1)*1000,mark_price=101.4,expected_side="LOW")
    assert stage is None and not m["early_age_ready"]

    # 140 bps / 200 bps = 70%: strong enough exactly at HARD90.
    stage,m=next_signal(early,now_ms=EARLY_HARD_AGE_S*1000,mark_price=101.4,expected_side="LOW")
    assert stage=="HARD90"
    assert m["early_fraction_ready"]
    assert early.evaluated_stages==["HARD90"]

    fallback=HardCandidate("LOW",100.0,0,"L120",200.0,["6h"])
    # A weaker 50% recovery fails HARD90 permanently.
    stage,_=next_signal(fallback,now_ms=EARLY_HARD_AGE_S*1000,mark_price=101.0,expected_side="LOW")
    assert stage is None
    assert fallback.evaluated_stages==["HARD90"]
    # A later 70% recovery before 120m must NOT be retroactively accepted.
    stage,_=next_signal(fallback,now_ms=(EARLY_HARD_AGE_S+600)*1000,mark_price=101.4,expected_side="LOW")
    assert stage is None
    # The separate HARD120 fallback may pass at its checkpoint.
    stage,m=next_signal(fallback,now_ms=HARD_AGE_S*1000,mark_price=101.0,expected_side="LOW")
    assert stage=="HARD120"
    assert m["retrace_fraction_pre_180"] >= .49
    assert fallback.evaluated_stages==["HARD90","HARD120"]

    blocked=HardCandidate("LOW",100.0,0,"blocked",200.0,["6h"])
    stage,_=next_signal(blocked,now_ms=EARLY_HARD_AGE_S*1000,mark_price=101.4,expected_side="HIGH")
    assert stage is None


def test_contract_is_paper_only_and_never_core_flip():
    c=contract()
    assert c["name"]=="INTERNAL_SURVIVAL_LADDER_V1"
    assert c["role"]=="TACTICAL_HARD_PAPER_ONLY"
    assert c["stages"]["HARD90"]["age_s"]==EARLY_HARD_AGE_S
    assert c["stages"]["HARD120"]["age_s"]==HARD_AGE_S
    assert c["core_flip_authorized"] is False
    assert c["stale_refresh_resets_clock"] is False


def test_partial_pre_move_window_cannot_start_lineage():
    partial=bars(60)
    c=maybe_start_or_extend(None,side="LOW",price=98,ts_ms=180*60_000,
        candidate_id="L-partial",windows=["6h"],completed_m1_rows=partial)
    assert c is None


def test_late_restart_does_not_grant_retroactive_hard90():
    c=HardCandidate("HIGH",100.0,0,"H-late",200.0,["6h"])
    stage,m=next_signal(
        c,
        now_ms=(EARLY_HARD_AGE_S+CHECKPOINT_GRACE_S+1)*1000,
        mark_price=98.0,
        expected_side="HIGH",
    )
    assert stage is None
    assert "HARD90" in c.evaluated_stages
    assert m["hard90_within_checkpoint_window"] is False


def test_checkpoint_state_persists_in_candidate_dict():
    c=HardCandidate("LOW",100.0,0,"persist",200.0,["6h"])
    next_signal(c,now_ms=EARLY_HARD_AGE_S*1000,mark_price=100.5,expected_side="LOW")
    d=c.to_dict()
    assert d["evaluated_stages"]==["HARD90"]
    restored=HardCandidate(**d)
    stage,_=next_signal(restored,now_ms=(EARLY_HARD_AGE_S+300)*1000,mark_price=101.5,expected_side="LOW")
    assert stage is None
