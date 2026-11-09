#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline

from research.hype_false_local_entry import full116_candidate_features as feat
from research.hype_false_local_entry import full116_terminal_replay as replay
from research.hype_quant.feature_contract import INPUT_IDS, POINTS


QUALITY_ONLY=set(replay.QUALITY_ONLY)
POINT_TITLE={int(p["id"]):p["title"] for p in POINTS}
MIN_TRUE=5
MIN_FALSE=20


def finite(v):
    return isinstance(v,(int,float,np.number)) and math.isfinite(float(v))


def safe_auc(y,x):
    y=np.asarray(y,dtype=int);x=np.asarray(x,dtype=float)
    ok=np.isfinite(x)
    y=y[ok];x=x[ok]
    if len(y)<10 or len(set(y))<2:
        return None
    try:return float(roc_auc_score(y,x))
    except Exception:return None


def gap_iqr(y,x):
    y=np.asarray(y,dtype=int);x=np.asarray(x,dtype=float)
    ok=np.isfinite(x);y=y[ok];x=x[ok]
    a=x[y==0];b=x[y==1]
    if len(a)<MIN_FALSE or len(b)<MIN_TRUE:return None
    lo,hi=np.quantile(x,[.25,.75])
    scale=float(hi-lo)
    if not scale:
        scale=float(np.std(x))
    if not scale:return None
    return float((np.median(b)-np.median(a))/scale)


def relation_stats(records,name):
    per={}
    for period,rows in records.items():
        vals=[];ys=[]
        for r in rows:
            v=r["features"].get(name)
            if finite(v):
                vals.append(float(v));ys.append(int(r["terminal"]))
        if sum(ys)<MIN_TRUE or len(ys)-sum(ys)<MIN_FALSE:
            continue
        auc=safe_auc(ys,vals);gap=gap_iqr(ys,vals)
        if auc is None or gap is None:continue
        per[period]={
            "auc":auc,"auc_strength":abs(auc-.5)*2,
            "direction":"HIGHER_AT_TRUE" if auc>.5 else "LOWER_AT_TRUE",
            "median_gap_iqr":gap,
            "true_n":int(sum(ys)),"false_n":int(len(ys)-sum(ys)),
            "true_median":float(np.median(np.asarray(vals)[np.asarray(ys)==1])),
            "false_median":float(np.median(np.asarray(vals)[np.asarray(ys)==0])),
        }
    if not per:return None
    dirs=[1 if x["auc"]>.5 else -1 for x in per.values()]
    consistency=abs(sum(dirs))/len(dirs)
    strengths=[x["auc_strength"] for x in per.values()]
    gaps=[abs(x["median_gap_iqr"]) for x in per.values()]
    return {
        "periods":per,
        "period_count":len(per),
        "sign_consistency":float(consistency),
        "worst_auc_strength":float(min(strengths)),
        "median_auc_strength":float(np.median(strengths)),
        "median_abs_gap_iqr":float(np.median(gaps)),
        "robust_score":float(
            (len(per)/4.0)*consistency*
            (0.55*min(strengths)+0.30*np.median(strengths)+0.15*min(3.0,np.median(gaps))/3.0)
        ),
    }


def build_period_rows(master):
    periods,_=replay.inventory(master,{})
    result={}
    for name,p in periods.items():
        tags=replay.outcomes(p["early"],p["scope"])
        rows=[]
        for r,tag in zip(p["early"],tags):
            if tag is None:continue
            ep,terminal=tag
            f={k:float(v) for k,v in r["features"].items()
               if finite(v) and feat.point_id(k) in INPUT_IDS and feat.point_id(k) not in QUALITY_ONLY}
            rows.append({
                "period":name,"side":r["side"],"age_s":int(r["age_s"]),
                "candidate_id":r["candidate_id"],"episode":int(ep),
                "terminal":bool(terminal),"features":f,
            })
        result[name]=rows
    return periods,result


