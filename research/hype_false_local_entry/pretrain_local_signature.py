#!/usr/bin/env python3
from __future__ import annotations

import argparse, gzip, json, math, pickle
from datetime import datetime, timezone
from pathlib import Path

from research.hype_false_local_entry.local_signature_model import LocalSignatureModel

TRAIN_END=int(datetime(2026,10,23,tzinfo=timezone.utc).timestamp()*1000)
OOS_START=int(datetime(2026,10,27,tzinfo=timezone.utc).timestamp()*1000)
STAGES={60,180,300}


def load(path: Path):
    with gzip.open(path,"rt",encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def finalized_strict_label_ids(path: Path) -> set[int]:
    with gzip.open(path,"rt",encoding="utf-8") as fh:
        doc=json.load(fh)
    return {
        int(r["label_id"]) for r in (doc.get("strict") or [])
        if bool(r.get("reference_finalized",True))
    }


def causal_signature_features(raw: dict) -> dict[str,float]:
    """Historical bootstrap features with explicit elapsed-time fields removed.

    Rolling market windows (5s/15s/60s/etc.) remain legal causal measurements.
    What is removed is candidate age/delay itself, so elapsed time cannot become
    an entry rule.
    """
    out={}
    for k,v in (raw or {}).items():
        lk=str(k).lower()
        if lk in {"age_s","delay_s","candidate_age_s","elapsed_s","stage"}:
            continue
        if lk.startswith("target_") or "strict_true" in lk or "label" in lk:
            continue
        if isinstance(v,(int,float)) and math.isfinite(float(v)):
            out[str(k)]=float(v)
    return out


def first_signal_metrics(rows, model, side, th):
    grouped={}
    true_candidates=set()
    for r in rows:
        if r["side"]!=side:
            continue
        grouped.setdefault(r["candidate_id"],[]).append(r)
        if r["strict_true"]:
            true_candidates.add(r["candidate_id"])

    accepted=[]
    for cid,rr in grouped.items():
        rr.sort(key=lambda z:int(z.get("snapshot_ts_ms",z["candidate_ts_ms"])))
        for r in rr:
            p=model.probability(side,causal_signature_features(r["features"]))
            if p>=th:
                accepted.append((r,p))
                break

    tp=sum(bool(r["strict_true"]) for r,_ in accepted)
    fp=len(accepted)-tp
    delays=[
        max(0.0,(int(r.get("snapshot_ts_ms",r["candidate_ts_ms"]))-int(r["candidate_ts_ms"]))/1000.0)
        for r,_ in accepted if r["strict_true"]
    ]
    delays.sort()
    med=None if not delays else delays[len(delays)//2]
    return {
        "candidates":len(grouped),
        "reference_true_candidates":len(true_candidates),
        "accepted_first":len(accepted),
        "true_first":tp,
        "false_first":fp,
        "precision":tp/len(accepted) if accepted else None,
        "recall":tp/len(true_candidates) if true_candidates else None,
        "coverage":len(accepted)/len(grouped) if grouped else 0.0,
        "median_delay_s":med,
    }


def choose_threshold(rows, model, side):
    best=None
    for i in range(500,1000):
        th=i/1000.0
        m=first_signal_metrics(rows,model,side,th)
        p=m["precision"] or 0.0
        r=m["recall"] or 0.0
        viable=(m["true_first"]>=2 and m["accepted_first"]>=3 and r>=0.20)
        # First-signal precision dominates; recall breaks ties. Delay is only a
        # tertiary metric and never an eligibility clock.
        delay=m["median_delay_s"] if m["median_delay_s"] is not None else 1e9
        key=(1 if viable else 0,p,r,-m["false_first"],-delay,th)
        if best is None or key>best[0]:
            best=(key,th,m)
    return (best[1],best[2]) if best else (0.985,None)

def fit(rows, side):
    rr=[r for r in rows if r["side"]==side]
    train=[r for r in rr if int(r["candidate_ts_ms"])<TRAIN_END]
    valid=[r for r in rr if TRAIN_END<=int(r["candidate_ts_ms"])<OOS_START]
    oos=[r for r in rr if int(r["candidate_ts_ms"])>=OOS_START]

    model=LocalSignatureModel()
    pos=sum(bool(r["strict_true"]) for r in train)
    neg=len(train)-pos
    repeat=max(1,min(12,round(neg/max(1,pos))))
    for r in train:
        x=causal_signature_features(r["features"])
        for _ in range(repeat if r["strict_true"] else 1):
            model.learn(side,x,bool(r["strict_true"]),live=False)

    th,vm=choose_threshold(valid,model,side)
    om=first_signal_metrics(oos,model,side,th)
    tm=first_signal_metrics(train,model,side,th)
    return {
        "threshold":th,"repeat":repeat,
        "train":tm,"validation":vm,"oos":om,
        "train_rows":len(train),"validation_rows":len(valid),"oos_rows":len(oos),
        "train_positive":pos,
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshots",type=Path,required=True)
    ap.add_argument("--labels-gz",type=Path,required=True)
    ap.add_argument("--model-out",type=Path,required=True)
    ap.add_argument("--report-out",type=Path,required=True)
    args=ap.parse_args()

    finalized_ids=finalized_strict_label_ids(args.labels_gz)
    rows=[]
    for r in load(args.snapshots):
        if r.get("side") not in ("LOW","HIGH"):
            continue
        if int(r.get("delay_s",-1)) not in STAGES:
            continue
        label_id=r.get("strict_label_id")
        y=bool(label_id is not None and int(label_id) in finalized_ids)
        x=causal_signature_features(r.get("features") or {})
        if not x:
            continue
        rows.append({**r,"features":x,"strict_true":y})

    if not rows:
        raise SystemExit("no strict historical signature rows")

    selected={side:fit(rows,side) for side in ("LOW","HIGH")}

    # Final research model: after thresholds are selected only on validation and
    # OOS is reported untouched, fit all available 30d rows for live shadow use.
    final=LocalSignatureModel(
        low_threshold=selected["LOW"]["threshold"],
        high_threshold=selected["HIGH"]["threshold"],
    )
    for side in ("LOW","HIGH"):
        rr=[r for r in rows if r["side"]==side]
        pos=sum(bool(r["strict_true"]) for r in rr)
        neg=len(rr)-pos
        repeat=max(1,min(12,round(neg/max(1,pos))))
        for r in rr:
            for _ in range(repeat if r["strict_true"] else 1):
                final.learn(side,r["features"],bool(r["strict_true"]),live=False)

    final.history_bootstrap={
        "version":"HYPE-LOCAL-SIGNATURE-HISTORY-BOOTSTRAP-v1",
        "teacher":"STRICT_L6_K2_REFERENCE_FINALIZED_ONLY",
        "rows":len(rows),
        "finalized_strict_label_ids":len(finalized_ids),
        "thresholds":{"LOW":selected["LOW"]["threshold"],"HIGH":selected["HIGH"]["threshold"]},
        "candidate_age_removed_from_predictors":True,
    }

    report={
        "version":"HYPE-LOCAL-SIGNATURE-HISTORY-BOOTSTRAP-v1",
        "teacher":"STRICT_L6_K2_REFERENCE_FINALIZED_ONLY",
        "decision_time_gated":False,
        "candidate_age_removed_from_predictors":True,
        "rolling_market_windows_are_causal_inputs":True,
        "rows":len(rows),
        "finalized_strict_label_ids":len(finalized_ids),
        "by_side":selected,
        "model_report":final.report(),
        "warning":"Historical stage snapshots bootstrap the signature only; event-driven live/OOS first-signal evidence remains required.",
        "real_orders":False,
    }
    args.model_out.parent.mkdir(parents=True,exist_ok=True)
    with args.model_out.open("wb") as fh:
        pickle.dump(final,fh,pickle.HIGHEST_PROTOCOL)
    args.report_out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("LOCAL_SIGNATURE_BOOTSTRAP="+json.dumps(report,separators=(",",":")))


if __name__=="__main__":
    main()
