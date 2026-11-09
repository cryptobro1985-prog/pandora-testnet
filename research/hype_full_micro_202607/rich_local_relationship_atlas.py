#!/usr/bin/env python3
from __future__ import annotations

import argparse,gzip,json,math
from collections import Counter,defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score,roc_auc_score
from sklearn.pipeline import Pipeline


def finite(v): return isinstance(v,(int,float,np.number)) and math.isfinite(float(v))


def load_jsonl(path):
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip(): yield json.loads(line)


def group(name):
    x=name.lower()
    if "book" in x or "bid_" in x or "ask_" in x or "spread" in x or "depth" in x:
        return "L50_BOOK"
    if "liq" in x or "liquidat" in x:
        return "LIQUIDATIONS"
    if "open_interest" in x or x.startswith("oi_") or "_oi_" in x:
        return "OPEN_INTEREST"
    if "mark" in x or "basis" in x or "funding" in x or "ticker" in x:
        return "MARK_BASIS_FUNDING"
    if "buy" in x or "sell" in x or "flow" in x or "trade" in x or "eff" in x:
        return "TRADE_FLOW_EFFICIENCY"
    if "ret_" in x or "return" in x or "retrace" in x or "range" in x or "volatility" in x:
        return "PRICE_RESPONSE"
    if "survival" in x or "attempt" in x or "proposal" in x:
        return "CANDIDATE_SURVIVAL"
    return "OTHER_CAUSAL"


def clean(raw):
    out={}
    for k,v in (raw or {}).items():
        if not finite(v): continue
        lk=str(k).lower()
        if any(z in lk for z in ("target_","strict_true","teacher","label_id","future")):
            continue
        if lk in ("delay_s","stage"):
            continue
        out[str(k)]=float(v)
    return out


def auc(y,x):
    y=np.asarray(y,dtype=int);x=np.asarray(x,dtype=float)
    ok=np.isfinite(x);y=y[ok];x=x[ok]
    if len(y)<12 or len(set(y))<2:return None
    try:return float(roc_auc_score(y,x))
    except:return None


def stat(rows,name):
    # Temporal quartiles by target labels make the relationship prove itself
    # throughout the rich period instead of one pooled coincidence.
    ids=sorted(set(int(r["target_label_id"]) for r in rows))
    if len(ids)<8:return None
    chunks=np.array_split(ids,4)
    folds=[]
    for ids_chunk in chunks:
        q=[r for r in rows if int(r["target_label_id"]) in set(map(int,ids_chunk))]
        vals=[];ys=[]
        for r in q:
            v=r["features"].get(name)
            if finite(v):vals.append(float(v));ys.append(int(r["strict_true"]))
        if sum(ys)<2 or len(ys)-sum(ys)<8:continue
        a=auc(ys,vals)
        if a is None:continue
        arr=np.asarray(vals); yy=np.asarray(ys)
        lo,hi=np.quantile(arr,[.25,.75]);scale=float(hi-lo) or float(np.std(arr)) or 1.0
        folds.append({
            "auc":a,"strength":abs(a-.5)*2,
            "direction":"HIGHER_AT_TRUE" if a>.5 else "LOWER_AT_TRUE",
            "median_gap_iqr":float((np.median(arr[yy==1])-np.median(arr[yy==0]))/scale),
            "true_n":int(yy.sum()),"false_n":int(len(yy)-yy.sum())
        })
    if len(folds)<2:return None
    dirs=[1 if x["auc"]>.5 else -1 for x in folds]
    strength=[x["strength"] for x in folds]
    return {
        "folds":folds,"fold_count":len(folds),
        "sign_consistency":abs(sum(dirs))/len(dirs),
        "worst_strength":min(strength),
        "median_strength":float(np.median(strength)),
        "robust_score":float(
            (len(folds)/4)*abs(sum(dirs))/len(dirs)*
            (0.65*min(strength)+0.35*np.median(strength))
        ),
    }


def relations(rows):
    names=sorted({k for r in rows for k in r["features"]})
    out=[]
    for name in names:
        s=stat(rows,name)
        if s is None:continue
        out.append({"feature":name,"family":group(name),**s})
    out.sort(key=lambda x:(x["robust_score"],x["worst_strength"]),reverse=True)
    return out


def transition_rows(rows,a,b):
    by=defaultdict(dict)
    for r in rows:
        anchor=r.get("retrace_anchor_bps")
        if anchor not in (a,b):continue
        by[r["candidate_id"]][int(anchor)]=r
    out=[]
    for cid,z in by.items():
        if a not in z or b not in z:continue
        fa,fb=z[a]["features"],z[b]["features"]
        d={f"DELTA__{k}":float(fb[k]-fa[k]) for k in fa.keys()&fb.keys() if finite(fa[k]) and finite(fb[k])}
        if d:
            out.append({
                "candidate_id":cid,"side":z[b]["side"],
                "target_label_id":z[b]["target_label_id"],
                "strict_true":bool(z[b]["strict_true"]),
                "features":d,
            })
    return out


