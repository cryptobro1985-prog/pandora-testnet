#!/usr/bin/env python3
from __future__ import annotations

import argparse,gzip,json,math
from collections import Counter,defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier,HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline


SEED=20261109
ANCHORS=(25,30,33,35,38,45,60)
SEVERITIES=(5.0,10.0,20.0,40.0)


def load_json_gz(path):
    with gzip.open(path,"rt",encoding="utf-8") as f:return json.load(f)


def load_jsonl_gz(path):
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip():yield json.loads(line)


def finite(v):
    return isinstance(v,(int,float,np.number)) and math.isfinite(float(v))


def finalized_labels(doc):
    rows=[dict(x) for x in (doc.get("strict") or []) if bool(x.get("reference_finalized",True))]
    rows.sort(key=lambda x:int(x["extreme_interval_start_ms"]))
    return rows


def split_labels(labels):
    n=len(labels)
    a=max(2,int(n*.60));b=max(a+2,int(n*.80))
    return {
        "train":{int(x["label_id"]) for x in labels[:a]},
        "valid":{int(x["label_id"]) for x in labels[a:b]},
        "oos":{int(x["label_id"]) for x in labels[b:]},
    }


def clean_features(raw):
    out={}
    for k,v in (raw or {}).items():
        if not finite(v):continue
        lk=str(k).lower()
        if any(x in lk for x in ("strict","label","future","target_","precision","recall")):
            continue
        # Candidate survival may help as a continuous causal feature, but it is
        # never used as a fixed eligibility clock.
        if lk=="age_s":
            out["candidate_survival_log_s"]=math.log1p(max(0.0,float(v)))
            continue
        out[str(k)]=float(v)
    return out


def prepare(rows,labels):
    byid={int(x["label_id"]):x for x in labels}
    out=[]
    for r in rows:
        if r.get("observation_kind")!="RETRACE_CROSS":continue
        anchor=r.get("retrace_anchor_bps")
        tid=r.get("target_label_id")
        if anchor not in ANCHORS or tid is None or int(tid) not in byid:continue
        side=str(r.get("side",""))
        if side not in ("LOW","HIGH"):continue
        f=clean_features(r.get("features") or {})
        if not f:continue
        target=byid[int(tid)]
        cp=float(r["extreme_price"]);tp=float(target["extreme_price"])
        cont=max(0.0,(cp/tp-1.0)*10000.0) if side=="LOW" else max(0.0,(tp/cp-1.0)*10000.0)
        out.append({
            **r,"features":f,
            "strict_true":bool(r.get("strict_label_id") is not None and int(r["strict_label_id"])==int(tid)),
            "continuation_bps":cont,
            "target_extreme_price":tp,
            "target_extreme_ts_ms":int(target["extreme_interval_start_ms"]),
        })
    return out


def names(rows):
    c=Counter(k for r in rows for k in r["features"])
    n=max(1,len(rows))
    return sorted(k for k,v in c.items() if v/n>=.35)


def matrix(rows,ns):
    return np.asarray([[r["features"].get(k,np.nan) for k in ns] for r in rows],dtype=float)


def make(kind):
    if kind=="extra":
        return Pipeline([
            ("impute",SimpleImputer(strategy="median",add_indicator=True)),
            ("model",ExtraTreesClassifier(
                n_estimators=600,max_depth=9,min_samples_leaf=5,
                max_features="sqrt",random_state=SEED,n_jobs=-1,
            ))
        ])
    return Pipeline([
        ("impute",SimpleImputer(strategy="median",add_indicator=True)),
        ("model",HistGradientBoostingClassifier(
            max_iter=260,learning_rate=.04,max_leaf_nodes=15,
            min_samples_leaf=10,l2_regularization=4.0,random_state=SEED,
        ))
    ])


