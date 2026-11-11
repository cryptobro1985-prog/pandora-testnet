from research.hype_false_local_entry.early_causal_core_entry_mfe_v1 import require_label_cohort

def test_missing_internal_fails_closed():
    labels, issue = require_label_cohort({"strict": [{"label_id": 1}]}, "internal", "JUL_AUG")
    assert labels is None
    assert issue["not_scored"] is True
    assert issue["label_count"] == 0
    assert issue["cohort"] == "internal"

def test_single_label_cannot_define_completed_swing():
    labels, issue = require_label_cohort({"internal": [{"label_id": 1, "extreme_interval_start_ms": 10}]}, "internal", "X")
    assert labels is None
    assert issue["status"] == "MISSING_OR_INSUFFICIENT_LABELS"

def test_two_labels_are_scored():
    doc = {"internal": [
        {"label_id": 1, "extreme_interval_start_ms": 10, "side": "LOW"},
        {"label_id": 2, "extreme_interval_start_ms": 20, "side": "HIGH"},
    ]}
    labels, issue = require_label_cohort(doc, "internal", "X")
    assert issue is None
    assert [x["label_id"] for x in labels] == [1, 2]
