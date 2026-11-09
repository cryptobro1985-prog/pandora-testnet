#!/usr/bin/env python3
from __future__ import annotations

import argparse,gzip,json,math,pickle
from collections import Counter,defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier,HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline


SEED=20261109
SEVERITIES=(5.0,10.0,20.0,40.0)


def load_json_gz(path):
    with gzip.open(path,"rt",encoding="utf-8") as f:return json.load(f)


def load_jsonl_gz(path):
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip():yield json.loads(line)


def finite(v):
    return isinstance(v,(int,float,np.number)) and math.isfinite(float(v))


def clean_features(raw):
    out={}
    for k,v in (raw or {}).items():
        if not finite(v):continue
        lk=str(k).lower()
        if any(x in lk for x in ("strict","label","future","target_","precision","recall")):
            continue
        if lk in ("delay_s","candidate_age_s","elapsed_s","stage"):
            continue
        if lk=="age_s":
            out["candidate_survival_log_s"]=math.log1p(max(0.0,float(v)))
            continue
        out[str(k)]=float(v)
    if "candidate_survival_log_s" in out and "retrace_bps" in out:
        out["survival_x_retrace"]=out["candidate_survival_log_s"]*out["retrace_bps"]
    return out


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


def prepare(rows,labels):
    byid={int(x["label_id"]):x for x in labels}
    out=[]
    for r in rows:
        side=str(r.get("side",""))
        tid=r.get("target_label_id")
        if side not in ("LOW","HIGH") or tid is None or int(tid) not in byid:
            continue
        f=clean_features(r.get("features") or {})
        if not f:continue
        target=byid[int(tid)]
        cp=float(r["extreme_price"]);tp=float(target["extreme_price"])
        cont=max(0.0,(cp/tp-1.0)*10000.0) if side=="LOW" else max(0.0,(tp/cp-1.0)*10000.0)
        retr=float(f.get("retrace_bps",0.0))
        signal_px=cp*(1.0+retr/10000.0) if side=="LOW" else cp*(1.0-retr/10000.0)
        out.append({
            **r,"features":f,
            "strict_true":bool(r.get("strict_label_id") is not None and int(r["strict_label_id"])==int(tid)),
            "continuation_bps":cont,
            "target_extreme_price":tp,
            "target_extreme_ts_ms":int(target["extreme_interval_start_ms"]),
            "signal_price_estimate":signal_px,
        })
    return out


def names(rows):
    c=Counter(k for r in rows for k in r["features"])
    n=max(1,len(rows))
    return sorted(k for k,v in c.items() if v/n>=.35)


def matrix(rows,ns):
    return np.asarray([[r["features"].get(k,np.nan) for k in ns] for r in rows],dtype=float)


def model(kind):
    if kind=="extra":
        return Pipeline([
            ("impute",SimpleImputer(strategy="median",add_indicator=True)),
            ("model",ExtraTreesClassifier(
                n_estimators=600,max_depth=10,min_samples_leaf=6,
                max_features="sqrt",random_state=SEED,n_jobs=-1,
            )),
        ])
    return Pipeline([
        ("impute",SimpleImputer(strategy="median",add_indicator=True)),
        ("model",HistGradientBoostingClassifier(
            max_iter=260,learning_rate=.04,max_leaf_nodes=15,
            min_samples_leaf=12,l2_regularization=4.0,random_state=SEED,
        )),
    ])


def sample_weights(rows,y):
    reps=Counter(r["candidate_id"] for r in rows)
    bycid={}
    for r,z in zip(rows,y):bycid[r["candidate_id"]]=bool(z)
    pos=sum(bycid.values());neg=len(bycid)-pos
    pw=min(15.0,max(1.0,neg/max(1,pos)))
    nw=min(5.0,max(1.0,pos/max(1,neg)))
    return np.asarray([((pw if z else nw)/max(1,reps[r["candidate_id"]])) for r,z in zip(rows,y)])


