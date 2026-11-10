"""Run the same causal dense post-local engine over every preserved strict period.

Research/paper only. Teacher labels are read only for offline scoring and censor
accounting. Signals are generated once from completed M1 bars without labels.
"""
import argparse, gzip, json
from pathlib import Path
from statistics import median

from .audit_dense_coverage import read_jsonl
from .causal_sequential_engine import CausalReversalMachine
from .dense_causal_reachability import dense_completed_m1_candidates
from .first_flip_path_audit import score_first_flips


def label_time(x):
    return int(x["extreme_interval_start_ms"])


def bar_bounds(b):
    interval=int(b.get("interval_ms",60000))
    if b.get("start_ms") is not None:
        start=int(b["start_ms"])
    elif b.get("bar_end_ms") is not None:
        start=int(b["bar_end_ms"])-interval
    else:
        start=int(b["ts_ms"])-interval
    end=int(b.get("bar_end_ms") or (start+interval))
    return start,end


def exact_missing(candidates, labels):
    keys={(x["side"],int(x["extreme_ts_ms"]),round(float(x["extreme_price"]),10)) for x in candidates}
    missing=[]
    for x in labels:
        key=(x["side"],label_time(x),round(float(x["extreme_price"]),10))
        if key not in keys:
            # Fall back to interval containment + exact price because teacher may
            # store interval start while intrabar trade time is unavailable.
            lo=int(x["extreme_interval_start_ms"])
            hi=int(x.get("extreme_interval_end_ms",lo+60000))
            ok=any(c["side"]==x["side"] and lo <= int(c["extreme_ts_ms"]) < hi
                   and abs(float(c["extreme_price"])/float(x["extreme_price"])-1)*10000 <= 1e-6
                   for c in candidates)
            if not ok:
                missing.append(x)
    return missing


def classify_missing(label,bars):
    t=label_time(label)
    first=bar_bounds(bars[0])[0]
    last=bar_bounds(bars[-1])[1]
    if t < first: return "before_first_bar"
    if t >= last: return "after_last_bar"
    covering=[b for b in bars if bar_bounds(b)[0] <= t < bar_bounds(b)[1]]
    if not covering: return "inside_gap"
    return "price_or_timestamp_mismatch"


def segments(labels, missing_ids):
    out=[]; cur=[]
    for x in labels:
        if x.get("label_id") in missing_ids:
            if len(cur)>=2: out.append(cur)
            cur=[]
        else:
            cur.append(x)
    if len(cur)>=2: out.append(cur)
    return out


def med(vals):
    vals=[v for v in vals if v is not None]
    return median(vals) if vals else None


def audit_period(base):
    base=Path(base)
    with gzip.open(base/"labels.json.gz","rt",encoding="utf-8") as f:
        doc=json.load(f)
    labels=sorted([x for x in doc.get("strict",[]) if x.get("reference_finalized")],key=label_time)
    bars=list(read_jsonl(base/"compact_1m.jsonl.gz"))
    candidates=list(dense_completed_m1_candidates(bars))
    missing=exact_missing(candidates,labels)
    missing_ids={x.get("label_id") for x in missing}
    miss=[{"label_id":x.get("label_id"),"side":x["side"],"ts_ms":label_time(x),
           "price":float(x["extreme_price"]),"reason":classify_missing(x,bars)}
          for x in missing]

    m=CausalReversalMachine(); emitted=[]
    for b in bars: emitted.extend(m.on_bar(b))
    flips=[s for s in emitted if s.core_flip and s.stage in ("HARD_CONFIRMED","ULTRA_CONFIRMED")]

    segs=segments(labels,missing_ids)
    scores=[score_first_flips(bars,seg,flips) for seg in segs]
    true_first=sum(s["completed_swing_true_first"] for s in scores)
    wrong=sum(s["completed_swing_wrong_first"] for s in scores)
    swings=sum(s["complete_swings"] for s in scores)
    matched=[r for s in scores for r in s["matched"][:-1] if r.get("detected")]
    result={
        "strict_labels":len(labels),
        "candidate_exact_covered":len(labels)-len(missing),
        "candidate_exact_missing":miss,
        "censored_labels":len(missing),
        "scored_segments":len(segs),
        "complete_scored_swings":swings,
        "true_first":true_first,
        "wrong_first":wrong,
        "no_correct_first":swings-true_first,
        "correct_first_rate":true_first/swings if swings else None,
        "wrong_first_rate":wrong/swings if swings else None,
        "median_lag_ms":med([r.get("lag_ms") for r in matched]),
        "median_entry_distance_bps":med([r.get("entry_distance_bps") for r in matched]),
        "median_remaining_swing_fraction":med([r.get("remaining_swing_fraction") for r in matched]),
        "median_adverse_extension_bps":med([r.get("adverse_extension_bps") for r in matched]),
        "wrong_first_records":[r for s in scores for r in s["matched"][:-1] if r.get("first_signal_wrong_side")],
    }
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--period",action="append",required=True,help="NAME=DIR")
    p.add_argument("--out",required=True)
    args=p.parse_args()
    out={}
    for spec in args.period:
        name,base=spec.split("=",1)
        out[name]=audit_period(base)
        x=out[name]
        print(name,json.dumps({k:x[k] for k in (
            "strict_labels","candidate_exact_covered","censored_labels",
            "complete_scored_swings","true_first","wrong_first","correct_first_rate",
            "median_lag_ms","median_entry_distance_bps","median_remaining_swing_fraction"
        )},separators=(",",":")))
        if x["candidate_exact_missing"]:
            print(name,"missing",json.dumps(x["candidate_exact_missing"],separators=(",",":")))
    swings=sum(x["complete_scored_swings"] for x in out.values())
    true=sum(x["true_first"] for x in out.values())
    wrong=sum(x["wrong_first"] for x in out.values())
    combined={
        "complete_scored_swings":swings,"true_first":true,"wrong_first":wrong,
        "correct_first_rate":true/swings if swings else None,
        "wrong_first_rate":wrong/swings if swings else None,
    }
    result={"status":"research_only_orders_off","periods":out,"combined":combined}
    Path(args.out).write_text(json.dumps(result,indent=2)+"\n")
    print("COMBINED",json.dumps(combined,separators=(",",":")))


if __name__=="__main__":
    main()
