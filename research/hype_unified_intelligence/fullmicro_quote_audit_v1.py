#!/usr/bin/env python3
"""HYPE retained FULL-MICRO quote audit and fixed-family chrono ablations.

Research only. Data source: July12-Aug07 full-micro candidate snapshots,
300s causal snapshots. This sample is historically inspected; July test split
is NOT an untouched/independent cross-regime validation.

Never feed strict_true, strict_label_id, internal_true, metadata, terminal
teacher timestamps or future outcomes into predictive X.

Crossed orderbook (spread < 0) is an invalid book quote EVEN when a source
flag reports fullmicro_book_valid=1. All models are compared on identical
quality-clean candidate cohorts; missing source fields stay NaN until train-
only median imputation, with missingness indicators.
"""
from __future__ import annotations
import argparse,zipfile,gzip,json,hashlib,math
from pathlib import Path
import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score,roc_auc_score,brier_score_loss

MEMBER="01_JUL12_AUG07_FULL_MICRO/candidate_snapshots_full_micro.jsonl.gz"
PRICE=["retrace_bps","position_60m","position_6h","position_24h",
 "distance_low_60m_bps","distance_high_60m_bps",
 "distance_low_6h_bps","distance_high_6h_bps",
 "distance_low_24h_bps","distance_high_24h_bps",
 "ret_60s","ret_180s","ret_300s",
 "rev_ret_60s","rev_ret_180s","rev_ret_300s"]
FLOW=["imbalance_15s","imbalance_60s","imbalance_180s","imbalance_300s",
 "rev_flow_60s","rev_eff_60s","rev_eff_180s","rev_eff_300s",
 "buy_60s_log","sell_60s_log",
 "trade_count_60s","trade_count_180s","trade_count_300s"]
BOOK=["fullmicro_spread_bps","fullmicro_book_imbalance_5",
 "fullmicro_book_imbalance_10","fullmicro_book_imbalance_25",
 "fullmicro_book_imbalance_50"]
LIQ=["fullmicro_liq_imbalance_300s","fullmicro_long_liq_notional_60s",
 "fullmicro_short_liq_notional_60s",
 "fullmicro_long_liq_notional_300s","fullmicro_short_liq_notional_300s"]
OI=["fullmicro_open_interest_age_ms",
 "fullmicro_open_interest_sum_open_interest",
 "fullmicro_mark_price_age_ms","fullmicro_mark_price_mark_price",
 "fullmicro_mark_price_index_price"]
FAMILIES={
 "price_only":PRICE,
 "price_flow":PRICE+FLOW,
 "price_flow_book":PRICE+FLOW+BOOK,
 "price_flow_book_liq":PRICE+FLOW+BOOK+LIQ,
 "price_flow_book_liq_oi":PRICE+FLOW+BOOK+LIQ+OI
}

