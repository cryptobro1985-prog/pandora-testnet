#!/usr/bin/env python3
"""Warm-start Local v3 from the saved 30-day HYPE causal archive.

This is NOT a replay that recollects market data. It consumes the already
persisted candidate snapshots + compact 1m bars and teaches the same Local v3
heads used by live trading research.

Leakage contract:
- model inputs come only from each candidate snapshot at its historical time;
- future 1m bars are used only to create the delayed 300s economic label;
- TARGET_EVAL fields / strict_true / internal_true are never model inputs;
- historically unavailable sources remain absent (no synthetic imputation).
"""
from __future__ import annotations

import argparse
import bisect
import gzip
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from research.hype_caterpillar_quant.learner import (
    CaterpillarQuantLearner,
    binary_model,
    clean_features,
)


ARCHIVE_VERSION="local116-HYPE-2026-10-04_2026-11-03"
STAGES=(60,180,300)
LABEL_HORIZON_S=300


def finite(v:Any)->bool:
    return isinstance(v,(int,float)) and math.isfinite(v)


def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def stage_price(row:dict[str,Any])->float|None:
    try:
        extreme=float(row["extreme_price"])
        retr=float((row.get("features") or {}).get("retrace_bps") or 0.0)/10000.0
        side=str(row["side"])
        price=extreme*(1.0+retr) if side=="LOW" else extreme*(1.0-retr)
        return price if math.isfinite(price) and price>0 else None
    except Exception:
        return None


def mapped_features(row:dict[str,Any])->dict[str,float]:
    """Translate archived causal features to names shared with the live v3 head."""
    src=row.get("features") or {}
    side=str(row.get("side") or "")
    sign=1.0 if side=="LOW" else -1.0
    out:dict[str,float]={}

    def put(k,v):
        if finite(v):out[k]=float(v)

    # Features that already use the same live names.
    for sec in (5,15,30,60,180,300):
        put(f"ret_{sec}s",src.get(f"ret_{sec}s"))
        put(f"trade_count_{sec}s",src.get(f"trade_count_{sec}s"))

        im=src.get(f"imbalance_{sec}s")
        if finite(im):
            put(f"flow_imbalance_raw_{sec}s",im)
            put(f"cq_flow_alignment_{sec}s",sign*float(im))

        ret=src.get(f"ret_{sec}s")
        if finite(ret):put(f"cq_price_alignment_{sec}s",sign*float(ret))

        # Archive logs are log1p(notional), exactly the scale live FeatureState
        # emits for these large market-size fields.
        put(f"log_trade_buy_notional_{sec}s",src.get(f"buy_{sec}s_log"))
        put(f"log_trade_sell_notional_{sec}s",src.get(f"sell_{sec}s_log"))

        old_eff=src.get(f"old_eff_{sec}s")
        rev_eff=src.get(f"rev_eff_{sec}s")
        put(f"cq_old_efficiency_{sec}s",old_eff)
        put(f"cq_reversal_efficiency_{sec}s",rev_eff)

        # Also expose the corresponding live side-specific efficiency names.
        if side=="LOW":
            put(f"sell_efficiency_{sec}s",old_eff)
            put(f"buy_efficiency_{sec}s",rev_eff)
        else:
            put(f"buy_efficiency_{sec}s",old_eff)
            put(f"sell_efficiency_{sec}s",rev_eff)

    put("log_volume_24h",src.get("volume_24h_log"))
    put("log_turnover_24h",src.get("turnover_24h_log"))

    # Rolling-structure features use the same sign/scale as live FeatureState.
    for label in ("60m","6h","24h"):
        dhi=src.get(f"distance_high_{label}_bps")
        dlo=src.get(f"distance_low_{label}_bps")
        if finite(dhi):put(f"dist_rolling_{label}_high",-float(dhi)/10000.0)
        if finite(dlo):put(f"dist_rolling_{label}_low", float(dlo)/10000.0)
        put(f"cq_position_{label}",src.get(f"position_{label}"))

    put("cq_candidate_side",sign)
    put("cq_candidate_age_s",src.get("age_s"))
    put("cq_retrace_bps",src.get("retrace_bps"))

    # 60s aliases used by existing live Local code.
    put("cq_flow_alignment",out.get("cq_flow_alignment_60s"))

    # Keep these archive-native causal descriptors as a historical prior. They
    # never masquerade as missing live-only sources; live fine-tuning can learn
    # additional dimensions independently.
    for k in ("atr_h1_frac","volatility_60m","directional_3h_rev",
              "directional_6h_rev","reversal_attempts"):
        v=src.get(k)
        if finite(v):put("archive_"+k,v)

    return clean_features(out)


