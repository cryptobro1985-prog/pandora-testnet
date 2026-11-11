#!/usr/bin/env python3
"""Strict, reproducible daily audit for the hindsight HYPE tradeable-path oracle.

Evaluation only. No oracle outputs may enter live trading features or signals.
Requires actual executable bid/ask; refuses optimistic mid-price fallback.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from tradeable_path_oracle_v2 import oracle
except ModuleNotFoundError:
    from research.hype_movement_signature.tradeable_path_oracle_v2 import oracle

THRESHOLDS = (0.0025, 0.0035, 0.005, 0.0075, 0.01)


def audit(path, expected_step_seconds=60, max_gap_seconds=300,
          min_coverage=0.95, fee_bps=6, slip_bps=2,
          min_hold_seconds=60, cooldown_seconds=60):
    if expected_step_seconds <= 0 or max_gap_seconds <= 0:
        raise ValueError("invalid sampling or gap settings")
    if not 0 <= min_coverage <= 1:
        raise ValueError("invalid coverage threshold")
    data = Path(path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    days = defaultdict(list)
    with Path(path).open(newline="") as f:
        reader = csv.DictReader(f)
        required = {"timestamp", "price", "executable_bid", "executable_ask"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("strict executable bid/ask columns required")
        for number, row in enumerate(reader, start=2):
            raw = row["timestamp"]
            try:
                t = float(raw)
                if t > 1e11:
                    t /= 1000
            except ValueError:
                t = datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
            if not all(row.get(k) for k in ("price", "executable_bid", "executable_ask")):
                raise ValueError(f"missing executable quote on line {number}")
            mid, bid, ask = (float(row[k]) for k in ("price", "executable_bid", "executable_ask"))
            if not all(map(math.isfinite, (t, mid, bid, ask))) or not 0 < bid <= mid <= ask:
                raise ValueError(f"invalid price/quote on line {number}")
            day = datetime.fromtimestamp(t, timezone.utc).date().isoformat()
            days[day].append((t, mid, bid, ask))
    result = {"source_sha256": sha, "evaluation_only": True,
              "costs": {"fee_bps_per_side": fee_bps, "slip_bps_per_side": slip_bps},
              "days": {}}
    for day, rows in sorted(days.items()):
        rows.sort()
        times = [r[0] for r in rows]
        if any(b <= a for a, b in zip(times, times[1:])):
            raise ValueError(f"duplicate/non-increasing timestamps on {day}")
        # Count coverage against the full UTC day, not merely the observed span.
        expected = round(86400 / expected_step_seconds)
        observed = len(rows)
        coverage = min(1.0, observed / expected)
        gaps = [b-a for a, b in zip(times, times[1:]) if b-a > max_gap_seconds]
        record = {"rows": observed, "expected_rows": expected,
                  "coverage_fraction": coverage, "gaps_over_limit_seconds": gaps,
                  "first_utc": datetime.fromtimestamp(times[0], timezone.utc).isoformat(),
                  "last_utc": datetime.fromtimestamp(times[-1], timezone.utc).isoformat()}
        if coverage < min_coverage or gaps:
            record["status"] = "REJECT_INCOMPLETE_COVERAGE"
            record["thresholds"] = {}
        else:
            record["status"] = "EVALUATION_ONLY"
            record["thresholds"] = {
                str(threshold): oracle(rows, threshold, fee_bps, slip_bps,
                                       max_gap_seconds, min_hold_seconds, cooldown_seconds)
                for threshold in THRESHOLDS
            }
        result["days"][day] = record
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv")
    p.add_argument("--min-coverage", type=float, default=0.95)
    p.add_argument("--expected-step-seconds", type=float, default=60)
    p.add_argument("--max-gap-seconds", type=float, default=300)
    args = p.parse_args()
    print(json.dumps(audit(args.csv, args.expected_step_seconds,
                           args.max_gap_seconds, args.min_coverage), indent=2))


if __name__ == "__main__":
    main()
