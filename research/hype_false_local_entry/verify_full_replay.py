"""Validate full-scope first-signal replay and export a per-swing reconciliation ledger.

Usage:
 python -m research.hype_false_local_entry.verify_full_replay --input /tmp/hype_first_flip.json --out /tmp/hype_swing_ledger.json

Read-only validation; never sends orders. No metric can silently use 120/121.
"""
import argparse
import json
from pathlib import Path

EXPECTED = {"internal": (122, 121), "strict": (76, 75)}


def verify(payload):
    if payload.get("orders") != "OFF":
        raise ValueError("orders must be OFF")
    if payload.get("core_flip_policy") != "HARD_CONFIRMED_OR_ULTRA_CONFIRMED_ONLY":
        raise ValueError("unsafe flip policy")
    output = {"status": "FULL_SCOPE_VERIFIED", "orders": "OFF", "scopes": {}}
    for scope, (nlocals, nswings) in EXPECTED.items():
        coverage = payload["candidate_generation"][scope]
        scores = payload["first_signal"][scope]
        if (coverage["finalized"], coverage["covered"], coverage["missed"]) != (nlocals, nlocals, 0):
            raise ValueError(f"{scope}: candidate reachability incomplete")
        if scores["finalized_locals"] != nlocals or scores["complete_swings"] != nswings:
            raise ValueError(f"{scope}: wrong label/swing denominators")
        rows = scores["matched"]
        if len(rows) != nlocals:
            raise ValueError(f"{scope}: missing per-local rows")
        ids = [r["label_id"] for r in rows]
        if any(x is None for x in ids) or len(set(ids)) != len(ids):
            raise ValueError(f"{scope}: missing or duplicate label IDs")
        completed = rows[:-1]
        hits = sum(bool(r["detected"]) for r in completed)
        wrong = sum(bool(r["first_signal_wrong_side"]) for r in completed)
        if hits != scores["completed_swing_true_first"] or wrong != scores["completed_swing_wrong_first"]:
            raise ValueError(f"{scope}: first-signal counts disagree with ledger")
        if nswings - hits != scores["completed_swing_missed"]:
            raise ValueError(f"{scope}: missed swing count disagrees")
        if scores["total_core_flips"] - hits != scores["completed_swing_false_first"]:
            raise ValueError(f"{scope}: false flip count disagrees")
        if any(r.get("stage") not in ("HARD_CONFIRMED", "ULTRA_CONFIRMED")
               for r in rows if r["first_signal_present"]):
            raise ValueError(f"{scope}: forbidden core flip stage")
        output["scopes"][scope] = {
            "finalized_locals": nlocals,
            "completed_swings": nswings,
            "candidate_recall": coverage["recall"],
            "true_first": hits,
            "wrong_first": wrong,
            "missed": nswings - hits,
            "precision": scores["completed_swing_first_signal_precision"],
            "recall": scores["completed_swing_recall"],
            "ledger": [
                {"swing_index": i, "from_label_id": row["label_id"],
                 "to_label_id": rows[i + 1]["label_id"],
                 "side": row["side"], "detected": row["detected"],
                 "wrong_first": row["first_signal_wrong_side"],
                 "entry_distance_bps": row.get("entry_distance_bps"),
                 "adverse_extension_bps": row.get("adverse_extension_bps"),
                 "remaining_swing_fraction": row.get("remaining_swing_fraction")}
                for i, row in enumerate(completed)
            ],
            "terminal_excluded": rows[-1]["label_id"],
        }
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = verify(json.loads(args.input.read_text()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: {s: {m: v for m, v in data.items() if m != "ledger"}
                            for s, data in result["scopes"].items()} if k == "scopes" else val
                      for k, val in result.items()}, indent=2))


if __name__ == "__main__":
    main()