def finite(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

def book_reject_reasons(features):
    """Avoid false rejection based on bid/ask relative to stale last trade.
    A valid bid can be above the last trade; ONLY crossed/invalid quotes are
    rejected. Crossed book is unambiguous: best bid > best ask.
    """
    reasons=[]
    if not finite(features.get("fullmicro_spread_bps")):
        reasons.append("MISSING_OR_NONFINITE_SPREAD")
    elif features["fullmicro_spread_bps"]<0:
        reasons.append("NEGATIVE_CROSSED_BOOK_SPREAD")
    if features.get("fullmicro_book_valid") != 1:
        reasons.append("SOURCE_BOOK_INVALID")
    if not finite(features.get("fullmicro_book_gap_count")):
        reasons.append("MISSING_BOOK_GAP_COUNT")
    elif features["fullmicro_book_gap_count"]>0:
        reasons.append("BOOK_GAP")
    return reasons

def load_snapshots(master):
    with zipfile.ZipFile(master) as z, gzip.open(z.open(MEMBER),"rt") as inp:
        rows=[json.loads(line) for line in inp if line.strip()]
    return sorted([r for r in rows if r.get("delay_s")==300],
                  key=lambda r:(int(r["candidate_ts_ms"]),str(r["candidate_id"])))

def evidence(rows):
    reasons={};bad=[]
    for r in rows:
        rr=book_reject_reasons(r["features"])
        if rr:
            bad.append(r)
            for name in rr:reasons[name]=reasons.get(name,0)+1
    valid=[r for r in rows if not book_reject_reasons(r["features"])]
    return {
     "total_300s":len(rows),"invalid_book_300s":len(bad),
     "invalid_pct":round(100*len(bad)/max(1,len(rows)),4),
     "invalid_marked_book_valid":sum(r["features"].get("fullmicro_book_valid")==1 for r in bad),
     "invalid_true_locals":sum(bool(r["strict_true"]) for r in bad),
     "reasons":reasons,"valid_cohort":valid}

def predict_ablation(rows,features,side,t1,t2):
    rr=[r for r in rows if r["side"]==side]
    xs=[int(r["candidate_ts_ms"]) for r in rr]
    i1=int(np.searchsorted(xs,t1))
    i2=int(np.searchsorted(xs,t2))
    group={"train":rr[:i1],"dev":rr[i1:i2],"test":rr[i2:]}
    ys={k:np.asarray([int(bool(r["strict_true"])) for r in v]) for k,v in group.items()}
    support={k:{"n":len(v),"positive":int(ys[k].sum())} for k,v in group.items()}
    if not all(len(np.unique(y))==2 for y in ys.values()):
        return {"status":"INCOMPLETE_CLASS_SUPPORT","support":support}
    def X(rows):
        return np.asarray([[float(r["features"][k]) if finite(r["features"].get(k))
                else np.nan for k in features] for r in rows],dtype=float)
    xx={k:X(v) for k,v in group.items()}
    # All valid input dimensions are chosen exclusively from TRAIN.
    use=np.isfinite(xx["train"]).any(axis=0)
    model=make_pipeline(SimpleImputer(strategy="median",add_indicator=True),
                        StandardScaler(),
                        LogisticRegression(max_iter=2000,C=.1,class_weight="balanced"))
    model.fit(xx["train"][:,use],ys["train"])
    metrics={}
    for k in ("dev","test"):
        p=model.predict_proba(xx[k][:,use])[:,1]
        y=ys[k]
        selected=p>=.5
        metrics[k]=dict(
          n=len(y),positives=int(y.sum()),base_rate=round(float(y.mean()),4),
          pr_auc=round(float(average_precision_score(y,p)),4),
          roc_auc=round(float(roc_auc_score(y,p)),4),
          brier=round(float(brier_score_loss(y,p)),4),
          accepted_thr0p5=int(selected.sum()),tp_thr0p5=int(y[selected].sum()),
          precision_thr0p5=(round(float(y[selected].mean()),4) if selected.any() else None)
        )
    return {
      "status":"DIAGNOSTIC_ONLY_TOO_FEW_TRUE_LOCALS",
      "train_positive":int(ys["train"].sum()),
      "fitted_dimensions":int(use.sum()),"dev":metrics["dev"],"test":metrics["test"],
      "promotable":False
    }

def audit(master):
    rs=load_snapshots(master)
    e=evidence(rs)
    valid=e.pop("valid_cohort")
    t1=int(valid[int(len(valid)*.6)]["candidate_ts_ms"])
    t2=int(valid[int(len(valid)*.8)]["candidate_ts_ms"])
    return {
      "version":"HYPE-FULLMICRO-CROSSED-BOOK-QUALITY-V1",
      "master_sha256":hashlib.sha256(Path(master).read_bytes()).hexdigest(),
      "research_only":True,"real_orders":False,"promotable":False,
      "cohort":"July12-Aug07 300-second candidate snapshots, pre-inspected",
      "audit":e,"valid_300s":len(valid),
      "split":{"train_before_ms":t1,"dev_before_ms":t2,
               "test":"last 20% of quality-clean chronological July cohort; previously inspected"},
      "ablation":{name:{side:predict_ablation(valid,cols,side,t1,t2)
                     for side in ("LOW","HIGH")}
                  for name,cols in FAMILIES.items()},
      "verdict":"QUARANTINE_CROSSED_BOOK_AND_DO_NOT_PROMOTE_MICRO_ALPHA",
      "limitations":[
       "July test only contains a handful of true LOW/HIGH candidates.",
       "Micro data availability and candidate generation may differ in October.",
       "Results cannot establish out-of-period robustness or executable PnL.",
       "No future labels are used in predictors; past outcome labels are only y.",
       "No broker's real liquidation calculation or price-impact execution is modeled."]
    }

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--master",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    result=audit(a.master)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"audit":result["audit"],
                      "verdict":result["verdict"]}))
