from research.hype_false_local_entry.first_signal_objective import (
    build_episodes,
    promotion_gate,
    summarize_first_signals,
    summarize_actionable_first_signals,
)


def labels():
    return [
        {"label_id": 1, "side": "LOW", "extreme_interval_start_ms": 100, "extreme_interval_end_ms": 110, "reference_finalized": True},
        {"label_id": 2, "side": "HIGH", "extreme_interval_start_ms": 200, "extreme_interval_end_ms": 210, "reference_finalized": True},
        {"label_id": 3, "side": "LOW", "extreme_interval_start_ms": 300, "extreme_interval_end_ms": 310, "reference_finalized": True},
    ]


def test_false_first_is_not_erased_by_later_true_candidate():
    rows = [
        {"candidate_id": "false", "side": "HIGH", "candidate_ts_ms": 150, "signal_ts_ms": 160,
         "accepted": True, "internal_true": False, "internal_label_id": None},
        {"candidate_id": "true", "side": "HIGH", "candidate_ts_ms": 200, "signal_ts_ms": 205,
         "accepted": True, "internal_true": True, "internal_label_id": 2},
        {"candidate_id": "true-low", "side": "LOW", "candidate_ts_ms": 300, "signal_ts_ms": 305,
         "accepted": True, "internal_true": True, "internal_label_id": 3},
    ]
    m = summarize_first_signals(rows, labels())
    assert m["episodes"] == 2
    assert m["accepted_first"] == 2
    assert m["true_first"] == 1
    assert m["false_first"] == 1
    assert m["precision"] == 0.5
    assert m["recall"] == 0.5


def test_no_signal_counts_as_recall_miss_not_false_positive():
    rows = [
        {"candidate_id": "true", "side": "HIGH", "candidate_ts_ms": 200, "signal_ts_ms": 205,
         "accepted": True, "internal_true": True, "internal_label_id": 2},
    ]
    m = summarize_first_signals(rows, labels())
    assert m["accepted_first"] == 1
    assert m["true_first"] == 1
    assert m["false_first"] == 0
    assert m["no_signal"] == 1
    assert m["precision"] == 1.0
    assert m["recall"] == 0.5


def test_labels_must_alternate():
    bad = labels()
    bad[1] = dict(bad[1], side="LOW")
    try:
        build_episodes(bad)
    except ValueError:
        return
    assert False, "non-alternating labels were accepted"


def test_gate_is_explicit_and_paper_only():
    g = promotion_gate({"episodes": 25, "precision": .9, "recall": .5, "true_first": 12})
    assert g["passed"]
    assert g["authorization"] == "PAPER_FORWARD_ONLY"


def test_actionable_metric_ignores_signal_after_next_local_extreme():
    labs=[
        {"label_id":1,"side":"LOW","extreme_interval_start_ms":100,"extreme_interval_end_ms":110,"reference_finalized":True},
        {"label_id":2,"side":"HIGH","extreme_interval_start_ms":200,"extreme_interval_end_ms":210,"reference_finalized":True},
        {"label_id":3,"side":"LOW","extreme_interval_start_ms":300,"extreme_interval_end_ms":310,"reference_finalized":True},
    ]
    late=[{"candidate_id":"H","side":"HIGH","candidate_ts_ms":200,"signal_ts_ms":305,
           "accepted":True,"internal_true":True,"internal_label_id":2}]
    m=summarize_actionable_first_signals(late,labs)
    assert m["episodes"]==1
    assert m["accepted_first"]==0
    assert m["no_signal"]==1
    assert m["actionable_deadline"]=="NEXT_FINALIZED_LOCAL_EXTREME"


def test_actionable_metric_counts_same_signal_before_deadline():
    labs=[
        {"label_id":1,"side":"LOW","extreme_interval_start_ms":100,"extreme_interval_end_ms":110,"reference_finalized":True},
        {"label_id":2,"side":"HIGH","extreme_interval_start_ms":200,"extreme_interval_end_ms":210,"reference_finalized":True},
        {"label_id":3,"side":"LOW","extreme_interval_start_ms":300,"extreme_interval_end_ms":310,"reference_finalized":True},
    ]
    rows=[{"candidate_id":"H","side":"HIGH","candidate_ts_ms":200,"signal_ts_ms":250,
           "accepted":True,"internal_true":True,"internal_label_id":2}]
    m=summarize_actionable_first_signals(rows,labs)
    assert m["true_first"]==1
    assert m["precision"]==1.0
    assert m["recall"]==1.0
