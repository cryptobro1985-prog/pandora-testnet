from __future__ import annotations
import argparse,gzip,json,math,bisect
from collections import defaultdict
from pathlib import Path
import numpy as np
from sklearn.metrics import roc_auc_score,average_precision_score

SEED=20261107

def finite(v):
    return isinstance(v,(int,float,np.number)) and math.isfinite(float(v))

def load(path):
    rows=[]
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            r=json.loads(line)
            if int(r["delay_s"])==0:
                rows.append(r)
    return sorted(rows,key=lambda r:int(r["candidate_ts_ms"]))

def robust_feature_names(rows):
    names=sorted({k for r in rows for k,v in (r.get("features") or {}).items() if finite(v)})
    banned=("strict","label","future","target_","precision","recall")
    return [k for k in names if not any(b in k.lower() for b in banned)]

def split(rows):
    ts=sorted({int(r["candidate_ts_ms"]) for r in rows})
    n=len(ts)
    a=ts[int(n*.60)]
    b=ts[int(n*.80)]
    return (
        [r for r in rows if int(r["candidate_ts_ms"])<a],
        [r for r in rows if a<=int(r["candidate_ts_ms"])<b],
        [r for r in rows if int(r["candidate_ts_ms"])>=b],
    )

def auc_on(rows,k):
    z=[(1 if r["strict_true"] else 0,float(r["features"][k])) for r in rows if finite(r["features"].get(k))]
    if len(z)<20 or len({y for y,_ in z})<2 or len({v for _,v in z})<2:return None
    return float(roc_auc_score([y for y,_ in z],[v for _,v in z]))

def build_relation(dev,val,names):
    rel=[]
    for k in names:
        ad=auc_on(dev,k); av=auc_on(val,k)
        if ad is None or av is None: continue
        dd=ad-.5; dv=av-.5
        if dd*dv<=0: continue
        weight=min(abs(dd),abs(dv))
        if weight<.01: continue
        direction=1 if dd>0 else -1
        vals=sorted(float(r["features"][k]) for r in dev+val if finite(r["features"].get(k)))
        if len(vals)<20: continue
        rel.append({"feature":k,"direction":direction,"weight":weight,"reference":vals})
    return rel

def score(rows,rel):
    scores=[]
    for r in rows:
        s=0.;den=0.
        for z in rel:
            v=r["features"].get(z["feature"])
            if not finite(v): continue
            arr=z["reference"]
            pct=bisect.bisect_right(arr,float(v))/len(arr)
            signed=(pct-.5)*2*z["direction"]
            s+=signed*z["weight"];den+=z["weight"]
        scores.append(s/den if den else 0.)
    return np.asarray(scores,dtype=float)

def threshold_metrics(rows,scores,threshold):
    pred=scores>=threshold
    y=np.asarray([1 if r["strict_true"] else 0 for r in rows],dtype=int)
    tp=int(((pred)&(y==1)).sum()); fp=int(((pred)&(y==0)).sum()); fn=int((~pred&(y==1)).sum())
    accepted=int(pred.sum())
    precision=tp/accepted if accepted else 0.
    recall=tp/(tp+fn) if tp+fn else 0.
    return {"threshold":float(threshold),"accepted":accepted,"tp":tp,"fp":fp,"fn":fn,
            "precision":precision,"recall":recall}

def choose_threshold(val,scores):
    best=None
    for th in np.linspace(-.2,.95,232):
        m=threshold_metrics(val,scores,float(th))
        if m["accepted"]<3 or m["tp"]<2: continue
        score=.7*m["precision"]+.3*m["recall"]
        row=(score,m["precision"],m["recall"],m)
        if best is None or row[:3]>best[:3]: best=row
    return best[3] if best else threshold_metrics(val,scores,float(np.quantile(scores,.95)))

def side_report(all_rows,side):
    rows=[r for r in all_rows if r["side"]==side]
    dev,val,test=split(rows)
    names=robust_feature_names(dev+val)
    relation=build_relation(dev,val,names)
    sv=score(val,relation); st=score(test,relation)
    chosen=choose_threshold(val,sv)
    testm=threshold_metrics(test,st,chosen["threshold"])
    yv=np.asarray([1 if r["strict_true"] else 0 for r in val])
    yt=np.asarray([1 if r["strict_true"] else 0 for r in test])
    top=sorted(relation,key=lambda z:z["weight"],reverse=True)
    return {
      "side":side,
      "rows":{"development":len(dev),"validation":len(val),"frozen_test":len(test)},
      "true_locals":{"development":sum(bool(r["strict_true"]) for r in dev),
                     "validation":sum(bool(r["strict_true"]) for r in val),
                     "frozen_test":sum(bool(r["strict_true"]) for r in test)},
      "contract":{"total_points":116,"causal_quality_inputs":86,"teacher_eval_points":28,"metadata_points":2},
      "available_raw_dimensions_scanned":len(names),
      "stable_relation_dimensions":len(relation),
      "validation":{"roc_auc":float(roc_auc_score(yv,sv)) if len(set(yv))>1 else None,
                    "average_precision":float(average_precision_score(yv,sv)),
                    "threshold_selection":chosen},
      "frozen_test":{"roc_auc":float(roc_auc_score(yt,st)) if len(set(yt))>1 else None,
                     "average_precision":float(average_precision_score(yt,st)),
                     **testm},
      "relation_definition":"Single side-specific composite relation built from every causal feature whose direction is stable in both development and validation. All unstable dimensions are retained in the scan but receive zero weight.",
      "top_relation_dimensions":[{"feature":z["feature"],"direction":"higher_in_true_local" if z["direction"]>0 else "lower_in_true_local","weight":z["weight"]} for z in top[:40]],
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshots",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    rows=load(a.snapshots)
    out={
      "objective":"Find exactly one relationship for Local LOW and exactly one for Local HIGH across the fixed 116-point contract. Future teacher/eval points never enter X.",
      "LOW":side_report(rows,"LOW"),
      "HIGH":side_report(rows,"HIGH")
    }
    (a.out/"LOW_HIGH_RELATIONS_LATEST.json").write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps({"LOW":out["LOW"]["frozen_test"],"HIGH":out["HIGH"]["frozen_test"]},separators=(",",":")))

if __name__=="__main__": main()
