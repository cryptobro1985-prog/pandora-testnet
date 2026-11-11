"""Compare baseline and retained-anchor churn on identical completed M1 bars.

This is label-blind research, NOT OOS precision or a trading deployment.
Usage:
 python -m research.hype_false_local_entry.compare_anchor_reset_modes --base-dir /path/to/local116-HYPE --out /tmp/anchor_modes.json
"""
import argparse
import json
from pathlib import Path
from .audit_dense_coverage import read_jsonl
from .audit_flip_churn import audit

def compare(bars):
    bars = list(bars)
    baseline = audit(bars)
    retained = audit(bars, reset_anchors_on_flip=False)
    return {
        "orders": "OFF",
        "bars": len(bars),
        "baseline": baseline,
        "retained_anchor": retained,
        "delta_retained_minus_baseline": {
            key: retained[key] - baseline[key]
            for key in (
                "total_core_flips",
                "flips_within_5m_of_previous",
                "flips_within_15m_of_previous",
                "flips_within_60m_of_previous",
                "max_flips_per_utc_hour",
                "utc_hours_with_at_least_5_flips",
                "core_side_alternation_violations",
            )
        },
        "warning": "Label-blind churn comparison only; lower flips does not imply better recall, precision or PnL. Evaluate both modes on complete 122 internal/76 strict labels and untouched forward OOS before selection."
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = compare(read_jsonl(args.base_dir / "compact_1m.jsonl.gz"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
