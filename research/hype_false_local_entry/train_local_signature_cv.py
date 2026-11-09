#!/usr/bin/env python3
from __future__ import annotations

import argparse,gzip,json,math,pickle
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier,HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from research.hype_false_local_entry.frozen_signature_champion import FrozenSignatureChampion

def ms(y,m,d): return int(datetime(y,m,d,tzinfo=timezone.utc).timestamp()*1000)
OOS_START=ms(2026,10,27)
FOLDS=[
    (ms(2026,10,4),ms(2026,10,14),ms(2026,10,18)),
    (ms(2026,10,4),ms(2026,10,18),ms(2026,10,22)),
    (ms(2026,10,4),ms(2026,10,22),OOS_START),
]
CV_START=FOLDS[0][1]
STAGES={60,180,300}


def load_rows(path):
    with gzip.open(path,"rt",encoding="utf-8") as fh:
        for line in fh:
            if line.strip(): yield json.loads(line)


def load_labels(path):
    with gzip.open(path,"rt",encoding="utf-8") as fh: doc=json.load(fh)
    rows=[dict(x) for x in (doc.get("strict") or []) if bool(x.get("reference_finalized",True))]
    rows.sort(key=lambda x:int(x["extreme_interval_start_ms"]))
    return rows


def clean_features(raw):
    out={}
    for k,v in (raw or {}).items():
        if not isinstance(v,(int,float)) or not math.isfinite(float(v)): continue
        lk=str(k).lower()
        if lk in {"delay_s","candidate_age_s","elapsed_s","stage"}: continue
        if lk.startswith("target_") or "strict_true" in lk or "label" in lk: continue
        if lk=="age_s":
            # Point 37: survival without same-side extension. Continuous
            # evidence only; it never gates decision eligibility.
            out["candidate_survival_log_s"]=math.log1p(max(0.0,float(v)))
            continue
        out[str(k)]=float(v)
    retr=out.get("retrace_bps")
    surv=out.get("candidate_survival_log_s")
    if retr is not None and surv is not None:
        out["survival_x_retrace"]=surv*retr
    return out


def prepare(rows,ids):
    out=[]
    for r in rows:
        if r.get("side") not in ("LOW","HIGH") or int(r.get("delay_s",-1)) not in STAGES: continue
        f=clean_features(r.get("features") or {})
        if not f:continue
        lid=r.get("strict_label_id")
        out.append({**r,"features":f,"strict_true":bool(lid is not None and int(lid) in ids)})
    return out


def feature_names(rows,min_support=20):
    c=Counter(k for r in rows for k in r["features"])
    return sorted(k for k,n in c.items() if n>=min_support)


def matrix(rows,names):
    return np.asarray([[r["features"].get(k,np.nan) for k in names] for r in rows],dtype=float)


def row_weights(rows):
    repeats=Counter(r["candidate_id"] for r in rows)
    cy={}
    for r in rows: cy[r["candidate_id"]]=bool(r["strict_true"])
    pos=sum(cy.values());neg=len(cy)-pos
    pw=min(12.0,max(1.0,neg/max(1,pos)))
    return np.asarray([(pw if r["strict_true"] else 1.0)/repeats[r["candidate_id"]] for r in rows])


def make_model(spec):
    fam,p=spec
    if fam=="logit":
        return Pipeline([
            ("impute",SimpleImputer(strategy="median",add_indicator=True)),
            ("scale",StandardScaler()),
            ("model",LogisticRegression(C=p,max_iter=1200,solver="lbfgs")),
        ])
    if fam=="extra":
        depth,leaf,frac=p
        return Pipeline([
            ("impute",SimpleImputer(strategy="median",add_indicator=True)),
            ("model",ExtraTreesClassifier(n_estimators=350,max_depth=depth,min_samples_leaf=leaf,
                                           max_features=frac,random_state=611,n_jobs=-1)),
        ])
    leaves,minleaf,l2,lr=p
    return Pipeline([
        ("impute",SimpleImputer(strategy="median",add_indicator=True)),
        ("model",HistGradientBoostingClassifier(max_iter=220,learning_rate=lr,max_leaf_nodes=leaves,
                                                  min_samples_leaf=minleaf,l2_regularization=l2,
                                                  random_state=611)),
    ])