def static_atlas(rows_by_period,side,age):
    records={}
    names=set()
    for period,rows in rows_by_period.items():
        q=[r for r in rows if r["side"]==side and r["age_s"]==age]
        records[period]=q
        for r in q:names.update(r["features"])
    out=[]
    for name in sorted(names):
        stat=relation_stats(records,name)
        if stat is None:continue
        point=feat.point_id(name)
        out.append({
            "kind":"STATIC","side":side,"age_s":age,
            "feature":name,"point_id":point,"point_title":POINT_TITLE.get(point),
            **stat
        })
    out.sort(key=lambda x:(x["robust_score"],x["period_count"],x["worst_auc_strength"]),reverse=True)
    return out


def transition_atlas(rows_by_period,side,a,b):
    records={}
    names=set()
    for period,rows in rows_by_period.items():
        by=defaultdict(dict)
        meta={}
        for r in rows:
            if r["side"]!=side or r["age_s"] not in (a,b):continue
            by[r["candidate_id"]][r["age_s"]]=r
            meta[r["candidate_id"]]=r
        q=[]
        for cid,z in by.items():
            if a not in z or b not in z:continue
            fa,fb=z[a]["features"],z[b]["features"]
            common=fa.keys()&fb.keys()
            delta={f"DELTA__{k}":float(fb[k]-fa[k]) for k in common}
            if not delta:continue
            q.append({
                "period":period,"side":side,"age_s":b,"candidate_id":cid,
                "episode":z[b]["episode"],"terminal":z[b]["terminal"],
                "features":delta,
            })
            names.update(delta)
        records[period]=q
    out=[]
    for dname in sorted(names):
        base=dname.split("DELTA__",1)[1]
        stat=relation_stats(records,dname)
        if stat is None:continue
        point=feat.point_id(base)
        out.append({
            "kind":"TRANSITION","side":side,"from_age_s":a,"to_age_s":b,
            "feature":base,"delta_feature":dname,
            "point_id":point,"point_title":POINT_TITLE.get(point),
            **stat
        })
    out.sort(key=lambda x:(x["robust_score"],x["period_count"],x["worst_auc_strength"]),reverse=True)
    return out


def matrix(rows,names):
    return np.asarray([[r["features"].get(k,np.nan) for k in names] for r in rows],dtype=float)


def cross_period_model(rows_by_period,side,age,ranked):
    # Use only universally stable top relationships; model score is descriptive
    # cross-period transfer, not a trading authorization.
    features=[]
    for x in ranked:
        if x["period_count"]==4 and x["sign_consistency"]==1.0:
            features.append(x["feature"])
        if len(features)>=24:break
    if len(features)<3:
        features=[x["feature"] for x in ranked[:min(12,len(ranked))]]
    folds=[]
    importances=defaultdict(list)
    for holdout in sorted(rows_by_period):
        train=[r for p,rs in rows_by_period.items() if p!=holdout
               for r in rs if r["side"]==side and r["age_s"]==age]
        test=[r for r in rows_by_period[holdout] if r["side"]==side and r["age_s"]==age]
        if not train or not test:continue
        ytr=np.asarray([r["terminal"] for r in train],dtype=int)
        yte=np.asarray([r["terminal"] for r in test],dtype=int)
        if min(np.bincount(ytr,minlength=2))<3 or min(np.bincount(yte,minlength=2))<2:
            continue
        model=Pipeline([
            ("impute",SimpleImputer(strategy="median",add_indicator=True)),
            ("model",ExtraTreesClassifier(
                n_estimators=500,max_depth=7,min_samples_leaf=8,
                max_features="sqrt",class_weight="balanced",
                random_state=20261109,n_jobs=-1,
            ))
        ])
        model.fit(matrix(train,features),ytr)
        p=model.predict_proba(matrix(test,features))[:,1]
        auc=float(roc_auc_score(yte,p))
        ap=float(average_precision_score(yte,p))
        folds.append({
            "holdout_period":holdout,"rows":len(test),"true":int(yte.sum()),
            "auc":auc,"average_precision":ap,
        })
        # Missing-indicator columns follow originals; only collect original importances.
        imp=model.named_steps["model"].feature_importances_[:len(features)]
        for k,v in zip(features,imp):importances[k].append(float(v))
    if not folds:return None
    ranked_imp=sorted([
        {
            "feature":k,"point_id":feat.point_id(k),"point_title":POINT_TITLE.get(feat.point_id(k)),
            "mean_importance":float(np.mean(v)),"min_importance":float(min(v)),
        }
        for k,v in importances.items()
    ],key=lambda x:x["mean_importance"],reverse=True)
    return {
        "side":side,"age_s":age,"features":features,
        "folds":folds,
        "mean_auc":float(np.mean([x["auc"] for x in folds])),
        "worst_auc":float(min(x["auc"] for x in folds)),
        "mean_average_precision":float(np.mean([x["average_precision"] for x in folds])),
        "feature_importance":ranked_imp,
    }


