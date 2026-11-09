#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

PERIODS = [
    {
        "folder": "01_JUL12_AUG07_FULL_MICRO",
        "start": "2026-07-12T17:00:00Z",
        "end": "2026-08-07T00:00:00Z",
        "class": "full_micro_historical",
        "known_causal_inputs": 83,
        "missing_input_ids": [111, 112, 113],
        "notes": "Trades + historical L50 orderbook + liquidations + OI + mark/ticker. Some liquidation hours are absent and explicitly listed in the source manifest.",
    },
    {
        "folder": "02_AUG08_SEP01",
        "start": "2026-08-08T00:00:00Z",
        "end": "2026-09-01T00:00:00Z",
        "class": "compact_trade_structural",
        "notes": "Bybit executed-trade history compacted into causal structure/flow; unavailable historical streams are not fabricated.",
    },
    {
        "folder": "03_SEP01_OCT01",
        "start": "2026-09-01T00:00:00Z",
        "end": "2026-10-01T00:00:00Z",
        "class": "compact_trade_structural_plus_audits",
        "notes": "Compact causal replay, labels and frozen September audit outputs.",
    },
    {
        "folder": "04_OCT04_NOV03",
        "start": "2026-10-04T00:00:00Z",
        "end": "2026-11-03T00:00:00Z",
        "class": "compact_trade_structural_plus_snapshots",
        "notes": "Compact causal replay, candidate snapshots, labels and availability metadata.",
    },
]

README = """# HYPE historical master — Jul 12 to Nov 3, 2026

This folder preserves every currently available HYPE historical block used by Local research, regardless of feature completeness.

Periods:
- Jul 12 17:00 UTC → Aug 7 00:00 UTC: richest full-micro historical block.
- Aug 8 00:00 UTC → Sep 1 00:00 UTC.
- Sep 1 00:00 UTC → Oct 1 00:00 UTC.
- Oct 4 00:00 UTC → Nov 3 00:00 UTC.

Known calendar gaps: Aug 7→8 and Oct 1→4. Missing internal streams remain explicitly missing; nothing is fabricated.

The canonical research contract contains 116 points: 86 causal/quality inputs, 2 metadata points and 28 teacher/evaluation points. Teacher/eval IDs 83–110 must never enter the predictive feature set.

Local detection must use market structure as causal context: previous confirmed H1 High/Low, active swing direction, same-side extreme replacement, rolling 60m/6h/24h position, swing maturity and retracement; then combine that with flow, price response, orderbook, OI and liquidations where those streams exist.

MASTER_INDEX.json contains exact file inventory, SHA-256 checksums, period boundaries and data-quality notes.
"""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    root = args.root
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name not in {"MASTER_INDEX.json", "README.md"}:
            files.append({
                "path": str(p.relative_to(root)),
                "bytes": p.stat().st_size,
                "sha256": sha256(p),
            })
    index = {
        "dataset": "HYPE_HISTORY_20260712_20261103_MASTER",
        "symbol": "HYPEUSDT",
        "coverage": {
            "start": "2026-07-12T17:00:00Z",
            "end": "2026-11-03T00:00:00Z",
            "known_calendar_gaps": [
                "2026-08-07T00:00:00Z..2026-08-08T00:00:00Z",
                "2026-10-01T00:00:00Z..2026-10-04T00:00:00Z",
            ],
        },
        "feature_contract": {
            "points_total": 116,
            "causal_or_quality_inputs": 86,
            "metadata": 2,
            "target_eval": 28,
            "anti_leakage": "IDs 83..110 are teacher/evaluation only and never predictors.",
        },
        "principle": "Preserve everything that exists; keep missing streams missing; never impute unavailable history.",
        "periods": PERIODS,
        "files": files,
    }
    (root / "MASTER_INDEX.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "README.md").write_text(README, encoding="utf-8")
    print(json.dumps({"files": len(files), "bytes": sum(x["bytes"] for x in files)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
