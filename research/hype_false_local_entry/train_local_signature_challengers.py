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

TRAIN_END=int(datetime(2026,10,23,tzinfo=timezone.utc).timestamp()*1000)
OOS_START=int(datetime(2026,10,27,tzinfo=timezone.utc).timestamp()*1000)
STAGES={60,180,300}


def load_rows(path):
    with gzip.open(path,"rt",encoding="utf-8") as fh:
        for line in fh:
            if line.strip(): yield json.loads(line)


def load_labels(path):
    with gzip.open(path,"rt",encoding="utf-8") as fh:
        doc=json.load(fh)
    rows=[dict(x) for x in (doc.get("strict") or []) if bool(x.get("reference_finalized",True))]
    rows.sort(key=lambda x:int(x["extreme_interval_start_ms"]))
    return rows


def clean_features(raw):
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


def prepare(rows, finalized_ids):
    out=[]
    for r in rows:
        if r.get("side") not in ("LOW","HIGH") or int(r.get("delay_s",-1)) not in STAGES:
            continue
        f=clean_features(r.get("features") or {})
        if not f: continue
        lid=r.get("strict_label_id")
        y=bool(lid is not None and int(lid) in finalized_ids)
        out.append({**r,"features":f,"strict_true":y})
    return out


def feature_names(rows, min_support=25):
    c=Counter(k for r in rows for k in r["features"])
    return sorted(k for k,n in c.items() if n>=min_support)


def matrix(rows,names):
    return np.asarray([[r["features"].get(k,np.nan) for k in names] for r in rows],dtype=float)


def weights(rows):
    repeats=Counter(r["candidate_id"] for r in rows)
    candidate_y={}
    for r in rows: candidate_y[r["candidate_id"]]=bool(r["strict_true"])
    pos=sum(candidate_y.values()); neg=len(candidate_y)-pos
    pos_w=min(12.0,max(1.0,neg/max(1,pos)))
    return np.asarray([
        (pos_w if r["strict_true"] else 1.0)/max(1,repeats[r["candidate_id"]])
        for r in rows
    ],dtype=float)


def configs():
    out=[]
    for c in (0.05,0.2,1.0):
        out.append((f"logit_C{c}",Pipeline([
            ("impute",SimpleImputer(strategy="median",add_indicator=True)),
            ("scale",StandardScaler()),
            ("model",LogisticRegression(C=c,max_iter=1200,solver="lbfgs")),
        ])))
    for depth,leaf,frac in ((4,5,"sqrt"),(6,5,"sqrt"),(8,8,.5),(None,12,"sqrt")):
        out.append((f"extra_d{depth}_l{leaf}_f{frac}",Pipeline([
            ("impute",SimpleImputer(strategy="median",add_indicator=True)),
            ("model",ExtraTreesClassifier(
                n_estimators=350,max_depth=depth,min_samples_leaf=leaf,
                max_features=frac,random_state=611,n_jobs=-1,
            )),
        ])))
    for leaves,minleaf,l2,lr in ((7,12,2.0,.05),(15,12,5.0,.05),(15,8,2.0,.03)):
        out.append((f"hist_L{leaves}_m{minleaf}_l2{l2}_lr{lr}",Pipeline([
            ("impute",SimpleImputer(strategy="median",add_indicator=True)),
            ("model",HistGradientBoostingClassifier(
                max_iter=220,learning_rate=lr,max_leaf_nodes=leaves,
                min_samples_leaf=minleaf,l2_regularization=l2,random_state=611,
            )),
        ])))
    return out


def accepted_signals(rows, probs, th):
    by=defaultdict(list)
    for r,p in zip(rows,probs):
        by[r["candidate_id"]].append((int(r.get("snapshot_ts_ms",r["candidate_ts_ms"])),r,float(p)))
    out=[]
    for cid,items in by.items():
        for ts,r,p in sorted(items):
            if p>=th:
                out.append({
                    "candidate_id":cid,"side":r["side"],"candidate_ts_ms":int(r["candidate_ts_ms"]),
                    "signal_ts_ms":ts,"strict_label_id":r.get("strict_label_id"),
                    "strict_true":bool(r["strict_true"]),"probability":p,
                })
                break
    return out


def episode_metrics(rows, probs, th, labels, side, start_ms, end_ms):
    sigs=accepted_signals(rows,probs,th)
    episodes=[]
    for i in range(1,len(labels)-1):
        prev,target,nxt=labels[i-1],labels[i],labels[i+1]
        t=int(target["extreme_interval_start_ms"])
        if target["side"]!=side or not (start_ms<=t<end_ms): continue
        episodes.append((prev,target,nxt))

    true_first=false_first=0;delays=[];records=[]
    for prev,target,nxt in episodes:
        left=int(prev["extreme_interval_start_ms"])
        deadline=int(nxt["extreme_interval_start_ms"])
        eligible=[
            s for s in sigs
            if s["side"]==side and left<int(s["candidate_ts_ms"])<deadline and int(s["signal_ts_ms"])<deadline
        ]
        if not eligible: continue
        first=min(eligible,key=lambda s:(s["signal_ts_ms"],s["candidate_ts_ms"]))
        true=first.get("strict_label_id") is not None and int(first["strict_label_id"])==int(target["label_id"])
        if true:
            true_first+=1
            delays.append(max(0.0,(first["signal_ts_ms"]-int(target["extreme_interval_start_ms"]))/1000.0))
        else:false_first+=1
        records.append({**first,"target_label_id":int(target["label_id"]),"true_first":bool(true)})

    accepted=true_first+false_first
    return {
        "episodes":len(episodes),"accepted_first":accepted,
        "true_first":true_first,"false_first":false_first,
        "precision":true_first/accepted if accepted else None,
        "recall":true_first/len(episodes) if episodes else None,
        "coverage":accepted/len(episodes) if episodes else None,
        "median_delay_s":float(np.median(delays)) if delays else None,
        "first_signals":records,
    }


