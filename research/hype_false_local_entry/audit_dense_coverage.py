"""Audit dense completed-M1 candidate reachability against BOTH finalized label scopes.

Usage:
 python -m research.hype_false_local_entry.audit_dense_coverage --base-dir /path/local116-HYPE --out /tmp/dense_coverage.json

This is a LABEL-BLIND generator followed by an OFFLINE label audit.
Reachability is not first-signal detection, precision, or profitable capture.
"""
import argparse
import gzip
import json
from bisect import bisect_left
from pathlib import Path

from .dense_causal_reachability import dense_completed_m1_candidates


def read_jsonl(path):
    with gzip.open(path, "rt") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def evaluate(events, labels, tolerance_ms=60000, price_tolerance_bps=1.0):
    by_side = {"LOW": [], "HIGH": []}
    for event in events:
        by_side[event["side"]].append(event)
    for side in by_side:
        by_side[side].sort(key=lambda e: e["extreme_ts_ms"])
    if tolerance_ms < 0 or price_tolerance_bps < 0:
        raise ValueError("matching tolerances must be nonnegative")
    results = []
    for label in labels:
        side = label["side"]
        start = int(label["extreme_interval_start_ms"])
        end = int(label.get("extreme_interval_end_ms", start + 60000))
        price = float(label["extreme_price"])
        matches = [
            e for e in by_side[side]
            if start - tolerance_ms <= e["extreme_ts_ms"] <= end + tolerance_ms
            and abs(e["extreme_price"] / price - 1) * 10000 <= price_tolerance_bps
            and e["signal_ts_ms"] >= e["extreme_ts_ms"]
            # Exact-minute mode must identify the SAME completed candle, not
            # a neighboring candle at the inclusive teacher interval end.
            and (tolerance_ms != 0 or
                 e["signal_ts_ms"] - int(e.get("interval_ms", 60000)) == start)
        ]
        earliest = min(matches, key=lambda e: e["signal_ts_ms"]) if matches else None
        results.append({
            "label_id": label["label_id"], "side": side,
            "matched": earliest is not None,
            "first_available_ts_ms": earliest["signal_ts_ms"] if earliest else None,
            "availability_lag_from_interval_start_ms": earliest["signal_ts_ms"] - start if earliest else None,
        })
    n = len(results)
    covered = sum(x["matched"] for x in results)
    return {"finalized": n, "covered": covered, "missed": n-covered,
            "recall": covered/n if n else None,
            "missing_label_ids": [x["label_id"] for x in results if not x["matched"]],
            "per_label": results}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--tolerance-ms", type=int, default=60000)
    p.add_argument("--price-tolerance-bps", type=float, default=1.0)
    args = p.parse_args()
    with gzip.open(args.base_dir / "labels.json.gz", "rt") as f:
        labels = json.load(f)
    events = list(dense_completed_m1_candidates(read_jsonl(args.base_dir / "compact_1m.jsonl.gz")))
    output = {
        "status": "candidate_reachability_only",
        "source": "completed_M1_only",
        "candidate_events": len(events),
        "tolerance_ms": args.tolerance_ms,
        "price_tolerance_bps": args.price_tolerance_bps,
        "internal": evaluate(events, [x for x in labels["internal"] if x.get("reference_finalized")], args.tolerance_ms, args.price_tolerance_bps),
        "strict": evaluate(events, [x for x in labels["strict"] if x.get("reference_finalized")], args.tolerance_ms, args.price_tolerance_bps),
        "warning": "This report does NOT compute first-signal precision, false-first, state-machine coverage, or OOS capture. No orders.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({k: {z:v for z,v in val.items() if z!="per_label"} if isinstance(val,dict) else val for k,val in output.items()}, indent=2))


if __name__ == "__main__":
    main()