def fit_head(rows,ns,kind,y):
    m=model(kind)
    yy=np.asarray(y,dtype=bool)
    if len(set(yy))<2:
        return None
    m.fit(matrix(rows,ns),yy,model__sample_weight=sample_weights(rows,yy))
    return m


def episode_metrics(rows,direct_p,risk_p,direct_th,risk_th):
    # First accepted snapshot across all candidates in an episode is the trade.
    byep=defaultdict(list)
    for r,p,q in zip(rows,direct_p,risk_p):
        byep[int(r["target_label_id"])].append((
            int(r["snapshot_ts_ms"]),int(r["candidate_ts_ms"]),r,float(p),float(q)
        ))
    tp=fp=0;missed=[];delay=[];false_cont=[];records=[]
    for tid,items in sorted(byep.items()):
        accepted=[z for z in items if z[3]>=direct_th and z[4]<=risk_th]
        if not accepted:continue
        _,_,r,p,q=min(accepted,key=lambda z:(z[0],z[1]))
        true=bool(r["strict_true"])
        if true:
            tp+=1
            delay.append(max(0.0,(int(r["snapshot_ts_ms"])-int(r["target_extreme_ts_ms"]))/1000.0))
            side=r["side"];tp_px=float(r["target_extreme_price"]);sp=float(r["signal_price_estimate"])
            mb=max(0.0,(sp/tp_px-1)*10000) if side=="LOW" else max(0.0,(tp_px/sp-1)*10000)
            missed.append(mb)
        else:
            fp+=1;false_cont.append(float(r["continuation_bps"]))
        records.append({
            "target_label_id":tid,"candidate_id":r["candidate_id"],"side":r["side"],
            "candidate_ts_ms":int(r["candidate_ts_ms"]),"signal_ts_ms":int(r["snapshot_ts_ms"]),
            "direct_probability":p,"continuation_risk":q,
            "true_first":true,"continuation_bps":float(r["continuation_bps"]),
        })
    episodes=len(byep);n=tp+fp
    return {
        "episodes":episodes,"accepted_first":n,"true_first":tp,"false_first":fp,
        "precision":tp/n if n else None,"recall":tp/episodes if episodes else None,
        "coverage":n/episodes if episodes else None,
        "median_delay_s":float(np.median(delay)) if delay else None,
        "median_missed_move_bps":float(np.median(missed)) if missed else None,
        "median_false_continuation_bps":float(np.median(false_cont)) if false_cont else None,
        "first_signals":records,
    }


def select_gates(rows,dp,rp):
    best=None
    for dth in np.arange(.50,.991,.02):
        for rth in np.arange(.01,.501,.02):
            m=episode_metrics(rows,dp,rp,float(dth),float(rth))
            p=m["precision"] or 0.0;rc=m["recall"] or 0.0
            viable=m["true_first"]>=2 and rc>=.15
            false_sev=m["median_false_continuation_bps"]
            false_sev=1e9 if false_sev is None else false_sev
            delay_v=1e9 if m["median_delay_s"] is None else m["median_delay_s"]
            key=(1 if viable else 0,p,rc,-m["false_first"],-false_sev,-delay_v)
            if best is None or key>best[0]:
                best=(key,float(dth),float(rth),m)
    return best[1],best[2],best[3],best[0]