def load_bars(path:Path):
    rows=[]
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            z=json.loads(line)
            if all(k in z for k in ("start_ms","bar_end_ms","high","low")):
                rows.append(z)
    rows.sort(key=lambda z:int(z["start_ms"]))
    return rows,[int(z["start_ms"]) for z in rows]


def economic_outcome(row:dict[str,Any],bars,starts,cost:float):
    price=stage_price(row)
    if price is None:return None
    ts=int(row["snapshot_ts_ms"])
    end=ts+LABEL_HORIZON_S*1000
    # Strictly future complete 1m bars only. This deliberately discards the
    # partial minute containing the snapshot rather than leaking its pre-snapshot
    # high/low into the label.
    first=((ts+59_999)//60_000)*60_000
    i=bisect.bisect_left(starts,first)
    best=worst=0.0
    used=0
    side=str(row["side"])
    while i<len(bars):
        b=bars[i]
        if int(b["start_ms"])>=end:break
        if int(b["bar_end_ms"])>end:
            break
        hi=float(b["high"]);lo=float(b["low"])
        if side=="LOW":
            favorable=hi/price-1.0
            adverse=1.0-lo/price
        else:
            favorable=1.0-lo/price
            adverse=hi/price-1.0
        best=max(best,favorable)
        worst=max(worst,adverse)
        used+=1;i+=1
    if used<3:return None
    advantage=best-worst-float(cost)
    return {
        "local_y":advantage>0.0,
        "bounce_y":best>worst,
        "best_favorable":best,
        "worst_adverse":worst,
        "economic_advantage":advantage,
        "future_bars":used,
        "stage_price":price,
    }


def metric_row(stats):
    tp=stats["tp"];fp=stats["fp"];fn=stats["fn"];tn=stats["tn"]
    n=tp+fp+fn+tn
    return {
        "n":n,"positive":tp+fn,
        "precision":tp/(tp+fp) if tp+fp else None,
        "recall":tp/(tp+fn) if tp+fn else None,
        "accuracy":(tp+tn)/n if n else None,
        "tp":tp,"fp":fp,"fn":fn,"tn":tn,
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--checkpoint",type=Path,required=True)
    ap.add_argument("--history-dir",type=Path,required=True)
    ap.add_argument("--report",type=Path,required=True)
    args=ap.parse_args()

    cand=args.history_dir/"candidate_snapshots.jsonl.gz"
    bars_path=args.history_dir/"compact_1m.jsonl.gz"
    manifest_path=args.history_dir/"manifest.json"
    for p in (cand,bars_path,manifest_path,args.checkpoint):
        if not p.exists():raise SystemExit(f"missing required file: {p}")

    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    fingerprint={
        "archive_version":ARCHIVE_VERSION,
        "period":manifest.get("period"),
        "candidate_snapshots":manifest.get("candidate_snapshots"),
        "candidate_sha256":sha256(cand),
        "bars_sha256":sha256(bars_path),
        "label_contract":"LOCAL_V3_300S_REALIZED_REVERSAL_ADVANTAGE",
    }
    fp=hashlib.sha256(json.dumps(fingerprint,sort_keys=True).encode()).hexdigest()

    learner=CaterpillarQuantLearner.load(args.checkpoint)
    learner._ensure_v2()
    prior=getattr(learner,"historical_local_v3_warmstart",{}) or {}
    if prior.get("fingerprint")==fp and prior.get("applied") is True:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps({"status":"ALREADY_APPLIED",**prior},indent=2)+"\n",encoding="utf-8")
        print("HISTORICAL_LOCAL_V3_WARMSTART=ALREADY_APPLIED")
        return

    bars,starts=load_bars(bars_path)
    oos_start_ms=int(__import__("datetime").datetime.fromisoformat(
        str(manifest.get("oos_start") or "2026-10-27T00:00:00+00:00").replace("Z","+00:00")
    ).timestamp()*1000)

    examples=[]
    skipped=defaultdict(int)
    with gzip.open(cand,"rt",encoding="utf-8") as f:
        for line in f:
            row=json.loads(line)
            stage=int(row.get("delay_s") or -1)
            side=str(row.get("side") or "")
            if stage not in STAGES or side not in ("LOW","HIGH"):
                continue
            outcome=economic_outcome(row,bars,starts,learner.round_trip_cost)
            if outcome is None:
                skipped["no_complete_300s_path"]+=1
                continue
            x=mapped_features(row)
            if not x:
                skipped["no_mapped_features"]+=1
                continue
            examples.append({
                "side":side,"stage":stage,"ts_ms":int(row["snapshot_ts_ms"]),
                "x":x,**outcome,
            })

    if len(examples)<500:
        raise SystemExit(f"insufficient warm-start examples: {len(examples)}")

    # Honest OOS diagnostic first: fit only pre-OOS records, evaluate the saved
    # OOS period without updating on those records.
    diag_models={(side,stage):binary_model() for side in ("LOW","HIGH") for stage in STAGES}
    train_examples=[e for e in examples if e["ts_ms"]<oos_start_ms]
    oos_examples=[e for e in examples if e["ts_ms"]>=oos_start_ms]
    for e in train_examples:
        diag_models[(e["side"],e["stage"])].learn_one(e["x"],bool(e["local_y"]))
    metrics=defaultdict(lambda:{"tp":0,"fp":0,"fn":0,"tn":0})
    for e in oos_examples:
        model=diag_models[(e["side"],e["stage"])]
        p=float(model.predict_proba_one(e["x"]).get(True,0.5))
        pred=p>=0.5;y=bool(e["local_y"])
        z=metrics[f"{e['side']}_{e['stage']}s"]
        if pred and y:z["tp"]+=1
        elif pred and not y:z["fp"]+=1
        elif (not pred) and y:z["fn"]+=1
        else:z["tn"]+=1

    # Apply ALL saved history to the actual live Local v3 heads. Sparse history
    # is valid: absent live-only dimensions get learned later, not zero-imputed.
    applied=defaultdict(lambda:{"labels":0,"positive":0,"bounce_positive":0})
    for e in examples:
        key=(e["side"],e["stage"])
        learner._learn_binary(learner.local_models[key],e["x"],e["local_y"])
        learner.local_labels[key]+=1
        learner.local_pos[key]+=int(bool(e["local_y"]))
        learner._learn_binary(learner.bounce_models[key],e["x"],e["bounce_y"])
        learner.bounce_labels[key]+=1
        learner.bounce_pos[key]+=int(bool(e["bounce_y"]))
        z=applied[f"{e['side']}_{e['stage']}s"]
        z["labels"]+=1;z["positive"]+=int(bool(e["local_y"]))
        z["bounce_positive"]+=int(bool(e["bounce_y"]))

    marker={
        "applied":True,"fingerprint":fp,"archive":fingerprint,
        "examples":len(examples),"train_examples_for_diagnostic":len(train_examples),
        "oos_examples_for_diagnostic":len(oos_examples),
        "applied_by_head":dict(applied),
        "historical_input_rule":"availability-aware sparse causal inputs; no synthetic imputation",
        "future_usage":"future compact 1m highs/lows only for delayed 300s label",
        "target_eval_fields_used_as_inputs":False,
    }
    learner.historical_local_v3_warmstart=marker
    learner.save(args.checkpoint)

    report={
        "status":"APPLIED",
        **marker,
        "oos_diagnostic":{k:metric_row(v) for k,v in sorted(metrics.items())},
        "skipped":dict(skipped),
        "round_trip_cost":learner.round_trip_cost,
        "training_progress_after":learner.report().get("training_progress"),
        "local_models_after":learner.report().get("local_models"),
    }
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("HISTORICAL_LOCAL_V3_WARMSTART="+json.dumps({
        "examples":len(examples),
        "local_labels":sum(learner.local_labels.values()),
        "local_positive":sum(learner.local_pos.values()),
        "training_percent":learner.report()["training_progress"]["heads"]["local"]["percent"],
        "fingerprint":fp,
    },separators=(",",":")))


if __name__=="__main__":
    main()