def weights(rows,y):
    reps=Counter(r["candidate_id"] for r in rows)
    bycid={}
    for r,z in zip(rows,y):bycid[r["candidate_id"]]=bool(z)
    pos=sum(bycid.values());neg=len(bycid)-pos
    pw=min(15.0,max(1.0,neg/max(1,pos)));nw=min(5.0,max(1.0,pos/max(1,neg)))
    return np.asarray([((pw if z else nw)/max(1,reps[r["candidate_id"]])) for r,z in zip(rows,y)])


def fit(rows,ns,kind,y):
    yy=np.asarray(y,dtype=bool)
    if len(set(yy))<2:return None
    m=make(kind)
    m.fit(matrix(rows,ns),yy,model__sample_weight=weights(rows,yy))
    return m


def first_signal_metrics(rows,direct_p,risk_p,dth,rth):
    byep=defaultdict(list)
    for r,p,q in zip(rows,direct_p,risk_p):
        byep[int(r["target_label_id"])].append((
            int(r["snapshot_ts_ms"]),int(r["candidate_ts_ms"]),r,float(p),float(q)
        ))
    tp=fp=0;delay=[];false_cont=[];records=[]
    for tid,items in sorted(byep.items()):
        accepted=[z for z in items if z[3]>=dth and z[4]<=rth]
        if not accepted:continue
        _,_,r,p,q=min(accepted,key=lambda z:(z[0],z[1]))
        true=bool(r["strict_true"])
        if true:
            tp+=1
            delay.append(max(0.0,(int(r["snapshot_ts_ms"])-int(r["target_extreme_ts_ms"]))/1000.0))
        else:
            fp+=1;false_cont.append(float(r["continuation_bps"]))
        records.append({
            "target_label_id":tid,"candidate_id":r["candidate_id"],"side":r["side"],
            "anchor_bps":int(r["retrace_anchor_bps"]),
            "candidate_ts_ms":int(r["candidate_ts_ms"]),
            "signal_ts_ms":int(r["snapshot_ts_ms"]),
            "direct_probability":p,"continuation_risk":q,
            "true_first":true,"continuation_bps":float(r["continuation_bps"]),
        })
    n=tp+fp;episodes=len(byep)
    return {
        "episodes":episodes,"accepted_first":n,"true_first":tp,"false_first":fp,
        "precision":tp/n if n else None,"recall":tp/episodes if episodes else None,
        "coverage":n/episodes if episodes else None,
        "median_delay_s":float(np.median(delay)) if delay else None,
        "median_false_continuation_bps":float(np.median(false_cont)) if false_cont else None,
        "first_signals":records,
    }


def select(rows,dp,rp):
    best=None
    for dth in np.arange(.50,.991,.02):
        for rth in np.arange(.01,.501,.02):
            m=first_signal_metrics(rows,dp,rp,float(dth),float(rth))
            p=m["precision"] or 0.0;rc=m["recall"] or 0.0
            viable=m["true_first"]>=2 and rc>=.15
            sev=m["median_false_continuation_bps"]
            sev=1e9 if sev is None else sev
            delay=m["median_delay_s"]
            delay=1e9 if delay is None else delay
            key=(1 if viable else 0,p,rc,-m["false_first"],-sev,-delay)
            if best is None or key>best[0]:
                best=(key,float(dth),float(rth),m)
    return best[1],best[2],best[3],best[0]