def fit_side(rows,split,side):
    sr=[r for r in rows if r["side"]==side]
    tr=[r for r in sr if int(r["target_label_id"]) in split["train"]]
    va=[r for r in sr if int(r["target_label_id"]) in split["valid"]]
    oo=[r for r in sr if int(r["target_label_id"]) in split["oos"]]
    ns=names(tr)
    trials=[];best=None
    for direct_kind in ("extra","hist"):
        for risk_kind in ("extra","hist"):
            direct=fit_head(tr,ns,direct_kind,[r["strict_true"] for r in tr])
            if direct is None:continue
            dpv=direct.predict_proba(matrix(va,ns))[:,1]
            for sev in SEVERITIES:
                risk=fit_head(tr,ns,risk_kind,[r["continuation_bps"]>sev for r in tr])
                if risk is None:continue
                rpv=risk.predict_proba(matrix(va,ns))[:,1]
                dth,rth,vm,key=select_gates(va,dpv,rpv)
                row={
                    "direct_model":direct_kind,"risk_model":risk_kind,"severity_bps":sev,
                    "direct_threshold":dth,"risk_threshold":rth,
                    "validation":vm,"selection_key":list(key),
                }
                trials.append(row)
                if best is None or key>best[0]:
                    best=(key,direct_kind,risk_kind,sev,dth,rth,vm)
    _,dk,rk,sev,dth,rth,vm=best

    # Refit on train+validation only after gate selection. OOS stays untouched.
    dev=tr+va
    ns=names(dev)
    direct=fit_head(dev,ns,dk,[r["strict_true"] for r in dev])
    risk=fit_head(dev,ns,rk,[r["continuation_bps"]>sev for r in dev])
    dpo=direct.predict_proba(matrix(oo,ns))[:,1]
    rpo=risk.predict_proba(matrix(oo,ns))[:,1]
    om=episode_metrics(oo,dpo,rpo,dth,rth)

    return {
        "direct_model":dk,"risk_model":rk,"severity_bps":sev,
        "direct_threshold":dth,"risk_threshold":rth,
        "validation":vm,"oos":om,"trials":trials,
        "feature_names":ns,"direct_pipeline":direct,"risk_pipeline":risk,
        "rows":{"train":len(tr),"validation":len(va),"oos":len(oo)},
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
    sides={s:fit_side(rows,split,s) for s in ("LOW","HIGH")}

    report={
        "version":"HYPE-DENSE-FULL-MICRO-DUAL-HEAD-v1",
        "teacher":"STRICT_L6_K2_REFERENCE_FINALIZED_ONLY",
        "candidate_contract":"DENSE_STRICT_SWING_RUNNING_EXTREME_V1",
        "decision":"high terminal probability AND low continuation risk",
        "fixed_time_gate":False,
        "rows":len(rows),
        "by_side":{
            s:{k:v for k,v in sides[s].items() if k not in ("feature_names","direct_pipeline","risk_pipeline")}
              | {"feature_count":len(sides[s]["feature_names"])}
            for s in sides
        },
        "promotion_gate":{
            s:{
                "passed":bool(
                    sides[s]["oos"]["accepted_first"]>=3
                    and sides[s]["oos"]["true_first"]>=3
                    and (sides[s]["oos"]["precision"] or 0)>=.80
                    and (sides[s]["oos"]["recall"] or 0)>=.25
                ),
                "requirements":{"accepted_first":3,"true_first":3,"precision":.80,"recall":.25}
            } for s in sides
        },
        "real_orders":False,
    }
    bundle={
        "version":report["version"],
        "report":report,
        "sides":{
            s:{
                "feature_names":sides[s]["feature_names"],
                "direct_pipeline":sides[s]["direct_pipeline"],
                "risk_pipeline":sides[s]["risk_pipeline"],
                "direct_threshold":sides[s]["direct_threshold"],
                "risk_threshold":sides[s]["risk_threshold"],
                "severity_bps":sides[s]["severity_bps"],
            } for s in sides
        },
    }
    with (args.output/"HYPE_DENSE_FULL_MICRO_DUAL_HEAD.pkl").open("wb") as f:
        pickle.dump(bundle,f,pickle.HIGHEST_PROTOCOL)
    (args.output/"HYPE_DENSE_FULL_MICRO_DUAL_HEAD_REPORT.json").write_text(
        json.dumps(report,indent=2,ensure_ascii=False)+"\n"
    )
    print("DENSE_DUAL_HEAD="+json.dumps(report,separators=(",",":")))


if __name__=="__main__":main()
