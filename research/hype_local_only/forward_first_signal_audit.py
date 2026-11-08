#!/usr/bin/env python3
"""Forward first-signal audit for the broad INTERNAL L3/K1 learner.

Uses only matured terminal teacher labels already written by live_daemon.
No historical threshold search happens here.  This file answers the operational
question: inside each causally completed swing, was the FIRST accepted tactical
signal the true terminal local or a false correction?
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.hype_false_local_entry.first_signal_objective import (
    promotion_gate,
    summarize_first_signals,
    summarize_actionable_first_signals,
)

INTERNAL_TEACHERS={"INTERNAL_L3_K1","H1_L3_K1_INTERNAL"}


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out=[]
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row=json.loads(line)
        except Exception:
            continue
        if isinstance(row,dict):
            out.append(row)
    return out


def terminal_internal_labels(rows: list[dict]) -> list[dict]:
    """Deduplicate stage rows and defensively collapse same-side terminals."""
    by_candidate={}
    for r in rows:
        if r.get("teacher") not in INTERNAL_TEACHERS or r.get("label") is not True:
            continue
        if r.get("extreme_ts_ms") is None or r.get("extreme_price") is None:
            # Old ledgers lack the fields needed for a causal forward audit.
            continue
        cid=str(r.get("candidate_id") or "")
        if not cid:
            continue
        by_candidate.setdefault(cid,r)

    raw=[]
    for cid,r in sorted(by_candidate.items(),key=lambda kv:int(kv[1]["extreme_ts_ms"])):
        item={
            "candidate_id":cid,
            "side":str(r["side"]),
            "extreme_price":float(r["extreme_price"]),
            "extreme_interval_start_ms":int(r["extreme_ts_ms"]),
            "extreme_interval_end_ms":int(r["extreme_ts_ms"])+60_000,
            "teacher_finalized_ts_ms":int(r.get("teacher_finalized_ts_ms") or r.get("ts_ms") or 0),
        }
        if raw and raw[-1]["side"]==item["side"]:
            better=(item["extreme_price"]>raw[-1]["extreme_price"]
                    if item["side"]=="HIGH"
                    else item["extreme_price"]<raw[-1]["extreme_price"])
            if better:
                raw[-1]=item
        else:
            raw.append(item)

    for i,r in enumerate(raw,1):
        r["label_id"]=i
        r["reference_finalized"]=True
    return raw


def internal_signal_records(events: list[dict], labels: list[dict],
                            event_name: str="INTERNAL_TACTICAL_SIGNAL") -> list[dict]:
    truth={str(x["candidate_id"]):int(x["label_id"]) for x in labels}
    out=[]
    seen=set()
    for r in events:
        if r.get("event")!=event_name:
            continue
        if r.get("candidate_ts_ms") is None:
            continue
        cid=str(r.get("candidate_id") or "")
        # One candidate can be accepted at several stages.  Keep each stage;
        # summarize_first_signals will choose the earliest signal in the swing.
        key=(cid,int(r.get("stage") or 0),int(r.get("signal_ts_ms") or r.get("ts_ms") or 0))
        if key in seen:
            continue
        seen.add(key)
        lid=truth.get(cid)
        out.append({
            "candidate_id":cid,
            "side":str(r.get("side")),
            "candidate_ts_ms":int(r["candidate_ts_ms"]),
            "signal_ts_ms":int(r.get("signal_ts_ms") or r.get("ts_ms") or r["candidate_ts_ms"]),
            "accepted":True,
            "internal_true":lid is not None,
            "internal_label_id":lid,
            "stage":int(r.get("stage") or 0),
            "probability":r.get("probability"),
        })
    return out


def audit(labels_path: Path, events_path: Path, *,
          event_name: str="INTERNAL_TACTICAL_SIGNAL",
          actionable: bool=False) -> dict:
    label_rows=read_jsonl(labels_path)
    event_rows=read_jsonl(events_path)
    labels=terminal_internal_labels(label_rows)
    signals=internal_signal_records(event_rows,labels,event_name=event_name)

    if len(labels)<2:
        metrics={
            "episodes":max(0,len(labels)-1),"accepted_first":0,"true_first":0,
            "false_first":0,"no_signal":max(0,len(labels)-1),
            "precision":0.0,"recall":0.0,"false_first_rate":None,
            "median_true_signal_delay_s":None,
            "by_side":{"LOW":{"true_first":0,"false_first":0},
                       "HIGH":{"true_first":0,"false_first":0}},
            "first_signals":[],
        }
    else:
        metrics=(summarize_actionable_first_signals(signals,labels)
                 if actionable else summarize_first_signals(signals,labels))

    gate=promotion_gate(metrics)
    return {
        "status":"FORWARD_GATE_PASS" if gate["passed"] else "ACCUMULATING_FORWARD_EVIDENCE",
        "research_only":True,
        "real_orders":False,
        "teacher":"INTERNAL_L3_K1_TERMINAL_FINALIZED",
        "objective":("FIRST_ACCEPTED_ACTIONABLE_SIGNAL_BEFORE_NEXT_LOCAL"
                     if actionable else "FIRST_ACCEPTED_SIGNAL_PER_COMPLETED_INTERNAL_SWING"),
        "signal_event":event_name,
        "actionable_deadline_enabled":bool(actionable),
        "terminal_labels":len(labels),
        "tactical_signal_rows":len(signals),
        "metrics":metrics,
        "promotion_gate":gate,
        "warning":"A passing gate authorizes paper/forward promotion only; it is not a guarantee of future precision.",
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--labels",type=Path,required=True)
    ap.add_argument("--events",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--event-name",default="INTERNAL_TACTICAL_SIGNAL")
    ap.add_argument("--actionable",action="store_true")
    args=ap.parse_args()
    out=audit(args.labels,args.events,event_name=args.event_name,actionable=args.actionable)
    args.output.write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("FIRST_SIGNAL_FORWARD="+json.dumps({
        "status":out["status"],
        "terminal_labels":out["terminal_labels"],
        "signals":out["tactical_signal_rows"],
        "signal_event":out["signal_event"],
        "actionable":out["actionable_deadline_enabled"],
        "metrics":{k:out["metrics"].get(k) for k in ("episodes","accepted_first","true_first","false_first","precision","recall")},
        "gate":out["promotion_gate"]["passed"],
    },separators=(",",":"),ensure_ascii=False))


if __name__=="__main__":
    main()
