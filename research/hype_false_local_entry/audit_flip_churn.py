"""Label-blind churn diagnostics for HARD/ULTRA core flips; no orders.

Run:
 python -m research.hype_false_local_entry.audit_flip_churn \
   --base-dir /path/to/local116-HYPE --out /tmp/hype_flip_churn.json

This tool measures signal noise, not profitability or OOS precision.
"""
import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import median

from .audit_dense_coverage import read_jsonl
from .causal_sequential_engine import CausalReversalMachine


def audit(bars):
    machine = CausalReversalMachine()
    flips = []
    n_bars = 0
    for bar in bars:
        n_bars += 1
        flips.extend(s for s in machine.on_bar(bar)
                     if s.core_flip and s.stage in ("HARD_CONFIRMED", "ULTRA_CONFIRMED"))
    gaps = [(b.ts_ms - a.ts_ms) / 60000 for a, b in zip(flips, flips[1:])]
    by_day = Counter(str(s.ts_ms // 86400000) for s in flips)
    return {
        "orders": "OFF",
        "signal_generation": "completed_M1_label_blind",
        "bars": n_bars,
        "total_core_flips": len(flips),
        "core_flips_by_stage": dict(Counter(s.stage for s in flips)),
        "median_minutes_between_flips": median(gaps) if gaps else None,
        "flips_within_5m_of_previous": sum(g <= 5 for g in gaps),
        "flips_within_15m_of_previous": sum(g <= 15 for g in gaps),
        "flips_within_60m_of_previous": sum(g <= 60 for g in gaps),
        "daily_flip_counts": dict(sorted(by_day.items())),
        "daily_median_flips": median(by_day.values()) if by_day else None,
        "core_side_alternation_violations": sum(a.side == b.side for a, b in zip(flips, flips[1:])),
        "warning": "No labels used; this is a churn diagnostic, not a first-signal precision or untouched OOS estimate.",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    result = audit(read_jsonl(args.base_dir / "compact_1m.jsonl.gz"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
