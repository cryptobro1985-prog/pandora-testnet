#!/usr/bin/env python3
from __future__ import annotations

import argparse,gzip,json,math,pickle
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier,HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from research.hype_false_local_entry.frozen_signature_champion import FrozenSignatureChampion

def ms(y,m,d):return int(datetime(y,m,d,tzinfo=timezone.utc).timestamp()*1000)
OOS_START=ms(2026,10,27)
FOLDS=[
    (ms(2026,10,4),ms(2026,10,14),ms(2026,10,18)),
    (ms(2026,10,4),ms(2026,10,18),ms(2026,10,22)),
    (ms(2026,10,4),ms(2026,10,22),OOS_START),
]
CV_START=FOLDS[0][1]
STAGES={60,180,300}
SEVERITY_BPS=(5.0,10.0,20.0,40.0,80.0)


def load_rows(path):
    with gzip.open(path,"rt",encoding="utf-8") as fh:
        for line in fh:
            if line.strip():yield json.loads(line)


def load_labels(path):
    with gzip.open(path,"rt",encoding="utf-8") as fh:doc=json.load(fh)
    x=[dict(r) for r in (doc.get("strict") or []) if bool(r.get("reference_finalized",True))]
    x.sort(key=lambda r:int(r["extreme_interval_start_ms"]))
    return x


def clean_features(raw):
    out={}
    for k,v in (raw or {}).items():
        if not isinstance(v,(int,float)) or not math.isfinite(float(v)):continue
        lk=str(k).lower()
        if lk in {"delay_s","candidate_age_s","elapsed_s","stage"}:continue
        if lk.startswith("target_") or "strict_true" in lk or "label" in lk:continue
        if lk=="age_s":
            out["candidate_survival_log_s"]=math.log1p(max(0.0,float(v)));continue
        out[str(k)]=float(v)
    if "retrace_bps" in out and "candidate_survival_log_s" in out:
        out["survival_x_retrace"]=out["retrace_bps"]*out["candidate_survival_log_s"]
    return out


def episode_for_candidate(ts,side,labels):
    for i in range(1,len(labels)-1):
        prev,target,nxt=labels[i-1],labels[i],labels[i+1]
        if target["side"]!=side:continue
        left=int(prev["extreme_interval_start_ms"])
        terminal_end=int(target["extreme_interval_end_ms"])
        if left<int(ts)<=terminal_end:return prev,target,nxt
    return None


def prepare(rows,labels):
    finalized={int(x["label_id"]) for x in labels}
    out=[]
    for r in rows:
        side=r.get("side")
        if side not in ("LOW","HIGH") or int(r.get("delay_s",-1)) not in STAGES:continue
        ep=episode_for_candidate(int(r["candidate_ts_ms"]),side,labels)
        if ep is None:continue
        prev,target,nxt=ep
        cp=float(r["extreme_price"]);tp=float(target["extreme_price"])
        cont=max(0.0,(cp/tp-1)*10000.0) if side=="LOW" else max(0.0,(tp/cp-1)*10000.0)
        f=clean_features(r.get("features") or {})
        if not f:continue
        lid=r.get("strict_label_id")
        true=bool(lid is not None and int(lid) in finalized and int(lid)==int(target["label_id"]))
        out.append({**r,"features":f,"strict_true":true,
                    "target_label_id":int(target["label_id"]),"continuation_bps":cont})
    return out


def names(rows):
    c=Counter(k for r in rows for k in r["features"])
    return sorted(k for k,n in c.items() if n>=20)


def matrix(rows,ns):
    return np.asarray([[r["features"].get(k,np.nan) for k in ns] for r in rows],dtype=float)


def weights(rows,ys):
    reps=Counter(r["candidate_id"] for r in rows)
    cy={}
    for r,y in zip(rows,ys):cy[r["candidate_id"]]=bool(y)
    pos=sum(cy.values());neg=len(cy)-pos
    posw=min(8.0,max(1.0,neg/max(1,pos)));negw=min(8.0,max(1.0,pos/max(1,neg)))
    return np.asarray([((posw if y else negw)/reps[r["candidate_id"]]) for r,y in zip(rows,ys)])


