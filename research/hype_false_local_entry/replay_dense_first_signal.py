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
    args = p.parse_args()
    with gzip.open(args.base_dir / "labels.json.gz", "rt") as f:
        labels = json.load(f)
    bars = list(read_jsonl(args.base_dir / "compact_1m.jsonl.gz"))
    candidates = list(dense_completed_m1_candidates(bars))
    scopes = {
        scope: sorted((x for x in labels[scope] if x.get("reference_finalized")),
                      key=lambda x: int(x["extreme_interval_start_ms"]))
        for scope in ("internal", "strict")
    }
    # Fail closed on truncated or mismatched teacher exports. A complete
    # historical replay must retain every finalized turn, not just strict.
    expected = {"internal": (122, 61, 61, 121), "strict": (76, 38, 38, 75)}
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
    # Generate one shared causal stream; NEVER select signals using labels.
    machine = CausalReversalMachine()
    emitted = []
    for bar in bars:
        emitted.extend(machine.on_bar(bar))
    flips = [s for s in emitted if s.core_flip and
             s.stage in ("HARD_CONFIRMED", "ULTRA_CONFIRMED")]
    result = {
        "status": "offline_historical_diagnostic_not_untouched_oos",
        "orders": "OFF",
        "core_flip_policy": "HARD_CONFIRMED_OR_ULTRA_CONFIRMED_ONLY",
        "candidate_generation": {
            scope: evaluate(candidates, scope_labels)
            for scope, scope_labels in scopes.items()
        },
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
                "missed_locals", "missed_local_rate", "total_core_flips",
                "false_first", "first_signal_precision", "median_lag_ms",
                "median_entry_distance_bps", "median_adverse_extension_bps",
                "median_remaining_swing_fraction", "completed_swing_true_first",
                "completed_swing_missed", "completed_swing_missed_rate",
                "completed_swing_recall", "completed_swing_wrong_first",
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