SPECS=[
    ("logit",0.05),("logit",0.2),("logit",1.0),
    ("extra",(4,5,"sqrt")),("extra",(6,8,"sqrt")),("extra",(8,10,.5)),
    ("hist",(7,12,2.0,.05)),("hist",(15,12,5.0,.05)),("hist",(15,8,2.0,.03)),
]


def spec_name(spec):
    return spec[0]+"_"+str(spec[1]).replace(" ","")


def accepted_signals(rows,probs,th):
    by=defaultdict(list)
    for r,p in zip(rows,probs):
        by[r["candidate_id"]].append((int(r.get("snapshot_ts_ms",r["candidate_ts_ms"])),r,float(p)))
    out=[]
    for cid,items in by.items():
        for ts,r,p in sorted(items):
            if p>=th:
                out.append({"candidate_id":cid,"side":r["side"],"candidate_ts_ms":int(r["candidate_ts_ms"]),
                            "signal_ts_ms":ts,"strict_label_id":r.get("strict_label_id"),
                            "strict_true":bool(r["strict_true"]),"probability":p})
                break
    return out


def episode_metrics(rows,probs,th,labels,side,start,end):
    sigs=accepted_signals(rows,probs,th)
    eps=[]
    for i in range(1,len(labels)-1):
        prev,target,nxt=labels[i-1],labels[i],labels[i+1]
        t=int(target["extreme_interval_start_ms"])
        if target["side"]==side and start<=t<end:eps.append((prev,target,nxt))
    tp=fp=0;delays=[];records=[]
    for prev,target,nxt in eps:
        left=int(prev["extreme_interval_start_ms"]);deadline=int(nxt["extreme_interval_start_ms"])
        candidates=[s for s in sigs if s["side"]==side and left<int(s["candidate_ts_ms"])<deadline and int(s["signal_ts_ms"])<deadline]
        if not candidates:continue
        first=min(candidates,key=lambda z:(z["signal_ts_ms"],z["candidate_ts_ms"]))
        true=first.get("strict_label_id") is not None and int(first["strict_label_id"])==int(target["label_id"])
        if true:
            tp+=1;delays.append(max(0.0,(first["signal_ts_ms"]-int(target["extreme_interval_start_ms"]))/1000))
        else:fp+=1
        records.append({**first,"target_label_id":int(target["label_id"]),"true_first":bool(true)})
    n=tp+fp
    return {"episodes":len(eps),"accepted_first":n,"true_first":tp,"false_first":fp,
            "precision":tp/n if n else None,"recall":tp/len(eps) if eps else None,
            "coverage":n/len(eps) if eps else None,
            "median_delay_s":float(np.median(delays)) if delays else None,
            "first_signals":records}


def choose_threshold(rows,probs,labels,side,start,end):
    best=None
    for i in range(500,1000):
        th=i/1000
        m=episode_metrics(rows,probs,th,labels,side,start,end)
        p=m["precision"] or 0;r=m["recall"] or 0
        viable=m["true_first"]>=3 and r>=0.20
        delay=m["median_delay_s"] if m["median_delay_s"] is not None else 1e9
        key=(1 if viable else 0,p,r,-m["false_first"],-delay,th)
        if best is None or key>best[0]:best=(key,th,m)
    return best[1],best[2]