SPECS=[
 ("extra",(5,6,"sqrt")),("extra",(7,10,.5)),
 ("hist",(7,12,2.0,.05)),("hist",(15,10,4.0,.04)),
]
def make(spec):
    fam,p=spec
    if fam=="extra":
        d,l,f=p
        return Pipeline([("impute",SimpleImputer(strategy="median",add_indicator=True)),
                         ("model",ExtraTreesClassifier(n_estimators=400,max_depth=d,min_samples_leaf=l,
                                                      max_features=f,random_state=712,n_jobs=-1))])
    leaves,ml,l2,lr=p
    return Pipeline([("impute",SimpleImputer(strategy="median",add_indicator=True)),
                     ("model",HistGradientBoostingClassifier(max_iter=220,learning_rate=lr,
                                                              max_leaf_nodes=leaves,min_samples_leaf=ml,
                                                              l2_regularization=l2,random_state=712))])
def sname(s):return s[0]+"_"+str(s[1]).replace(" ","")


def accepted(rows,risks,gate):
    by=defaultdict(list)
    for r,p in zip(rows,risks):
        by[r["candidate_id"]].append((int(r.get("snapshot_ts_ms",r["candidate_ts_ms"])),r,float(p)))
    out=[]
    for cid,items in by.items():
        for ts,r,p in sorted(items):
            if p<=gate:
                out.append({"candidate_id":cid,"side":r["side"],"candidate_ts_ms":int(r["candidate_ts_ms"]),
                            "signal_ts_ms":ts,"strict_label_id":r.get("strict_label_id"),
                            "target_label_id":int(r["target_label_id"]),"strict_true":bool(r["strict_true"]),
                            "risk":p,"continuation_bps":float(r["continuation_bps"])})
                break
    return out


def metrics(rows,risks,gate,labels,side,start,end):
    sigs=accepted(rows,risks,gate)
    eps=[]
    for i in range(1,len(labels)-1):
        prev,target,nxt=labels[i-1],labels[i],labels[i+1]
        t=int(target["extreme_interval_start_ms"])
        if target["side"]==side and start<=t<end:eps.append((prev,target,nxt))
    tp=fp=0;delay=[];false_cont=[];recs=[]
    for prev,target,nxt in eps:
        left=int(prev["extreme_interval_start_ms"]);deadline=int(nxt["extreme_interval_start_ms"])
        ss=[s for s in sigs if s["side"]==side and left<s["candidate_ts_ms"]<deadline and s["signal_ts_ms"]<deadline]
        if not ss:continue
        first=min(ss,key=lambda z:(z["signal_ts_ms"],z["candidate_ts_ms"]))
        true=first.get("strict_label_id") is not None and int(first["strict_label_id"])==int(target["label_id"])
        if true:
            tp+=1;delay.append(max(0.0,(first["signal_ts_ms"]-int(target["extreme_interval_start_ms"]))/1000))
        else:
            fp+=1;false_cont.append(first["continuation_bps"])
        recs.append({**first,"true_first":bool(true)})
    n=tp+fp
    return {"episodes":len(eps),"accepted_first":n,"true_first":tp,"false_first":fp,
            "precision":tp/n if n else None,"recall":tp/len(eps) if eps else None,
            "coverage":n/len(eps) if eps else None,
            "median_delay_s":float(np.median(delay)) if delay else None,
            "false_continuation_bps_median":float(np.median(false_cont)) if false_cont else None,
            "first_signals":recs}


def oof(rows,side,spec,severity):
    allr=[];allp=[]
    folds=[]
    for a,b,c in FOLDS:
        tr=[r for r in rows if r["side"]==side and a<=int(r["candidate_ts_ms"])<b]
        va=[r for r in rows if r["side"]==side and b<=int(r["candidate_ts_ms"])<c]
        if not tr or not va:continue
        ns=names(tr);y=np.asarray([r["continuation_bps"]>severity for r in tr])
        if len(set(y))<2:continue
        model=make(spec);model.fit(matrix(tr,ns),y,model__sample_weight=weights(tr,y))
        p=model.predict_proba(matrix(va,ns))[:,1]
        allr.extend(va);allp.extend(map(float,p))
        folds.append({"train":[a,b],"valid":[b,c],"train_rows":len(tr),"valid_rows":len(va)})
    return allr,np.asarray(allp),folds