def point_summary(all_relations):
    agg=defaultdict(list)
    for r in all_relations:
        agg[(r["side"],r["point_id"])].append(r["robust_score"])
    out={}
    for side in ("LOW","HIGH"):
        q=[]
        for (s,pid),scores in agg.items():
            if s!=side:continue
            q.append({
                "point_id":pid,"point_title":POINT_TITLE.get(pid),
                "best_robust_score":float(max(scores)),
                "median_robust_score":float(np.median(scores)),
                "relationship_count":len(scores),
            })
        q.sort(key=lambda x:(x["best_robust_score"],x["median_robust_score"]),reverse=True)
        out[side]=q
    return out


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--master",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True)

    periods,rows=build_period_rows(args.master)
    ages=sorted({r["age_s"] for rs in rows.values() for r in rs})
    static={};transitions={};models={}
    flat=[]
    for side in ("LOW","HIGH"):
        static[side]={}
        models[side]={}
        for age in ages:
            rel=static_atlas(rows,side,age)
            static[side][str(age)]=rel[:100]
            flat.extend(rel)
            models[side][str(age)]=cross_period_model(rows,side,age,rel)
        transitions[side]={}
        for a,b in zip(ages,ages[1:]):
            rel=transition_atlas(rows,side,a,b)
            transitions[side][f"{a}->{b}"]=rel[:100]
            flat.extend(rel)

    # Universally robust top list across static + transition relationships.
    universal={}
    for side in ("LOW","HIGH"):
        q=[r for r in flat if r["side"]==side and r["period_count"]==4 and r["sign_consistency"]==1.0]
        q.sort(key=lambda x:(x["robust_score"],x["worst_auc_strength"]),reverse=True)
        universal[side]=q[:100]

    report={
        "version":"HYPE-ALL-LOCAL-RELATIONSHIP-ATLAS-v1",
        "target":"STRICT L6/K2 terminal Local vs false candidate state",
        "master_periods":list(periods),
        "teacher_locals":sum(len(p["scope"][0][0]) for p in periods.values()),
        "contract":{
            "canonical_points":116,
            "legal_causal_predictor_points":len(INPUT_IDS),
            "excluded_target_eval_metadata":116-len(INPUT_IDS),
            "note":"TARGET/EVAL and metadata are teacher/evaluation only; never predictors.",
        },
        "ages_are_observation_slices_not_entry_gates":ages,
        "universal_top_relationships":universal,
        "point_summary":point_summary(flat),
        "static_relationships":static,
        "transition_relationships":transitions,
        "cross_period_multivariate":models,
        "selection_rule":"Prefer four-period sign-consistent relationships with highest worst-period discrimination; then test combinations chronologically.",
        "real_orders":False,
    }
    args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

    concise={}
    for side in ("LOW","HIGH"):
        concise[side]={
            "top10":[{
                "kind":r["kind"],"point_id":r["point_id"],"point_title":r["point_title"],
                "feature":r["feature"],"robust_score":r["robust_score"],
                "worst_auc_strength":r["worst_auc_strength"],
                "median_auc_strength":r["median_auc_strength"],
                "sign_consistency":r["sign_consistency"],
                **({"age_s":r["age_s"]} if r["kind"]=="STATIC" else
                   {"from_age_s":r["from_age_s"],"to_age_s":r["to_age_s"]})
            } for r in universal[side][:10]],
            "best_models":sorted([
                x for x in models[side].values() if x
            ],key=lambda x:(x["worst_auc"],x["mean_auc"]),reverse=True)[:3]
        }
    print("RELATIONSHIP_ATLAS="+json.dumps(concise,separators=(",",":")))


if __name__=="__main__":
    main()
