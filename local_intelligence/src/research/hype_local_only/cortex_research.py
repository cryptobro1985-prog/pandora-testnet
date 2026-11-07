"""Persist numerical hypotheses from repaired causal history; reserve final OOS."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import time
from .cortex_meta import ResearchConfig, atomic_json, discover, load_memory, save_memory, validate_forward_proposals

def date_ms(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp() * 1000)

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", type=Path, required=True)
    parser.add_argument("--memory-out", type=Path, required=True)
    parser.add_argument("--report-out", type=Path, required=True)
    parser.add_argument("--causal-data", action="store_true", required=True,
                        help="Assert repaired completed-bar inputs with label_mature_ms; original archive inputs are forbidden.")
    parser.add_argument("--train-end", default="2026-10-23")
    parser.add_argument("--oos-start", default="2026-10-27")
    parser.add_argument("--embargo-hours", type=int, default=3)
    parser.add_argument("--proposals", type=Path, help="Optional daemon proposal ledger; only postproposal matured rows may validate it.")
    parser.add_argument("--forward-snapshots", type=Path, help="Separate causal future snapshots, beyond every historical snapshot; required with --proposals.")
    args = parser.parse_args()
    if bool(args.proposals) != bool(args.forward_snapshots):
        parser.error("--proposals and --forward-snapshots must be supplied together")
    digest = hashlib.sha256(args.snapshots.read_bytes()).hexdigest()
    with gzip.open(args.snapshots, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    result = discover(rows, ResearchConfig(date_ms(args.train_end), date_ms(args.oos_start),
                                          args.embargo_hours * 3_600_000), digest)
    result["provenance"] = {"source_file": args.snapshots.name,
                            "causal_data_asserted_by_operator": args.causal_data,
                            "archive_partial_bar_features_permitted": False}
    if args.proposals:
        proposals = load_memory(args.proposals).get("hypotheses", [])
        with gzip.open(args.forward_snapshots, "rt", encoding="utf-8") as stream:
            forward = [json.loads(line) for line in stream if line.strip()]
        historical_end = max((int(r.get("snapshot_ts_ms", 0)) for r in rows), default=0)
        result["submitted_proposal_validation"] = validate_forward_proposals(
            forward, proposals, int(time.time() * 1000), minimum_ts_ms=historical_end + 1)
        result["provenance"]["forward_sha256"] = hashlib.sha256(args.forward_snapshots.read_bytes()).hexdigest()
    save_memory(args.memory_out, result)
    counts = dict(Counter(h["status"] for h in result["hypotheses"]))
    report = {"version": result["version"], "source_sha256": digest,
              "splits": result["splits"], "method": result["method"],
              "hypothesis_status_counts": counts, "hypotheses": result["hypotheses"],
              "incremental_quantum_cortex_oos_gain": None,
              "production_promotions": 0, "real_orders": False}
    if args.proposals:
        report["submitted_proposal_validation"] = result["submitted_proposal_validation"]
    atomic_json(args.report_out, report)
    print(json.dumps({"hypotheses": len(result["hypotheses"]), "states": counts,
                      "train_rows": result["splits"]["train_rows"],
                      "validation_rows": result["splits"]["validation_rows"],
                      "oos_reserved_rows": result["splits"]["oos_reserved_rows"],
                      "production_promotions": 0}, sort_keys=True))

if __name__ == "__main__":
    main()