def model_cv(rows,ranked):
    names=[x["feature"] for x in ranked if x["sign_consistency"]==1.0][:30]
    if len(names)<5:names=[x["feature"] for x in ranked[:20]]
    ids=sorted(set(int(r["target_label_id"]) for r in rows))
    chunks=np.array_split(ids,4)
    folds=[];imps=defaultdict(list)
    for ids_chunk in chunks:
        test_ids=set(map(int,ids_chunk))
        tr=[r for r in rows if int(r["target_label_id"]) not in test_ids]
        te=[r for r in rows if int(r["target_label_id"]) in test_ids]
        if not tr or not te:continue
        ytr=np.asarray([r["strict_true"] for r in tr],dtype=int)
        yte=np.asarray([r["strict_true"] for r in te],dtype=int)
        if min(np.bincount(ytr,minlength=2))<3 or min(np.bincount(yte,minlength=2))<2:continue
        Xtr=np.asarray([[r["features"].get(k,np.nan) for k in names] for r in tr])
        Xte=np.asarray([[r["features"].get(k,np.nan) for k in names] for r in te])
        m=Pipeline([
            ("impute",SimpleImputer(strategy="median",add_indicator=True)),
            ("model",ExtraTreesClassifier(
                n_estimators=600,max_depth=8,min_samples_leaf=6,max_features="sqrt",
                class_weight="balanced",random_state=20261109,n_jobs=-1
            ))
        ])
        m.fit(Xtr,ytr);p=m.predict_proba(Xte)[:,1]
        folds.append({
            "labels":sorted(test_ids),"rows":len(te),"true":int(yte.sum()),
            "auc":float(roc_auc_score(yte,p)),
            "average_precision":float(average_precision_score(yte,p))
        })
        imp=m.named_steps["model"].feature_importances_[:len(names)]
        for n,v in zip(names,imp):imps[n].append(float(v))
    if not folds:return None
    return {
        "features":names,
        "folds":folds,
        "mean_auc":float(np.mean([x["auc"] for x in folds])),
        "worst_auc":float(min(x["auc"] for x in folds)),
        "mean_average_precision":float(np.mean([x["average_precision"] for x in folds])),
        "importance":sorted([
            {"feature":k,"family":group(k),"mean_importance":float(np.mean(v))}
            for k,v in imps.items()
        ],key=lambda x:x["mean_importance"],reverse=True)
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshots",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True)

    raw=list(load_jsonl(args.snapshots))
    base=[]
    for r in raw:
        if "target_label_id" not in r:continue
        f=clean(r.get("features") or {})
        if not f:continue
        base.append({
            "candidate_id":r["candidate_id"],"side":r["side"],
            "target_label_id":int(r["target_label_id"]),
            "strict_true":bool(r.get("strict_true")),
            "observation_kind":r.get("observation_kind","TIME_SAMPLE"),
            "retrace_anchor_bps":r.get("retrace_anchor_bps"),
            "features":f,
        })

    report={"version":"HYPE-RICH-LOCAL-RELATIONSHIP-ATLAS-v1","by_side":{},"real_orders":False}
    for side in ("LOW","HIGH"):
        srows=[r for r in base if r["side"]==side]
        report["by_side"][side]={"anchors":{},"transitions":{}}
        for anchor in (25,30,33,35,38,45,60):
            q=[r for r in srows if r["observation_kind"]=="RETRACE_CROSS" and r["retrace_anchor_bps"]==anchor]
            rel=relations(q)
            report["by_side"][side]["anchors"][str(anchor)]={
                "rows":len(q),"relations":rel[:120],"model":model_cv(q,rel)
            }
        for a,b in ((25,30),(30,33),(33,35),(35,38),(38,45),(45,60)):
            q=transition_rows(srows,a,b)
            rel=relations(q)
            report["by_side"][side]["transitions"][f"{a}->{b}"]={
                "rows":len(q),"relations":rel[:120],"model":model_cv(q,rel)
            }

    args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    concise={}
    for side in ("LOW","HIGH"):
        best=[]
        for anchor,x in report["by_side"][side]["anchors"].items():
            if x["relations"]:
                r=x["relations"][0]
                best.append((r["robust_score"],f"anchor_{anchor}",r))
        for tr,x in report["by_side"][side]["transitions"].items():
            if x["relations"]:
                r=x["relations"][0]
                best.append((r["robust_score"],f"transition_{tr}",r))
        best.sort(reverse=True,key=lambda z:z[0])
        concise[side]=[
            {"context":ctx,"feature":r["feature"],"family":r["family"],
             "robust_score":r["robust_score"],"worst_strength":r["worst_strength"],
             "sign_consistency":r["sign_consistency"]}
            for _,ctx,r in best[:10]
        ]
    print("RICH_RELATIONSHIP_ATLAS="+json.dumps(concise,separators=(",",":")))


if __name__=="__main__":main()
