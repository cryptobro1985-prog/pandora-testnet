#!/usr/bin/env python3
from __future__ import annotations

import argparse,json,math
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from research.hype_false_local_entry import full116_candidate_features as feat
from research.hype_false_local_entry import full116_terminal_replay as replay
from research.hype_quant.feature_contract import INPUT_IDS

QUALITY_ONLY=set(replay.QUALITY_ONLY)
THRESHOLDS=np.arange(.50,.996,.01)


def finite(v):
    return isinstance(v,(int,float,np.number)) and math.isfinite(float(v))


def build(master):
    periods,_=replay.inventory(master,{})
    rows={}
    for name,p in periods.items():
        tags=replay.outcomes(p["early"],p["scope"])
        rr=[]
        for r,tag in zip(p["early"],tags):
            if tag is None: continue
            ep,terminal=tag
            fx={k:float(v) for k,v in r["features"].items()
                if finite(v) and feat.point_id(k) in INPUT_IDS and feat.point_id(k) not in QUALITY_ONLY}
            rr.append(dict(r,features=fx,episode=int(ep),terminal=bool(terminal),period=name))
        rows[name]=rr
    return periods,rows


def feature_names(rows):
    c=Counter(k for r in rows for k in r["features"])
    n=max(1,len(rows))
    return sorted(k for k,v in c.items() if v/n>=.80)


def X(rows,names):
    return np.asarray([[r["features"].get(k,np.nan) for k in names] for r in rows],dtype=float)


def weights(rows):
    reps=Counter(r["candidate_id"] for r in rows)
    bycid={}
    for r in rows: bycid[r["candidate_id"]]=bool(r["terminal"])
    pos=sum(bycid.values()); neg=len(bycid)-pos
    pw=min(20.0,max(1.0,neg/max(1,pos)))
    return np.asarray([(pw if r["terminal"] else 1.0)/max(1,reps[r["candidate_id"]]) for r in rows])


def fit(rows,names):
    y=np.asarray([r["terminal"] for r in rows],dtype=int)
    m=Pipeline([
        ("impute",SimpleImputer(strategy="median",add_indicator=True)),
        ("model",ExtraTreesClassifier(
            n_estimators=700,max_depth=8,min_samples_leaf=7,max_features="sqrt",
            random_state=20261110,n_jobs=-1
        ))
    ])
    m.fit(X(rows,names),y,model__sample_weight=weights(rows))
    return m


def evaluate(periods,rows_by_period,pred_by_period,side,threshold,nameset):
    total=dict(episodes=0,confirmations=0,true_confirmations=0,false_confirmations=0)
    remaining=[]; captured=[]; entry_distance=[]; false_adverse=[]; false_continuation=[]; records=[]; per={}
    for name in nameset:
        p=periods[name]
        q=[r for r in rows_by_period[name] if r["side"]==side]
        probs=pred_by_period[name]
        accepted=[r for r,pr in zip(q,probs) if pr>=threshold]
        m=replay.summarize(p["tape"],p["labels"],side,accepted,p["scope"][0],keep_records=True)
        first=m.get("first_signals") or []
        tr=sum(bool(r.get("true_first")) for r in first)
        fl=len(first)-tr
        ep=int(m.get("episodes") or 0)
        per[name]={"episodes":ep,"confirmations":len(first),"true_confirmations":tr,"false_confirmations":fl}
        total["episodes"]+=ep; total["confirmations"]+=len(first)
        total["true_confirmations"]+=tr; total["false_confirmations"]+=fl
        labs=p["scope"][0][0]
        for r in first:
            if not r.get("true_first"):
                if finite(r.get("false_signal_adverse_to_terminal_bps")): false_adverse.append(float(r["false_signal_adverse_to_terminal_bps"]))
                if finite(r.get("false_candidate_continuation_bps")): false_continuation.append(float(r["false_candidate_continuation_bps"]))
                records.append({"period":name,**r})
                continue
            rem=float(r.get("remaining_swing_bps") or 0.0)
            remaining.append(rem)
            epidx=int(r["episode"])
            local=float(labs[epidx]["extreme_price"])
            nxt=float(labs[epidx+1]["extreme_price"])
            full=(nxt/local-1.0)*10000.0 if side=="LOW" else (local-nxt)/local*10000.0
            sig=float(r["signal_price"])
            dist=max(0.0,(sig/local-1.0)*10000.0) if side=="LOW" else max(0.0,(local-sig)/local*10000.0)
            entry_distance.append(dist)
            captured.append(rem/max(full,1e-9))
            records.append({"period":name,**r,"full_swing_bps":full,"entry_distance_from_local_bps":dist,
                            "captured_fraction_of_full_swing":rem/max(full,1e-9)})
    n=total["confirmations"]
    total["confirmation_precision"]=total["true_confirmations"]/n if n else None
    total["confirmation_recall"]=total["true_confirmations"]/total["episodes"] if total["episodes"] else None
    total["median_remaining_swing_bps"]=float(np.median(remaining)) if remaining else None
    total["median_entry_distance_from_local_bps"]=float(np.median(entry_distance)) if entry_distance else None
    total["median_captured_fraction"]=float(np.median(captured)) if captured else None
    total["false_adverse_median_bps"]=float(np.median(false_adverse)) if false_adverse else None
    total["false_adverse_p90_bps"]=float(np.percentile(false_adverse,90)) if false_adverse else None
    total["false_continuation_median_bps"]=float(np.median(false_continuation)) if false_continuation else None
    return total,per,records