def oof_for_spec(rows,side,spec):
    all_rows=[];all_probs=[]
    fold_reports=[]
    for tr_start,tr_end,va_end in FOLDS:
        train=[r for r in rows if r["side"]==side and tr_start<=int(r["candidate_ts_ms"])<tr_end]
        valid=[r for r in rows if r["side"]==side and tr_end<=int(r["candidate_ts_ms"])<va_end]
        if not train or not valid:continue
        names=feature_names(train)
        model=make_model(spec)
        model.fit(matrix(train,names),np.asarray([r["strict_true"] for r in train]),model__sample_weight=row_weights(train))
        p=model.predict_proba(matrix(valid,names))[:,1]
        all_rows.extend(valid);all_probs.extend(map(float,p))
        fold_reports.append({"train":[tr_start,tr_end],"valid":[tr_end,va_end],"train_rows":len(train),"valid_rows":len(valid)})
    return all_rows,np.asarray(all_probs),fold_reports


def fit_side(rows,labels,side):
    trials=[]
    best=None
    for spec in SPECS:
        vr,vp,folds=oof_for_spec(rows,side,spec)
        th,cv=choose_threshold(vr,vp,labels,side,CV_START,OOS_START)
        key=(1 if cv["true_first"]>=3 else 0,cv["precision"] or 0,cv["recall"] or 0,-cv["false_first"])
        trial={"name":spec_name(spec),"spec":spec,"threshold":th,"cv":cv,"folds":folds,"selection_key":list(key)}
        trials.append(trial)
        if best is None or key>best[0]:best=(key,spec,th,cv)

    _,spec,th,cv=best
    pre=[r for r in rows if r["side"]==side and int(r["candidate_ts_ms"])<OOS_START]
    oos=[r for r in rows if r["side"]==side and int(r["candidate_ts_ms"])>=OOS_START]
    names=feature_names(pre)
    model=make_model(spec)
    model.fit(matrix(pre,names),np.asarray([r["strict_true"] for r in pre]),model__sample_weight=row_weights(pre))
    op=model.predict_proba(matrix(oos,names))[:,1]
    end=max(int(x["extreme_interval_start_ms"]) for x in labels)+1
    om=episode_metrics(oos,op,th,labels,side,OOS_START,end)
    return {"name":spec_name(spec),"spec":spec,"threshold":th,"cv":cv,"oos":om,
            "trials":trials,"feature_names":names,"pipeline":model,
            "rows":{"pre_oos":len(pre),"oos":len(oos)}}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshots",type=Path,required=True)
    ap.add_argument("--labels-gz",type=Path,required=True)
    ap.add_argument("--model-out",type=Path,required=True)
    ap.add_argument("--report-out",type=Path,required=True)
    args=ap.parse_args()
    labels=load_labels(args.labels_gz);ids={int(x["label_id"]) for x in labels}
    rows=prepare(list(load_rows(args.snapshots)),ids)
    sides={s:fit_side(rows,labels,s) for s in ("LOW","HIGH")}
    champ=FrozenSignatureChampion(
        feature_names={s:sides[s]["feature_names"] for s in sides},
        pipelines={s:sides[s]["pipeline"] for s in sides},
        thresholds={s:sides[s]["threshold"] for s in sides},
        metadata={"teacher":"STRICT_L6_K2_REFERENCE_FINALIZED_ONLY",
                  "selection":"3 expanding chronological CV folds; untouched OOS",
                  "candidate_survival":"continuous log feature, never a fixed time gate",
                  "selected_model":{s:sides[s]["name"] for s in sides}},
        version="HYPE-LOCAL-SIGNATURE-FROZEN-CHAMPION-v2-CV",
    )
    report={"version":champ.version,"rows":len(rows),"candidate_survival_is_feature_not_gate":True,
            "by_side":{s:{k:v for k,v in sides[s].items() if k not in ("feature_names","pipeline")}
                       | {"feature_count":len(sides[s]["feature_names"])} for s in sides},
            "real_orders":False}
    args.model_out.parent.mkdir(parents=True,exist_ok=True)
    with args.model_out.open("wb") as fh:pickle.dump(champ,fh,pickle.HIGHEST_PROTOCOL)
    args.report_out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("LOCAL_SIGNATURE_CV="+json.dumps(report,separators=(",",":")))


if __name__=="__main__":main()
