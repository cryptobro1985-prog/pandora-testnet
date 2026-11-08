from research.hype_false_local_entry.hard_survival_gate import (
    CHECKPOINT_GRACE_S,
    HARD_AGE_S,
    HardCandidate,
    contract,
    maybe_start_or_extend,
    next_signal,
    pre_move_180_bps,
    should_emit,
)


def bars(n=180):
    return [
        {"start_ms":i*60_000,"bar_end_ms":(i+1)*60_000,
         "high":110.0-i*.01,"low":100.0-i*.01}
        for i in range(n)
    ]


def test_pre_move_uses_only_completed_prior_rows():
    rows=bars(180)
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


def test_hard120_is_one_shot_checkpoint_not_late_crossing():
    c=HardCandidate("LOW",100.0,0,"L120",200.0,["6h"])
    stage,m=next_signal(c,now_ms=(HARD_AGE_S-1)*1000,mark_price=101.5,expected_side="LOW")
    assert stage is None
    assert c.evaluated_stages==[]

    stage,m=next_signal(c,now_ms=HARD_AGE_S*1000,mark_price=101.0,expected_side="LOW")
    assert stage=="HARD120"
    assert m["retrace_fraction_pre_180"] >= .49
    assert c.evaluated_stages==["HARD120"]

    stage,_=next_signal(c,now_ms=(HARD_AGE_S+600)*1000,mark_price=102.0,expected_side="LOW")
    assert stage is None


def test_failed_hard120_checkpoint_never_becomes_late_success():
    c=HardCandidate("HIGH",100.0,0,"H120",200.0,["6h"])
    stage,_=next_signal(c,now_ms=HARD_AGE_S*1000,mark_price=99.5,expected_side="HIGH")
    assert stage is None
    assert c.evaluated_stages==["HARD120"]

    stage,_=next_signal(c,now_ms=(HARD_AGE_S+600)*1000,mark_price=98.0,expected_side="HIGH")
    assert stage is None


def test_expected_side_can_block_checkpoint_without_core_flip():
    c=HardCandidate("LOW",100.0,0,"blocked",200.0,["6h"])
    stage,_=next_signal(c,now_ms=HARD_AGE_S*1000,mark_price=101.0,expected_side="HIGH")
    assert stage is None
    assert c.evaluated_stages==["HARD120"]


def test_contract_is_paper_only_and_never_core_flip():
    c=contract()
    assert c["name"]=="INTERNAL_HARD120_CHECKPOINT_V2"
    assert c["role"]=="TACTICAL_HARD_PAPER_ONLY"
    assert c["age_s"]==HARD_AGE_S
    assert c["min_retrace_fraction_pre_180"]==0.45
    assert c["core_flip_authorized"] is False
    assert c["stale_refresh_resets_clock"] is False
    assert "no late recovery" in c["checkpoint_semantics"]


def test_partial_pre_move_window_cannot_start_lineage():
    partial=bars(60)
    c=maybe_start_or_extend(None,side="LOW",price=98,ts_ms=180*60_000,
        candidate_id="L-partial",windows=["6h"],completed_m1_rows=partial)
    assert c is None


def test_late_restart_does_not_grant_retroactive_hard120():
    c=HardCandidate("HIGH",100.0,0,"H-late",200.0,["6h"])
    stage,m=next_signal(
        c,
        now_ms=(HARD_AGE_S+CHECKPOINT_GRACE_S+1)*1000,
        mark_price=98.0,
        expected_side="HIGH",
    )
    assert stage is None
    assert "HARD120" in c.evaluated_stages
    assert m["hard120_within_checkpoint_window"] is False


def test_checkpoint_state_persists_in_candidate_dict():
    c=HardCandidate("LOW",100.0,0,"persist",200.0,["6h"])
    next_signal(c,now_ms=HARD_AGE_S*1000,mark_price=100.5,expected_side="LOW")
    d=c.to_dict()
    assert d["evaluated_stages"]==["HARD120"]
    restored=HardCandidate(**d)
    stage,_=next_signal(restored,now_ms=(HARD_AGE_S+300)*1000,mark_price=101.5,expected_side="LOW")
    assert stage is None


def test_boolean_wrapper_matches_checkpoint_signal():
    c=HardCandidate("LOW",100.0,0,"bool",200.0,["6h"])
    ok,m=should_emit(c,now_ms=HARD_AGE_S*1000,mark_price=101.0,expected_side="LOW")
    assert ok
    assert m["ready_stage"]=="HARD120"
