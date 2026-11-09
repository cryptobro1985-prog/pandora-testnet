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


def metrics(rows, probs, th):
    tp=fp=fn=tn=0
    for r,p in zip(rows,probs):
        y=bool(r["strict_true"]); pred=float(p)>=float(th)
        if pred and y: tp+=1
        elif pred: fp+=1
        elif y: fn+=1
        else: tn+=1
    return {
        "n":len(rows),"tp":tp,"fp":fp,"fn":fn,"tn":tn,
        "precision":tp/(tp+fp) if tp+fp else None,
        "recall":tp/(tp+fn) if tp+fn else None,
        "coverage":(tp+fp)/len(rows) if rows else 0.0,
    }


def choose_threshold(rows, probs):
    # Precision first. Require enough examples and non-trivial recall so a
    # degenerate near-1.0 threshold cannot "win" by never firing.
    best=(None,0.985,None)
    for i in range(50,1000):
        th=i/1000.0
        m=metrics(rows,probs,th)
        p=m["precision"] or 0.0; r=m["recall"] or 0.0
        viable=(m["tp"]>=2 and (m["tp"]+m["fp"])>=3 and r>=0.20)
        key=(1 if viable else 0,p,r,-m["fp"],th)
        if best[0] is None or key>best[0]:
            best=(key,th,m)
    return best[1],best[2]


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

    vp=[model.probability(side,causal_signature_features(r["features"])) for r in valid]
    th,vm=choose_threshold(valid,vp)
    op=[model.probability(side,causal_signature_features(r["features"])) for r in oos]
    om=metrics(oos,op,th)
    tm=metrics(train,[model.probability(side,causal_signature_features(r["features"])) for r in train],th)
    return {
        "threshold":th,"repeat":repeat,
        "train":tm,"validation":vm,"oos":om,
        "train_rows":len(train),"validation_rows":len(valid),"oos_rows":len(oos),
        "train_positive":pos,
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshots",type=Path,required=True)
    ap.add_argument("--model-out",type=Path,required=True)
    ap.add_argument("--report-out",type=Path,required=True)
    args=ap.parse_args()

    rows=[]
    for r in load(args.snapshots):
        if r.get("side") not in ("LOW","HIGH"):
            continue
        if int(r.get("delay_s",-1)) not in STAGES:
            continue
        if "strict_true" not in r:
            continue
        x=causal_signature_features(r.get("features") or {})
        if not x:
            continue
        rows.append({**r,"features":x})

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

    report={
        "version":"HYPE-LOCAL-SIGNATURE-HISTORY-BOOTSTRAP-v1",
        "teacher":"strict_true",
        "decision_time_gated":False,
        "candidate_age_removed_from_predictors":True,
        "rolling_market_windows_are_causal_inputs":True,
        "rows":len(rows),
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