def choose(periods,rows,pred,side,train_names):
    frontier=[]; best=None
    for th in THRESHOLDS:
        m,_,_=evaluate(periods,rows,pred,side,float(th),train_names)
        p=m["confirmation_precision"] or 0.0
        r=m["confirmation_recall"] or 0.0
        rem=m["median_remaining_swing_bps"] or 0.0
        n=m["true_confirmations"]
        viable=n>=5
        key=(1 if viable else 0,p,rem,r,n,-m["false_confirmations"])
        frontier.append({"threshold":float(th),"metrics":m})
        if best is None or key>best[0]:
            best=(key,float(th),m)
    return best[1],best[2],frontier


def inner_oof_predictions(periods, rows, side, train_names):
    """Each calibration prediction is made by a model that never saw its period."""
    predictions = {}
    diagnostics = []
    for valid in train_names:
        fit_names = [p for p in train_names if p != valid]
        fit_rows = [r for p in fit_names for r in rows[p] if r["side"] == side]
        valid_rows = [r for r in rows[valid] if r["side"] == side]
        names = feature_names(fit_rows)
        if len({bool(r["terminal"]) for r in fit_rows}) < 2:
            raise ValueError(f"Inner OOF {side}/{valid}: single-class fit")
        model = fit(fit_rows, names)
        predictions[valid] = model.predict_proba(X(valid_rows, names))[:, 1]
        diagnostics.append({"validation_period": valid, "fit_periods": fit_names,
                            "feature_count": len(names), "rows": len(valid_rows)})
    return predictions, diagnostics


def run_side(periods, rows, side):
    folds = []
    names_periods = sorted(periods)
    for hold in names_periods:
        train_names = [p for p in names_periods if p != hold]
        # Calibration must not use scores from a model fitted on the same rows.
        oof_pred, inner_folds = inner_oof_predictions(periods, rows, side, train_names)
        th, calibration_metrics, frontier = choose(periods, rows, oof_pred, side, train_names)
        train = [r for p in train_names for r in rows[p] if r["side"] == side]
        test = [r for r in rows[hold] if r["side"] == side]
        names = feature_names(train)
        model = fit(train, names)
        test_pred = {hold: model.predict_proba(X(test, names))[:, 1]}
        test_metrics, _, records = evaluate(periods, rows, test_pred, side, th, [hold])
        folds.append({"holdout": hold, "threshold": th,
                      "calibration": calibration_metrics, "inner_oof_folds": inner_folds,
                      "test": test_metrics, "test_records": records,
                      "feature_count": len(names), "threshold_frontier": frontier})
    agg = dict(episodes=0, confirmations=0, true_confirmations=0, false_confirmations=0)
    rem, dist, cap, false_adverse, false_continuation = [], [], [], [], []
    for f in folds:
        for k in agg: agg[k] += f["test"][k]
        for r in f["test_records"]:
            if not r.get("true_first"):
                if finite(r.get("false_signal_adverse_to_terminal_bps")): false_adverse.append(float(r["false_signal_adverse_to_terminal_bps"]))
                if finite(r.get("false_candidate_continuation_bps")): false_continuation.append(float(r["false_candidate_continuation_bps"]))
            if r.get("true_first"):
                rem.append(float(r.get("remaining_swing_bps") or 0.0))
                dist.append(float(r.get("entry_distance_from_local_bps") or 0.0))
                cap.append(float(r.get("captured_fraction_of_full_swing") or 0.0))
    n = agg["confirmations"]
    agg["confirmation_precision"] = agg["true_confirmations"]/n if n else None
    agg["confirmation_recall"] = agg["true_confirmations"]/agg["episodes"] if agg["episodes"] else None
    agg["median_remaining_swing_bps"] = float(np.median(rem)) if rem else None
    agg["median_entry_distance_from_local_bps"] = float(np.median(dist)) if dist else None
    agg["median_captured_fraction"] = float(np.median(cap)) if cap else None
    agg["false_adverse_median_bps"] = float(np.median(false_adverse)) if false_adverse else None
    agg["false_adverse_p90_bps"] = float(np.percentile(false_adverse,90)) if false_adverse else None
    agg["false_continuation_median_bps"] = float(np.median(false_continuation)) if false_continuation else None
    agg["worst_period_precision"] = min((f["test"]["confirmation_precision"] for f in folds if f["test"]["confirmation_precision"] is not None),default=None)
    return {"side": side, "folds": folds, "aggregate_oos": agg}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--master",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    a=ap.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    periods,rows=build(a.master)
    out={"version":"HYPE-CONFIRMED-LOCAL-BOUNCE-ENTRY-CV-v2-inner-period-OOF",
         "objective":"CONFIRM_LOCAL_THEN_ENTER_REVERSAL_MOVE_NOT_EXTREME_GUESS",
         "time_gate":False,"by_side":{},"real_orders":False}
    for side in ("LOW","HIGH"):
        out["by_side"][side]=run_side(periods,rows,side)
    a.output.write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n")
    print("CONFIRMED_BOUNCE_CV="+json.dumps({
      s:out["by_side"][s]["aggregate_oos"] for s in ("LOW","HIGH")
    },separators=(",",":")))


if __name__=="__main__": main()
