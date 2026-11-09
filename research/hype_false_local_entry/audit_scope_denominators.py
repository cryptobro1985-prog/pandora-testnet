"""Fail-closed reconciliation of historical HYPE label/swing denominators.

Run: python -m research.hype_false_local_entry.audit_scope_denominators
This audits saved report metadata; it does NOT run the sequential engine.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def audit():
    scope = json.loads((HERE / "LABEL_SCOPE_AUDIT_30D.json").read_text())
    dual = json.loads((HERE / "EARLY60_FULL_STACK_DUAL_PERIOD_AUDIT_2026-11-09.json").read_text())
    first = json.loads((HERE / "FIRST_SIGNAL_122_AUDIT_2026-11-08.json").read_text())
    counts = scope["artifact_counts"]
    swings = scope["complete_alternating_swings"]
    assert counts["internal_labels_finalized"] == 122
    assert counts["strict_labels_finalized"] == 76
    assert counts["internal_finalized_by_side"] == {"LOW": 61, "HIGH": 61}
    assert counts["strict_finalized_by_side"] == {"LOW": 38, "HIGH": 38}
    assert swings == {"strict": 75, "internal": 121}
    assert first["teacher_scopes"]["internal"]["complete_swings"] == swings["internal"]
    assert first["teacher_scopes"]["strict"]["complete_swings"] == swings["strict"]
    assert first["candidate_generation"]["exact_internal_coverage"] == "122/122"
    assert first["candidate_generation"]["exact_strict_coverage"] == "76/76"
    octnov = dual["oct_nov_2026"]
    assert octnov["internal_labels"] == 122
    assert octnov["accepted_first"] == octnov["true_first"] + octnov["false_first"]
    for side in ("LOW", "HIGH"):
        assert octnov[side]["true_first"] + octnov[side]["false_first"] >= 0
    assert sum(octnov[s]["true_first"] for s in ("LOW", "HIGH")) == octnov["true_first"]
    assert sum(octnov[s]["false_first"] for s in ("LOW", "HIGH")) == octnov["false_first"]
    # A 120-row next-target sample is independently reported. It does not
    # establish which swing was omitted or why; require per-swing IDs.
    next_target_n = first["true_internal_local_tradeoff"]["sample_with_next_target"]
    reported_n = octnov["episodes"]
    discrepancy = swings["internal"] - reported_n
    out = {
        "status": "UNRECONCILED" if discrepancy else "MATCH",
        "expected_completed_internal_swings": swings["internal"],
        "reported_octnov_episodes": octnov["episodes"],
        "unaccounted_completed_swings": discrepancy,
        "next_target_sample_matches_reported_episodes": next_target_n == reported_n,
        "reconciliation_required": "Compare per-swing IDs and exclusion reasons, including next-target availability and +60m checkpoint; matching counts alone do not prove matching cohorts.",
        "first_signal_report_tradeoff_sample": first["true_internal_local_tradeoff"]["sample_with_next_target"],
        "warning": "Both reports contain 120-row samples, but aggregate counts cannot identify omitted swing IDs or justify the exclusion. Do not relabel 120/121 as complete recall.",
        "candidate_reachability": "122/122 internal; 76/76 strict (separate from signal recall)",
        "real_orders": "OFF",
    }
    return out


if __name__ == "__main__":
    result = audit()
    print(json.dumps(result, indent=2))
    if result["status"] != "MATCH":
        raise SystemExit(2)
