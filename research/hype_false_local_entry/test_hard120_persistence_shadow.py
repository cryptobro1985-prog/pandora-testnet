from research.hype_false_local_entry.hard120_persistence_shadow import (
    MIN_PERSISTENCE,persistence_metrics,contract,
)

def bars(side="LOW"):
    if side=="LOW":
        return [
            {"bar_end_ms":120_000,"high":101.0,"low":99.5},
            {"bar_end_ms":180_000,"high":102.0,"low":100.2},
        ]
    return [
        {"bar_end_ms":120_000,"high":100.5,"low":99.0},
        {"bar_end_ms":180_000,"high":99.8,"low":98.0},
    ]

def test_low_persistence_uses_completed_path_high():
    m=persistence_metrics(side="LOW",extreme_price=100,retrace_bps=130,
                          candidate_ts_ms=60_000,sample_ts_ms=180_000,
                          completed_m1_rows=bars("LOW"))
    assert round(m["max_reversal_bps"],6)==200.0
    assert round(m["reversal_persistence"],6)==0.65
    assert m["ready"]

def test_high_persistence_uses_completed_path_low():
    m=persistence_metrics(side="HIGH",extreme_price=100,retrace_bps=100,
                          candidate_ts_ms=60_000,sample_ts_ms=180_000,
                          completed_m1_rows=bars("HIGH"))
    assert round(m["max_reversal_bps"],6)==round((100/98-1)*10000,6)
    assert not m["ready"]

def test_contract_is_shadow_only_and_frozen_before_holdout():
    c=contract()
    assert c["min_reversal_persistence"]==MIN_PERSISTENCE==0.65
    assert c["primary_contract_unchanged"] is True
    assert c["core_flip_authorized"] is False
    assert "2026-09-01" in c["holdout_not_inspected_when_frozen"]
