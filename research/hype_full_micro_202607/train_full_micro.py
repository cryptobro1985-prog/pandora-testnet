from __future__ import annotations
import argparse,gzip,json,math,pickle
from collections import defaultdict
from pathlib import Path
import numpy as np
from sklearn.ensemble import ExtraTreesClassifier,HistGradientBoostingClassifier
from sklearn.metrics import precision_recall_fscore_support

SEED=20261107
def finite(v):return isinstance(v,(int,float,np.number)) and math.isfinite(float(v))
def load(path):
    out=[]
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip():out.append(json.loads(line))
    return out
def split_ts(rows):
    ts=sorted({int(r["candidate_ts_ms"]) for r in rows});n=len(ts)
    a=ts[int(n*.70)];b=ts[int(n*.85)]
    return a,b
def schema(rows,cut):
    train=[r for r in rows if int(r["candidate_ts_ms"])<cut]
    counts=defaultdict(int)
    for r in train:
        for k,v in (r.get("features") or {}).items():
            if finite(v):counts[k]+=1
    n=max(1,len(train))
    banned=("strict","label","future","target_","precision","recall")
    return sorted(k for k,c in counts.items() if c/n>=.50 and not any(x in k.lower() for x in banned))
def matrix(rows,names):
    x=np.zeros((len(rows),len(names)*2),dtype=np.float32)
    for i,r in enumerate(rows):
        f=r["features"]
        for j,k in enumerate(names):
            v=f.get(k)
            if finite(v):x[i,j]=float(v);x[i,j+len(names)]=1.
    return x
def metrics(rows,p,th):
    by=defaultdict(list);truth={}
    for r,prob in zip(rows,p):
        by[r["candidate_id"]].append((int(r["delay_s"]),float(prob),r))
        truth[r["candidate_id"]]=bool(r["strict_true"])
    acc=[]
    for cid,rr in by.items():
        for d,prob,r in sorted(rr):
            if prob>=th:acc.append((cid,d,prob,r));break
    tp=sum(bool(r["strict_true"]) for *_,r in acc);fp=len(acc)-tp;tt=sum(truth.values());fn=max(0,tt-tp)
    pr=tp/(tp+fp) if tp+fp else 0.;rc=tp/(tp+fn) if tp+fn else 0.;f1=2*pr*rc/(pr+rc) if pr+rc else 0.
    return {"candidates":len(by),"true":tt,"accepted":len(acc),"tp":tp,"fp":fp,"fn":fn,"precision":pr,"recall":rc,"f1":f1,
            "median_delay_s":float(np.median([d for _,d,_,r in acc if r["strict_true"]])) if tp else None}
def choose(valid,p):
    best=None
    for th in np.arange(.2,.96,.02):
        m=metrics(valid,p,float(th))
        if m["accepted"]<4 or m["tp"]<2:continue
        score=.60*m["precision"]+.30*m["f1"]+.10*m["recall"]-.0001*(m["median_delay_s"] or 300)
        row=(score,m["precision"],m["f1"],m["recall"],float(th),m)
        if best is None or row[:4]>best[:4]:best=row
    return (best[4],best[5]) if best else (.5,metrics(valid,p,.5))
def feature_relationships(rows,names,topn=60):
    out=[]
    for side in ("LOW","HIGH"):
        rr=[r for r in rows if r["side"]==side and int(r["delay_s"])==300]
        pos=[r for r in rr if r["strict_true"]];neg=[r for r in rr if not r["strict_true"]]
        base=len(pos)/max(1,len(rr))
        feats=[]
        for k in names:
            pv=[float(r["features"][k]) for r in pos if finite(r["features"].get(k))]
            nv=[float(r["features"][k]) for r in neg if finite(r["features"].get(k))]
            if len(pv)<3 or len(nv)<8:continue
            med=float(np.median(pv+nv));mad=float(np.median(np.abs(np.asarray(pv+nv)-med)))
            scale=max(1e-9,1.4826*mad,abs(med)*.02)
            eff=(float(np.median(pv))-float(np.median(nv)))/scale
            if not math.isfinite(eff):continue
            feats.append({"feature":k,"effect":eff,"threshold":med,
                          "true_median":float(np.median(pv)),"false_median":float(np.median(nv)),
                          "true_support":len(pv),"false_support":len(nv)})
        feats.sort(key=lambda z:abs(z["effect"]),reverse=True)
        pairs=[]
        for i,a in enumerate(feats[:18]):
            for b in feats[i+1:18]:
                sat=[]
                for r in rr:
                    f=r["features"]
                    if not finite(f.get(a["feature"])) or not finite(f.get(b["feature"])):continue
                    aa=float(f[a["feature"]])>=a["threshold"] if a["effect"]>0 else float(f[a["feature"]])<=a["threshold"]
                    bb=float(f[b["feature"]])>=b["threshold"] if b["effect"]>0 else float(f[b["feature"]])<=b["threshold"]
                    if aa and bb:sat.append(r)
                if len(sat)<8:continue
                rate=sum(bool(r["strict_true"]) for r in sat)/len(sat)
                pairs.append({"a":a["feature"],"b":b["feature"],"support":len(sat),
                              "positive_rate":rate,"baseline_rate":base,"lift":rate/max(base,1e-9)})
        pairs.sort(key=lambda z:(z["lift"],z["support"]),reverse=True)
        out.append((side,{"baseline_positive_rate":base,
                          "top_features":feats[:topn],
                          "top_pairs":pairs[:topn]}))
    return dict(out)

