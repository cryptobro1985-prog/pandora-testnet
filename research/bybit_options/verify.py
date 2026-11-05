from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

REQUIRED_SIGNAL_KEYS = {
    "ts_ms", "strategy", "action", "symbol", "option_type", "expiry_ms",
    "entry_reference_ask", "score", "paper_only", "greeks", "liquidity", "components",
}


def read_rows(path: Path):
    if not path.exists():
        return
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("directory")
    args = ap.parse_args()
    p = Path(args.directory)
    manifest = json.loads((p / "RUN_MANIFEST.json").read_text())
    summary = json.loads((p / "SUMMARY.json").read_text())
    problems = []
    if not manifest.get("paper_only"):
        problems.append("manifest is not paper-only")
    if manifest.get("allow_naked_short"):
        problems.append("naked short enabled")
    if summary.get("scan_count", 0) <= 0:
        problems.append("no scans")
    candidate_rows = 0
    for batch in read_rows(p / "candidates.jsonl.gz") or []:
        for candidate in batch.get("top", []):
            candidate_rows += 1
            strike = float(candidate.get("strike") or 0)
            underlying = float(candidate.get("underlying") or 0)
            if strike <= 0:
                problems.append(f"invalid candidate strike: {candidate.get('symbol')}")
            if underlying <= 0:
                problems.append(f"invalid candidate underlying: {candidate.get('symbol')}")
    if candidate_rows <= 0:
        problems.append("no option candidates")
    for row in read_rows(p / "signals.jsonl.gz") or []:
        missing = REQUIRED_SIGNAL_KEYS - row.keys()
        if missing:
            problems.append(f"signal missing {sorted(missing)}")
        if row.get("paper_only") is not True:
            problems.append("non-paper signal")
        if row.get("action") != "BUY_OPTION":
            problems.append("unexpected action")
        if row.get("option_type") not in {"CALL", "PUT"}:
            problems.append("unknown option type")
        if not (0.0 <= float(row.get("score", -1)) <= 1.0):
            problems.append("score out of range")
    result = {"ok": not problems, "problems": problems[:50], "summary": summary}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not problems else 2


if __name__ == "__main__":
    raise SystemExit(main())