def choose_threshold(rows,probs,labels,side,start,end):
    best=None
    for i in range(500,1000):
        th=i/1000
        m=episode_metrics(rows,probs,th,labels,side,start,end)
        p=m["precision"] or 0.0;r=m["recall"] or 0.0
        viable=(m["true_first"]>=2 and m["accepted_first"]>=2 and r>=0.20)
        delay=m["median_delay_s"] if m["median_delay_s"] is not None else 1e9
        key=(1 if viable else 0,p,r,-m["false_first"],-delay,th)
        if best is None or key>best[0]: best=(key,th,m)
    return best[1],best[2]


def fit_side(all_rows,labels,side):
    rows=[r for r in all_rows if r["side"]==side]
    train=[r for r in rows if int(r["candidate_ts_ms"])<TRAIN_END]
    valid=[r for r in rows if TRAIN_END<=int(r["candidate_ts_ms"])<OOS_START]
    oos=[r for r in rows if int(r["candidate_ts_ms"])>=OOS_START]
    names=feature_names(train)
    xtr=matrix(train,names);ytr=np.asarray([bool(r["strict_true"]) for r in train])
    w=weights(train)

    valid_start=TRAIN_END;valid_end=OOS_START
    oos_end=max([int(x["extreme_interval_start_ms"]) for x in labels]+[OOS_START+1])+1

    trials=[]
    fitted=[]
    for name,pipe in configs():
        pipe.fit(xtr,ytr,model__sample_weight=w)
        vp=pipe.predict_proba(matrix(valid,names))[:,1] if valid else np.asarray([])
        th,vm=choose_threshold(valid,vp,labels,side,valid_start,valid_end)
        key=(1 if (vm["true_first"]>=2 and (vm["precision"] or 0)>=0.50) else 0,
             vm["precision"] or 0,vm["recall"] or 0,-vm["false_first"])
        trials.append({"name":name,"threshold":th,"validation":vm,"selection_key":list(key)})
        fitted.append((key,name,th,pipe))

    fitted.sort(key=lambda z:z[0],reverse=True)
    key,name,th,champ=fitted[0]
    op=champ.predict_proba(matrix(oos,names))[:,1] if oos else np.asarray([])
    om=episode_metrics(oos,op,th,labels,side,OOS_START,oos_end)
    tp=champ.predict_proba(xtr)[:,1]
    tm=episode_metrics(train,tp,th,labels,side,min(r["candidate_ts_ms"] for r in train),TRAIN_END)
    return {
        "name":name,"threshold":th,"feature_names":names,"pipeline":champ,
        "train":tm,"validation":next(x["validation"] for x in trials if x["name"]==name),
        "oos":om,"trials":trials,
        "rows":{"train":len(train),"validation":len(valid),"oos":len(oos)},
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshots",type=Path,required=True)
    ap.add_argument("--labels-gz",type=Path,required=True)
    ap.add_argument("--model-out",type=Path,required=True)
    ap.add_argument("--report-out",type=Path,required=True)
    args=ap.parse_args()

    labels=load_labels(args.labels_gz)
    ids={int(x["label_id"]) for x in labels}
    rows=prepare(list(load_rows(args.snapshots)),ids)
    sides={side:fit_side(rows,labels,side) for side in ("LOW","HIGH")}

    champion=FrozenSignatureChampion(
        feature_names={s:sides[s]["feature_names"] for s in sides},
        pipelines={s:sides[s]["pipeline"] for s in sides},
        thresholds={s:sides[s]["threshold"] for s in sides},
        metadata={
            "teacher":"STRICT_L6_K2_REFERENCE_FINALIZED_ONLY",
            "candidate_age_removed":True,
            "selection":"validation first-signal precision/recall; OOS untouched",
            "selected_model":{s:sides[s]["name"] for s in sides},
        },
    )
    report={
        "version":champion.version,"teacher":"STRICT_L6_K2_REFERENCE_FINALIZED_ONLY",
        "candidate_age_removed":True,"rows":len(rows),
        "by_side":{
            s:{k:v for k,v in sides[s].items() if k not in ("pipeline","feature_names")}
            | {"feature_count":len(sides[s]["feature_names"])}
            for s in sides
        },
        "real_orders":False,
    }
    args.model_out.parent.mkdir(parents=True,exist_ok=True)
    with args.model_out.open("wb") as fh:pickle.dump(champion,fh,pickle.HIGHEST_PROTOCOL)
    args.report_out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("LOCAL_SIGNATURE_CHALLENGER="+json.dumps(report,separators=(",",":")))


if __name__=="__main__":
    main()
