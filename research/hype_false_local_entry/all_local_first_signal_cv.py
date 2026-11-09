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
THRESHOLDS=np.arange(.50,.991,.01)


def finite(v):
    return isinstance(v,(int,float,np.number)) and math.isfinite(float(v))


def build(master):
    periods,_=replay.inventory(master,{})
    rows={}
    for name,p in periods.items():
        tags=replay.outcomes(p["early"],p["scope"])
        rr=[]
        for r,tag in zip(p["early"],tags):
            if tag is None:continue
            ep,terminal=tag
            f={k:float(v) for k,v in r["features"].items()
               if finite(v) and feat.point_id(k) in INPUT_IDS and feat.point_id(k) not in QUALITY_ONLY}
            rr.append(dict(r,features=f,episode=int(ep),terminal=bool(terminal),period=name))
        rows[name]=rr
    return periods,rows


def feature_names(train,side,age):
    q=[r for r in train if r["side"]==side and r["age_s"]==age]
    count=Counter(k for r in q for k in r["features"])
    n=max(1,len(q))
    return sorted(k for k,c in count.items() if c/n>=.80)


def X(rows,names):
    return np.asarray([[r["features"].get(k,np.nan) for k in names] for r in rows],dtype=float)


def row_weights(rows):
    # Equalize candidates and classes; no future fields enter X.
    reps=Counter(r["candidate_id"] for r in rows)
    cy={}
    for r in rows:cy[r["candidate_id"]]=bool(r["terminal"])
    pos=sum(cy.values());neg=len(cy)-pos
    pw=min(20.0,max(1.0,neg/max(1,pos)))
    return np.asarray([(pw if r["terminal"] else 1.0)/max(1,reps[r["candidate_id"]]) for r in rows])


def fit(train,names):
    y=np.asarray([r["terminal"] for r in train],dtype=int)
    m=Pipeline([
        ("impute",SimpleImputer(strategy="median",add_indicator=True)),
        ("model",ExtraTreesClassifier(
            n_estimators=700,max_depth=8,min_samples_leaf=7,max_features="sqrt",
            class_weight=None,random_state=20261109,n_jobs=-1
        ))
    ])
    m.fit(X(train,names),y,model__sample_weight=row_weights(train))
    return m


def first_metrics(periods,rows_by_period,pred_by_period,side,threshold,nameset):
    total={"episodes":0,"accepted_first":0,"true_first":0,"false_first":0}
    per={}
    for name in nameset:
        p=periods[name]
        rows=[r for r in rows_by_period[name] if r["side"]==side]
        probs=pred_by_period[name]
        accepted=[r for r,pr in zip(rows,probs) if pr>=threshold]
        m=replay.summarize(p["tape"],p["labels"],side,accepted,p["scope"][0],keep_records=False)
        q={k:m.get(k,0) or 0 for k in total}
        per[name]=q
        for k in total: total[k]+=q[k]
    n=total["true_first"]+total["false_first"]
    total["precision"]=total["true_first"]/n if n else None
    total["recall"]=total["true_first"]/total["episodes"] if total["episodes"] else None
    total["coverage"]=n/total["episodes"] if total["episodes"] else None
    return total,per


def choose_threshold(periods,rows_by_period,pred,side,train_names):
    best=None
    for th in THRESHOLDS:
        m,_=first_metrics(periods,rows_by_period,pred,side,float(th),train_names)
        p=m["precision"] or 0.0;r=m["recall"] or 0.0
        viable=m["true_first"]>=5 and r>=.08
        key=(1 if viable else 0,p,r,m["true_first"],-m["false_first"],th)
        if best is None or key>best[0]:best=(key,float(th),m)
    return best[1],best[2]


def run_side_age(periods,rows_by_period,side,age):
    folds=[]
    names_periods=sorted(periods)
    for hold in names_periods:
        train_names=[p for p in names_periods if p!=hold]
        train=[r for p in train_names for r in rows_by_period[p] if r["side"]==side and r["age_s"]==age]
        test=[r for r in rows_by_period[hold] if r["side"]==side and r["age_s"]==age]
        if not train or not test:continue
        names=feature_names(train,side,age)
        if len(names)<5:continue
        model=fit(train,names)

        train_pred={}
        for p in train_names:
            q=[r for r in rows_by_period[p] if r["side"]==side and r["age_s"]==age]
            train_pred[p]=model.predict_proba(X(q,names))[:,1]
        th,train_metric=choose_threshold(periods,rows_by_period,train_pred,side,train_names)

        ptest=model.predict_proba(X(test,names))[:,1]
        test_pred={hold:ptest}
        test_metric,_=first_metrics(periods,rows_by_period,test_pred,side,th,[hold])
        imp=model.named_steps["model"].feature_importances_[:len(names)]
        top=sorted([
            {"feature":k,"point_id":feat.point_id(k),"importance":float(v)}
            for k,v in zip(names,imp)
        ],key=lambda x:x["importance"],reverse=True)[:15]
        folds.append({
            "holdout":hold,"threshold":th,
            "train":train_metric,"test":test_metric,
            "feature_count":len(names),"top_features":top
        })

    total={"episodes":0,"accepted_first":0,"true_first":0,"false_first":0}
    for f in folds:
        for k in total:total[k]+=f["test"][k]
    n=total["true_first"]+total["false_first"]
    total["precision"]=total["true_first"]/n if n else None
    total["recall"]=total["true_first"]/total["episodes"] if total["episodes"] else None
    total["coverage"]=n/total["episodes"] if total["episodes"] else None
    ps=[f["test"]["precision"] for f in folds if f["test"]["precision"] is not None]
    total["worst_fold_precision"]=min(ps) if ps else None
    return {"side":side,"age_s":age,"folds":folds,"aggregate_oos":total}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--master",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True)

    periods,rows=build(args.master)
    ages=sorted({r["age_s"] for rr in rows.values() for r in rr})
    out={"version":"HYPE-ALL-LOCAL-FIRST-SIGNAL-CV-v1","by_side":{},"real_orders":False}
    for side in ("LOW","HIGH"):
        runs=[run_side_age(periods,rows,side,age) for age in ages]
        runs.sort(key=lambda x:(
            x["aggregate_oos"]["precision"] or 0,
            x["aggregate_oos"]["recall"] or 0,
            x["aggregate_oos"]["true_first"]
        ),reverse=True)
        out["by_side"][side]={"best":runs[0] if runs else None,"all":runs}
    args.output.write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n")
    print("FIRST_SIGNAL_CV="+json.dumps({
        s:None if out["by_side"][s]["best"] is None else {
            "age_s":out["by_side"][s]["best"]["age_s"],
            "aggregate_oos":out["by_side"][s]["best"]["aggregate_oos"],
            "folds":[{"holdout":f["holdout"],"threshold":f["threshold"],"test":f["test"]}
                     for f in out["by_side"][s]["best"]["folds"]]
        } for s in ("LOW","HIGH")
    },separators=(",",":")))


if __name__=="__main__":main()
