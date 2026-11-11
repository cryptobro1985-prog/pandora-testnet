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
from .causal_sequential_engine import CausalReversalMachine

def compare(bars):
    bars = list(bars)
    baseline = audit(bars)
    # audit() intentionally instantiates the default machine; independently
    # replay the opt-in research variant on exactly the same bars.
    machine = CausalReversalMachine(reset_anchors_on_flip=False)
    flips = []
    for bar in bars:
        flips.extend(s for s in machine.on_bar(bar) if s.core_flip)
    timestamps = [s.ts_ms for s in flips]
    gaps = [(b-a)/60000 for a,b in zip(timestamps,timestamps[1:])]
    return {
        "orders": "OFF",
        "bars": len(bars),
        "baseline": baseline,
        "retained_anchor": {
            "total_core_flips": len(flips),
            "flips_within_5m_of_previous": sum(g <= 5 for g in gaps),
            "adjacent_flip_pairs_within_5m_fraction": sum(g <= 5 for g in gaps)/len(gaps) if gaps else None,
            "core_side_alternation_violations": sum(a.side == b.side for a,b in zip(flips,flips[1:])),
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