def fit_one(train,valid,oos,names,kind):
    X=matrix(train,names);y=np.asarray([int(r["strict_true"]) for r in train])
    if kind=="extra":
        m=ExtraTreesClassifier(n_estimators=700,max_depth=14,min_samples_leaf=2,max_features="sqrt",
                               class_weight="balanced_subsample",n_jobs=4,random_state=SEED)
    else:
        # explicit sample weights handle the severe class imbalance.
        m=HistGradientBoostingClassifier(max_iter=350,max_leaf_nodes=31,l2_regularization=2.0,learning_rate=.05,random_state=SEED)
    sw=np.where(y==1,max(1.,(len(y)-y.sum())/max(1,y.sum())),1.)
    try:m.fit(X,y,sample_weight=sw)
    except TypeError:m.fit(X,y)
    vp=m.predict_proba(matrix(valid,names))[:,1];th,vm=choose(valid,vp)
    op=m.predict_proba(matrix(oos,names))[:,1];om=metrics(oos,op,th)
    return m,th,vm,om
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--snapshots",type=Path,required=True);ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    rows=[r for r in load(args.snapshots) if int(r.get("delay_s",-1)) in (60,180,300)]
    a,b=split_ts(rows);names=schema(rows,a)
    train=[r for r in rows if r["candidate_ts_ms"]<a]
    valid=[r for r in rows if a<=r["candidate_ts_ms"]<b]
    oos=[r for r in rows if r["candidate_ts_ms"]>=b]
    models={};report={"split":{"train_end_ms":a,"valid_end_ms":b},"features":len(names),"rows":{"train":len(train),"valid":len(valid),"oos":len(oos)},"models":{},"relationships":feature_relationships(train+valid,names)}
    for kind in ("extra","histgb"):
        m,th,vm,om=fit_one(train,valid,oos,names,kind);models[kind]=m
        ready=bool(om["accepted"]>=5 and om["tp"]>=5 and om["precision"]>=.90 and om["recall"]>=.30)
        report["models"][kind]={"threshold":th,"validation":vm,"oos":om,
                              "holdout_90pct_gate":{"passed":ready,"precision_min":.90,"recall_min":.30,"tp_min":5,"accepted_min":5}}
    report["overall_90pct_gate"]={
        "passed":any(v["holdout_90pct_gate"]["passed"] for v in report["models"].values()),
        "meaning":"research readiness only; not a profit guarantee or future-performance guarantee"
    }
    # final refit on all data only after OOS report is frozen
    full={}
    X=matrix(rows,names);y=np.asarray([int(r["strict_true"]) for r in rows]);sw=np.where(y==1,max(1.,(len(y)-y.sum())/max(1,y.sum())),1.)
    for kind in ("extra","histgb"):
        if kind=="extra":m=ExtraTreesClassifier(n_estimators=900,max_depth=14,min_samples_leaf=2,max_features="sqrt",class_weight="balanced_subsample",n_jobs=4,random_state=SEED)
        else:m=HistGradientBoostingClassifier(max_iter=400,max_leaf_nodes=31,l2_regularization=2.0,learning_rate=.05,random_state=SEED)
        try:m.fit(X,y,sample_weight=sw)
        except TypeError:m.fit(X,y)
        full[kind]=m
    with (args.output/"HYPE_FULL_MICRO_202607.pkl").open("wb") as f:pickle.dump({"models":full,"feature_names":names,"report":report},f,pickle.HIGHEST_PROTOCOL)
    (args.output/"HYPE_FULL_MICRO_202607_REPORT.json").write_text(json.dumps(report,indent=2)+"\n")
    print("FULL_MICRO_TRAIN="+json.dumps(report,separators=(",",":")))
if __name__=="__main__":main()