def fit_anchor(allrows,split,side,anchor):
    sr=[r for r in allrows if r["side"]==side and int(r["retrace_anchor_bps"])==anchor]
    tr=[r for r in sr if int(r["target_label_id"]) in split["train"]]
    va=[r for r in sr if int(r["target_label_id"]) in split["valid"]]
    oo=[r for r in sr if int(r["target_label_id"]) in split["oos"]]
    if len(tr)<20 or len(va)<3 or len(oo)<3:
        return {"anchor_bps":anchor,"status":"insufficient_rows","rows":{"train":len(tr),"validation":len(va),"oos":len(oo)}}
    ns=names(tr)
    trials=[];best=None
    for dk in ("extra","hist"):
        direct=fit(tr,ns,dk,[r["strict_true"] for r in tr])
        if direct is None:continue
        dpv=direct.predict_proba(matrix(va,ns))[:,1]
        for rk in ("extra","hist"):
            for sev in SEVERITIES:
                risk=fit(tr,ns,rk,[r["continuation_bps"]>sev for r in tr])
                if risk is None:continue
                rpv=risk.predict_proba(matrix(va,ns))[:,1]
                dth,rth,vm,key=select(va,dpv,rpv)
                row={"direct_model":dk,"risk_model":rk,"severity_bps":sev,
                     "direct_threshold":dth,"risk_threshold":rth,
                     "validation":vm,"selection_key":list(key)}
                trials.append(row)
                if best is None or key>best[0]:
                    best=(key,dk,rk,sev,dth,rth,vm)
    if best is None:
        return {"anchor_bps":anchor,"status":"no_model","rows":{"train":len(tr),"validation":len(va),"oos":len(oo)}}
    _,dk,rk,sev,dth,rth,vm=best
    dev=tr+va;ns=names(dev)
    direct=fit(dev,ns,dk,[r["strict_true"] for r in dev])
    risk=fit(dev,ns,rk,[r["continuation_bps"]>sev for r in dev])
    dpo=direct.predict_proba(matrix(oo,ns))[:,1]
    rpo=risk.predict_proba(matrix(oo,ns))[:,1]
    om=first_signal_metrics(oo,dpo,rpo,dth,rth)
    return {
        "anchor_bps":anchor,"status":"ok",
        "direct_model":dk,"risk_model":rk,"severity_bps":sev,
        "direct_threshold":dth,"risk_threshold":rth,
        "validation":vm,"oos":om,
        "feature_count":len(ns),
        "rows":{"train":len(tr),"validation":len(va),"oos":len(oo)},
        "trials":trials,
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshots",type=Path,required=True)
    ap.add_argument("--labels-gz",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)

    labels=finalized_labels(load_json_gz(args.labels_gz))
    split=split_labels(labels)
    rows=prepare(list(load_jsonl_gz(args.snapshots)),labels)
    by_side={}
    for side in ("LOW","HIGH"):
        anchors=[fit_anchor(rows,split,side,a) for a in ANCHORS]
        eligible=[x for x in anchors if x.get("status")=="ok"]
        def rank(x):
            m=x["oos"]
            return (
                m["precision"] or 0.0,
                m["recall"] or 0.0,
                m["true_first"],
                -m["false_first"],
            )
        best=max(eligible,key=rank) if eligible else None
        by_side[side]={
            "best_anchor":best,
            "anchor_33":next((x for x in anchors if x["anchor_bps"]==33),None),
            "anchor_35":next((x for x in anchors if x["anchor_bps"]==35),None),
            "all_anchors":anchors,
        }

    report={
        "version":"HYPE-RETRACE-ANCHORED-RICH-SIGNATURE-v1",
        "teacher":"STRICT_L6_K2_REFERENCE_FINALIZED_ONLY",
        "candidate_contract":"DENSE_STRICT_SWING_RUNNING_EXTREME_V1",
        "anchor_role":"first retrace crossing is an event snapshot, not sufficient confirmation",
        "anchors_bps":list(ANCHORS),
        "rows":len(rows),
        "by_side":by_side,
        "real_orders":False,
    }
    (args.output/"HYPE_RETRACE_ANCHORED_RICH_SIGNATURE_REPORT.json").write_text(
        json.dumps(report,indent=2,ensure_ascii=False)+"\n"
    )
    print("RETRACE_RICH="+json.dumps({
        s:{
            "best":None if by_side[s]["best_anchor"] is None else {
                k:v for k,v in by_side[s]["best_anchor"].items() if k not in ("trials",)
            },
            "at33":None if by_side[s]["anchor_33"] is None else {
                k:v for k,v in by_side[s]["anchor_33"].items() if k not in ("trials",)
            },
            "at35":None if by_side[s]["anchor_35"] is None else {
                k:v for k,v in by_side[s]["anchor_35"].items() if k not in ("trials",)
            },
        } for s in ("LOW","HIGH")
    },separators=(",",":")))


if __name__=="__main__":main()
