from __future__ import annotations
import argparse
import gzip
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import median
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from research.local_116_30d.run_symbol import (
    read_jsonl_gz, fit_model, candidate_first_accept, score_record,
    stamp, DISCOVERY, TRAIN_END, OOS, END, robust_stats
)

def write_json(path,obj):
    Path(path).write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")

def token_effect(records,name,start,end):
    pos=[r["features"][name] for r in records if start<=r["candidate_ts_ms"]<end and r["strict_true"] and name in r["features"]]
    neg=[r["features"][name] for r in records if start<=r["candidate_ts_ms"]<end and not r["strict_true"] and name in r["features"]]
    if not pos or not neg:return None
    allv=pos+neg;_,scale=robust_stats(allv)
    return (median(pos)-median(neg))/scale

def retune_threshold(records,model):
    valid=[r for r in records if stamp(TRAIN_END)<=r["candidate_ts_ms"]<stamp(OOS)]
    scores=sorted(score_record(r,model) for r in valid if score_record(r,model)>-900)
    thresholds=sorted(set(scores))
    if len(thresholds)>100:
        thresholds=[thresholds[int(i*(len(thresholds)-1)/99)] for i in range(100)]
    best=None
    for th in thresholds:
        model["threshold"]=th
        m=candidate_first_accept(valid,model,stamp(TRAIN_END),stamp(OOS))
        if m["accepted"]<10:continue
        delay=(m["median_delay_s"] or 300)/300
        objective=.60*m["precision"]+.35*m["recall"]-.05*delay
        row=(objective,m["precision"],m["recall"],th,m)
        if best is None or row[:3]>best[:3]:best=row
    if best:
        model["threshold"]=best[3];model["validation"]=best[4]
    return model

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True,type=Path)
    ap.add_argument("--output",required=True,type=Path)
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    paths=sorted(args.root.rglob("candidate_snapshots.jsonl.gz"))
    if len(paths)!=10:
        raise SystemExit(f"need exactly 10 token candidate datasets, found {len(paths)}")
    records=[];by_token={};summaries={}
    for p in paths:
        rows=list(read_jsonl_gz(p))
        if not rows:raise SystemExit("empty candidate dataset: "+str(p))
        symbol=rows[0]["symbol"]
        if symbol in by_token:raise SystemExit("duplicate token artifact: "+symbol)
        by_token[symbol]=rows;records.extend(rows)
        sp=p.parent/"summary.json"
        if sp.exists():summaries[symbol]=json.loads(sp.read_text())
    model=fit_model(records)

    # Cross-token stability gate: a global feature survives only when its
    # true-vs-false direction agrees with the pooled weight on >=70% of tokens
    # where both classes are observable.
    stability={}
    keep={}
    for name,row in model["features"].items():
        signs={}
        for symbol,rr in by_token.items():
            eff=token_effect(rr,name,stamp(DISCOVERY),stamp(TRAIN_END))
            if eff is not None and abs(eff)>=.02:
                signs[symbol]=eff
        global_sign=1 if row["weight"]>0 else -1
        agree=sum((1 if v>0 else -1)==global_sign for v in signs.values())
        ratio=agree/len(signs) if signs else 0.0
        stability[name]={"token_effects":signs,"agreement_ratio":ratio,"tokens_with_evidence":len(signs)}
        if len(signs)>=5 and ratio>=.70:
            keep[name]=row
    if len(keep)>=3:
        model["features"]=dict(sorted(keep.items(),key=lambda kv:abs(kv[1]["weight"]),reverse=True)[:16])
        model=retune_threshold(records,model)
    model["cross_token_stability"]=stability
    model["feature_policy"]="retain time-stable pooled effects; require same direction on >=70% of >=5 tokens"

    pooled_discovery=candidate_first_accept(records,model,stamp(DISCOVERY),stamp(OOS))
    pooled_oos=candidate_first_accept(records,model,stamp(OOS),stamp(END))
    per_token_oos={s:candidate_first_accept(rr,model,stamp(OOS),stamp(END)) for s,rr in by_token.items()}
    per_token_discovery={s:candidate_first_accept(rr,model,stamp(DISCOVERY),stamp(OOS)) for s,rr in by_token.items()}

    # Confidence-state policy stays causal. Later states require survival time
    # in addition to model score, so a single impulse cannot hard-confirm a local.
    threshold=float(model.get("threshold",0.0))
    weights=[abs(x["weight"]) for x in model["features"].values()]
    margin=max(.05,median(weights)*.15 if weights else .05)
    state_machine={
        "WATCH":"new rolling structural extreme; no trade implication",
        "FORMING":"candidate survives without a new same-side extreme for >=30s",
        "EARLY_HIGH_CONFIDENCE":f"causal score >= {threshold:.6f}",
        "CONFIRMED":f"survival >=60s and causal score >= {threshold+margin:.6f}",
        "HARD_CONFIRMED":f"survival >=180s and causal score >= {threshold+2*margin:.6f}",
        "INVALIDATED":"any new same-side extreme before confirmation resets candidate to the newer extreme",
        "note":"thresholds are frozen from discovery/validation; final OOS never tunes them"
    }
    result={
        "tokens":sorted(by_token),
        "records":len(records),
        "global_model":model,
        "pooled_discovery":pooled_discovery,
        "pooled_oos":pooled_oos,
        "per_token_discovery":per_token_discovery,
        "per_token_oos":per_token_oos,
        "state_machine":state_machine,
        "historical_limit":"full 116 contract is availability-aware; unavailable historical L50/liquidation/OI fields are not fabricated",
        "promotion_rule":"do not promote forward-only L50/OI/liquidation inputs until they show OOS improvement on actually recorded observations",
    }
    write_json(args.output/"global_model.json",model)
    write_json(args.output/"global_summary.json",result)
    write_json(args.output/"cross_token_feature_stability.json",stability)
    print("LOCAL116_GLOBAL="+json.dumps({
        "tokens":result["tokens"],"records":len(records),
        "features":list(model["features"]),"threshold":model["threshold"],
        "discovery":pooled_discovery,"oos":pooled_oos
    },separators=(",",":"),sort_keys=True))

if __name__=="__main__":
    main()
