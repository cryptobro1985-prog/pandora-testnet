"""Chronological first-signal evaluation of the completed-M1 reversal machine.

Offline labels are used ONLY for scoring after all causal signals are emitted.
No trading orders. First HARD/ULTRA flip is evaluated, not every checkpoint.
"""
import argparse
import gzip
import json
from pathlib import Path
from .causal_sequential_engine import CausalReversalMachine
from .audit_dense_coverage import read_jsonl, evaluate
from .dense_causal_reachability import dense_completed_m1_candidates


def replay(bars, labels, max_lag_ms=3600000):
    machine = CausalReversalMachine()
    emitted = []
    for bar in bars:
        emitted.extend(machine.on_bar(bar))
    flips = [s for s in emitted if s.core_flip and s.stage in ("HARD_CONFIRMED", "ULTRA_CONFIRMED")]
    # Match first core flip in each local->next-local interval. No reuse.
    labels = sorted(labels, key=lambda x: int(x["extreme_interval_start_ms"]))
    scored = []
    used = set()
    for i, label in enumerate(labels):
        start = int(label["extreme_interval_start_ms"])
        stop = int(labels[i+1]["extreme_interval_start_ms"]) if i+1 < len(labels) else start+max_lag_ms
        eligible = [(j, s) for j,s in enumerate(flips)
                    if j not in used and s.side == label["side"]
                    and start <= s.ts_ms < min(stop, start+max_lag_ms)]
        if eligible:
            j, sig = eligible[0]
            used.add(j)
            scored.append(dict(label_id=label["label_id"], side=label["side"],
                               detected=True, signal_ts_ms=sig.ts_ms,
                               lag_ms=sig.ts_ms-start, stage=sig.stage,
                               entry_price=sig.close, extreme_price=label["extreme_price"]))
        else:
            scored.append(dict(label_id=label["label_id"], side=label["side"], detected=False))
    false = [dict(ts_ms=s.ts_ms, side=s.side, stage=s.stage, price=s.close)
             for j,s in enumerate(flips) if j not in used]
    hits = sum(x["detected"] for x in scored)
    return dict(finalized=len(labels), detected=hits, missed=len(labels)-hits,
                missed_local_rate=(len(labels)-hits)/len(labels) if labels else None,
                first_core_flips=len(flips), false_first=len(false),
                first_signal_precision=hits/len(flips) if flips else None,
                labels=scored, false_signals=false,
                caveat="Time-window attribution, not validated causal truth. Full swing capture/adverse excursion require minute path alignment.")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args=p.parse_args()
    with gzip.open(args.base_dir/"labels.json.gz","rt") as f:
        labels=json.load(f)
    bars=list(read_jsonl(args.base_dir/"compact_1m.jsonl.gz"))
    candidates=list(dense_completed_m1_candidates(bars))
    out={"status":"offline_diagnostic_not_oos","orders":"OFF",
         "candidate_generation":{
             "internal":evaluate(candidates,[x for x in labels["internal"] if x.get("reference_finalized")]),
             "strict":evaluate(candidates,[x for x in labels["strict"] if x.get("reference_finalized")])},
         "first_signal":{
             scope:replay(bars,[x for x in labels[scope] if x.get("reference_finalized")])
             for scope in ("internal","strict")}}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(out,indent=2)+"\n")
    print(json.dumps({k:v for k,v in out.items() if k!="first_signal"},indent=2))


if __name__=="__main__":
    main()
