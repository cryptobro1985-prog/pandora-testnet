"""Label-blind completed-M1 sequential replay, followed by offline teacher scoring.

Run:
 python -m research.hype_false_local_entry.replay_dense_first_signal \
   --base-dir /path/to/local116-HYPE --out /tmp/hype_first_flip.json

Never executes orders. HARD/ULTRA only may flip core.
"""
import argparse
import gzip
import json
from pathlib import Path

from .causal_sequential_engine import CausalReversalMachine
from .audit_dense_coverage import read_jsonl, evaluate
from .dense_causal_reachability import dense_completed_m1_candidates
from .first_flip_path_audit import score_first_flips


def replay(bars, labels, max_lag_ms=3600000):
    """Produce causal flips before reading teacher labels for postfactum scoring."""
    machine = CausalReversalMachine()
    emitted = []
    for bar in bars:
        emitted.extend(machine.on_bar(bar))
    flips = [s for s in emitted if s.core_flip and
             s.stage in ("HARD_CONFIRMED", "ULTRA_CONFIRMED")]
    return score_first_flips(bars, labels, flips, max_lag_ms=max_lag_ms)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--max-lag-ms", type=int, default=3600000)
    p.add_argument("--anchor-mode", choices=("reset", "retain"), default="reset")
    p.add_argument("--scope", choices=("both", "internal", "strict"), default="both")
    p.add_argument("--expected-total", type=int)
    p.add_argument("--expected-low", type=int)
    p.add_argument("--expected-high", type=int)
    p.add_argument("--expected-swings", type=int)
    args = p.parse_args()
    with gzip.open(args.base_dir / "labels.json.gz", "rt") as f:
        labels = json.load(f)
    bars = list(read_jsonl(args.base_dir / "compact_1m.jsonl.gz"))
    candidates = list(dense_completed_m1_candidates(bars))
    selected_scopes = ("internal", "strict") if args.scope == "both" else (args.scope,)
    scopes = {
        scope: sorted((x for x in labels.get(scope, []) if x.get("reference_finalized")),
                      key=lambda x: int(x["extreme_interval_start_ms"]))
        for scope in selected_scopes
    }
    # Fail closed on truncated or mismatched teacher exports. Defaults preserve
    # the canonical Oct-Nov contract; cross-period callers must pass the exact
    # expected denominator for their selected scope.
    expected = {"internal": (122, 61, 61, 121), "strict": (76, 38, 38, 75)}
    if args.scope != "both":
        supplied = (args.expected_total, args.expected_low, args.expected_high, args.expected_swings)
        if any(v is None for v in supplied):
            raise ValueError("single-scope replay requires all --expected-* counts")
        expected = {args.scope: supplied}
    for scope, (total, lows, highs, swings) in expected.items():
        rows = scopes[scope]
        side_counts = {side: sum(x.get("side", x.get("type")) == side for x in rows)
                       for side in ("LOW", "HIGH")}
        if len(rows) != total or side_counts != {"LOW": lows, "HIGH": highs}:
            raise ValueError(
                f"{scope} incomplete teacher scope: finalized={len(rows)}, "
                f"sides={side_counts}; expected {total}, LOW={lows}, HIGH={highs}"
            )
        if len(rows) - 1 != swings:
            raise ValueError(f"{scope} swing denominator mismatch")
        if any(a["side"] == b["side"] or
               int(a["extreme_interval_start_ms"]) >= int(b["extreme_interval_start_ms"])
               for a, b in zip(rows, rows[1:])):
            raise ValueError(f"{scope} teacher turns are not strictly alternating")
    # Require full causal candidate reachability before reporting full-scope metrics.
    # This is NOT a claim that the detector recognizes every local.
    coverage = {scope: evaluate(candidates, rows) for scope, rows in scopes.items()}
    for scope, report in coverage.items():
        if report['covered'] != report['finalized'] or report['missed']:
            raise ValueError(
                f"{scope} incomplete candidate reachability: "
                f"{report['covered']}/{report['finalized']}; "
                f"missing={report['missing_label_ids']}"
            )
    # Diagnostic exact-minute audit: the permissive +/-60s, 1bp match can
    # overstate reachability. Report exact candle/price matching separately.
    exact_coverage = {scope: evaluate(candidates, rows, tolerance_ms=0,
                                      price_tolerance_bps=0.000001)
                      for scope, rows in scopes.items()}
    # Exact-minute reachability is a mandatory gate, not a cosmetic diagnostic.
    # A nearby candle within +/-60 seconds or 1bp must never substitute for
    # the teacher's actual extremum when claiming full 122/76 coverage.
    for scope, report in exact_coverage.items():
        if report["covered"] != report["finalized"] or report["missed"]:
            raise ValueError(
                f"{scope} exact-minute candidate reachability incomplete: "
                f"{report['covered']}/{report['finalized']}; "
                f"missing={report['missing_label_ids']}"
            )
    # Generate one shared causal stream; NEVER select signals using labels.
    machine = CausalReversalMachine(reset_anchors_on_flip=(args.anchor_mode == "reset"))
    emitted = []
    for bar in bars:
        emitted.extend(machine.on_bar(bar))
    flips = [s for s in emitted if s.core_flip and
             s.stage in ("HARD_CONFIRMED", "ULTRA_CONFIRMED")]
    result = {
        "anchor_mode": args.anchor_mode,
        "status": "offline_historical_diagnostic_not_untouched_oos",
        "orders": "OFF",
        "core_flip_policy": "HARD_CONFIRMED_OR_ULTRA_CONFIRMED_ONLY",
        "candidate_generation": coverage,
        "exact_minute_candidate_generation": exact_coverage,
        "first_signal": {
            scope: score_first_flips(bars, scope_labels, flips,
                                     max_lag_ms=args.max_lag_ms)
            for scope, scope_labels in scopes.items()
        },
        "caveats": [
            "Candidate recall is separate from detector recall and precision.",
            "Labels used only after causal signals emitted.",
            "The same signal stream is scored against internal and strict contracts separately.",
            "M1 adverse excursion is an OHLC bound, not intrabar execution.",
            "Untouched OOS requires a separate unseen chronological period.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    summary = {
        "status": result["status"],
        "orders": result["orders"],
        "candidate_generation": {
            k: {m: v[m] for m in ("finalized", "covered", "missed", "recall")}
            for k, v in result["candidate_generation"].items()
        },
        "first_signal": {
            k: {m: v[m] for m in (
                "finalized_locals", "complete_swings", "detected_locals",
                "missed_locals", "missed_local_rate", "no_signal_locals",
                "wrong_first_locals", "direction_precision_given_first", "total_core_flips",
                "false_first", "first_signal_precision", "median_lag_ms",
                "median_entry_distance_bps", "median_adverse_extension_bps",
                "median_remaining_swing_fraction", "completed_swing_true_first",
                "completed_swing_missed", "completed_swing_missed_rate",
                "completed_swing_recall", "completed_swing_wrong_first",
                "completed_swing_no_signal", "completed_swing_first_present",
                "completed_swing_direction_precision_given_first",
                "completed_swing_false_first", "completed_swing_first_signal_precision",
                "completed_swing_median_lag_ms",
                "completed_swing_median_entry_distance_bps",
                "completed_swing_median_adverse_extension_bps",
                "completed_swing_median_remaining_swing_fraction")}
            for k, v in result["first_signal"].items()
        },
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