def choose_gate(rows,risks,labels,side):
    best=None
    for i in range(1,501):
        gate=i/1000
        m=metrics(rows,risks,gate,labels,side,CV_START,OOS_START)
        p=m["precision"] or 0;r=m["recall"] or 0
        viable=m["true_first"]>=3 and r>=0.20
        fc=m["false_continuation_bps_median"] if m["false_continuation_bps_median"] is not None else 1e9
        key=(1 if viable else 0,p,r,-m["false_first"],-fc)
        if best is None or key>best[0]:best=(key,gate,m)
    return best[1],best[2],best[0]


def fit_side(rows,labels,side):
    trials=[];best=None
    for sev in SEVERITY_BPS:
        for spec in SPECS:
            vr,vp,folds=oof(rows,side,spec,sev)
            if not len(vr):continue
            gate,cv,key=choose_gate(vr,vp,labels,side)
            row={"severity_bps":sev,"model":sname(spec),"spec":spec,"risk_gate":gate,
                 "cv":cv,"folds":folds,"selection_key":list(key)}
            trials.append(row)
            if best is None or key>best[0]:best=(key,sev,spec,gate,cv)
    _,sev,spec,gate,cv=best
    pre=[r for r in rows if r["side"]==side and int(r["candidate_ts_ms"])<OOS_START]
    oo=[r for r in rows if r["side"]==side and int(r["candidate_ts_ms"])>=OOS_START]
    ns=names(pre);y=np.asarray([r["continuation_bps"]>sev for r in pre])
    model=make(spec);model.fit(matrix(pre,ns),y,model__sample_weight=weights(pre,y))
    p=model.predict_proba(matrix(oo,ns))[:,1]
    end=max(int(x["extreme_interval_start_ms"]) for x in labels)+1
    om=metrics(oo,p,gate,labels,side,OOS_START,end)
    return {"severity_bps":sev,"model":sname(spec),"risk_gate":gate,"cv":cv,"oos":om,
            "trials":trials,"feature_names":ns,"pipeline":model}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshots",type=Path,required=True)
    ap.add_argument("--labels-gz",type=Path,required=True)
    ap.add_argument("--model-out",type=Path,required=True)
    ap.add_argument("--report-out",type=Path,required=True)
    args=ap.parse_args()
    labels=load_labels(args.labels_gz)
    rows=prepare(list(load_rows(args.snapshots)),labels)
    sides={s:fit_side(rows,labels,s) for s in ("LOW","HIGH")}
    # Bundle exposes probability as P(continuation risk). Consumer must compare
    # <= threshold, unlike terminal-probability champion.
    champ=FrozenSignatureChampion(
        feature_names={s:sides[s]["feature_names"] for s in sides},
        pipelines={s:sides[s]["pipeline"] for s in sides},
        thresholds={s:sides[s]["risk_gate"] for s in sides},
        metadata={"mode":"CONTINUATION_RISK_VETO","probability_semantics":"P(continuation_bps > severity)",
                  "severity_bps":{s:sides[s]["severity_bps"] for s in sides},
                  "selected_model":{s:sides[s]["model"] for s in sides},
                  "selection":"rolling CV first-signal precision; OOS untouched"},
        version="HYPE-LOCAL-CONTINUATION-RISK-v1",
    )
    report={"version":champ.version,"rows":len(rows),
            "by_side":{s:{k:v for k,v in sides[s].items() if k not in ("feature_names","pipeline")}
                       | {"feature_count":len(sides[s]["feature_names"])} for s in sides},
            "real_orders":False}
    args.model_out.parent.mkdir(parents=True,exist_ok=True)
    with args.model_out.open("wb") as f:pickle.dump(champ,f,pickle.HIGHEST_PROTOCOL)
    args.report_out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    print("CONTINUATION_RISK="+json.dumps(report,separators=(",",":")))


if __name__=="__main__":main()
