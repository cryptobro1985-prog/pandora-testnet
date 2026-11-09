#!/usr/bin/env python3
"""Rank frozen HYPE Local strategies from forward first-signal evidence only.

This module never changes model thresholds and never authorizes real orders.
It simply compares already-produced forward audit JSON files using the same
first-signal metrics. Historical/development results are deliberately excluded.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CANDIDATES = [
    ("TACTICAL_60S", "TACTICAL_60S_FORWARD_STATUS.json", 60),
    ("TACTICAL_180S", "TACTICAL_180S_FORWARD_STATUS.json", 180),
    ("TACTICAL_300S", "TACTICAL_300S_FORWARD_STATUS.json", 300),
    ("HARD120", "HARD120_FORWARD_STATUS.json", 7200),
    ("HARD120_HIGH_FLOW", "HARD120_HIGH_FLOW_SHADOW_FORWARD_STATUS.json", 7200),
    ("HARD120_PLUS_HIGH_FLOW", "HARD120_PLUS_HIGH_FLOW_FORWARD_STATUS.json", 7200),
    ("HARD120_HIGH_FLOW_V2", "HARD120_HIGH_FLOW_V2_FORWARD_STATUS.json", 7200),
    ("HARD120_PLUS_HIGH_FLOW_V2", "HARD120_PLUS_HIGH_FLOW_V2_FORWARD_STATUS.json", 7200),
    ("HARD120_HIGH_FLOW_V3", "HARD120_HIGH_FLOW_V3_FORWARD_STATUS.json", 7200),
    ("HARD120_PLUS_HIGH_FLOW_V3", "HARD120_PLUS_HIGH_FLOW_V3_FORWARD_STATUS.json", 7200),
    ("EARLY60_STRONG_REVERSAL", "EARLY60_STRONG_REVERSAL_FORWARD_STATUS.json", 3600),
    ("HIGH60_VETO", "HIGH60_VETO_FORWARD_STATUS.json", 3600),
    ("HARD120_PERSISTENCE", "HARD120_PERSISTENCE_FORWARD_STATUS.json", 7200),
]

def _load(path: Path) -> dict:
    try:
        x=json.loads(path.read_text(encoding="utf-8"))
        return x if isinstance(x,dict) else {}
    except Exception:
        return {}

def build_scoreboard(checkpoint_dir: Path) -> dict:
    rows=[]
    for name,filename,latency_s in CANDIDATES:
        path=checkpoint_dir/filename
        if not path.exists():
            continue
        doc=_load(path)
        m=doc.get("metrics") or {}
        gate=doc.get("promotion_gate") or {}
        episodes=int(m.get("episodes") or 0)
        accepted=int(m.get("accepted_first") or 0)
        true=int(m.get("true_first") or 0)
        false=int(m.get("false_first") or 0)
        precision=float(m.get("precision") or 0.0)
        recall=float(m.get("recall") or 0.0)
        passed=bool(gate.get("passed"))
        enough=(episodes>=20 and true>=10)
        rows.append({
            "strategy":name,
            "file":filename,
            "signal_latency_s":latency_s,
            "status":doc.get("status"),
            "episodes":episodes,
            "accepted_first":accepted,
            "true_first":true,
            "false_first":false,
            "precision":precision,
            "recall":recall,
            "promotion_gate_passed":passed,
            "minimum_evidence_present":enough,
            "research_only":True,
            "real_orders":False,
        })

    # Never let a tiny 1/1 sample beat a mature strategy merely because it is 100%.
    # First compare strategies that pass the declared forward gate, then those with
    # minimum evidence, then precision/recall; latency is a final tie-break only.
    rows.sort(key=lambda r:(
        int(r["promotion_gate_passed"]),
        int(r["minimum_evidence_present"]),
        r["precision"],
        r["recall"],
        r["true_first"],
        -r["false_first"],
        -r["signal_latency_s"],
    ), reverse=True)

    for i,row in enumerate(rows,1):
        row["rank"]=i
    winner=rows[0] if rows else None
    return {
        "status":"FORWARD_STRATEGY_RANKING",
        "selection_basis":"forward first-signal evidence only; no threshold retuning",
        "research_only":True,
        "real_orders":False,
        "winner":winner,
        "ranking":rows,
        "warning":"A rank is not a future guarantee. Tiny samples are explicitly prevented from outranking mature evidence.",
    }

def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--checkpoint-dir",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    out=build_scoreboard(args.checkpoint_dir)
    args.output.write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    w=out.get("winner") or {}
    print("STRATEGY_SCOREBOARD="+json.dumps({
        "winner":w.get("strategy"),"precision":w.get("precision"),
        "recall":w.get("recall"),"episodes":w.get("episodes"),
        "gate":w.get("promotion_gate_passed"),
    },separators=(",",":"),ensure_ascii=False))

if __name__=="__main__":
    main()
