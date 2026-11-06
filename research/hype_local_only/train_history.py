#!/usr/bin/env python3
from __future__ import annotations
import argparse,gzip,json,math,pickle,statistics
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
from research.hype_local_only.model import LocalOnlyModel,STAGES,clean

TRAIN_END=int(datetime(2026,10,23,tzinfo=timezone.utc).timestamp()*1000)
OOS_START=int(datetime(2026,10,27,tzinfo=timezone.utc).timestamp()*1000)

def load(path):
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip(): yield json.loads(line)

def robust(vals):
    vals=[float(x) for x in vals if isinstance(x,(int,float)) and math.isfinite(x)]
    if not vals:return 0.0,1.0
    med=statistics.median(vals);mad=statistics.median(abs(x-med) for x in vals)
    return med,max(1e-9,1.4826*mad,abs(med)*.02)

def stats(rows,probs,threshold):
    tp=fp=fn=tn=0
    for r,p in zip(rows,probs):
        y=bool(r["strict_true"]);pred=p>=threshold
        if pred and y:tp+=1
        elif pred:fp+=1
        elif y:fn+=1
        else:tn+=1
    n=tp+fp+fn+tn
    return {"n":n,"tp":tp,"fp":fp,"fn":fn,"tn":tn,
            "precision":tp/(tp+fp) if tp+fp else None,
            "recall":tp/(tp+fn) if tp+fn else None,
            "accuracy":(tp+tn)/n if n else None}

def choose_threshold(rows,probs):
    best=(None,0.5)
    for i in range(20,86):
        th=i/100
        m=stats(rows,probs,th)
        p=m["precision"] or 0;r=m["recall"] or 0
        # Precision matters, but a detector that never catches the local is useless.
        score=.58*p+.42*r
        if m["tp"]<2:score-=1
        if best[0] is None or score>best[0]:best=(score,th)
    return best[1]

def feature_effects(rows):
    names=sorted({k for r in rows for k in (r.get("features") or {})})
    effects=[]
    for name in names:
        pos=[r["features"][name] for r in rows if r["strict_true"] and name in r["features"]]
        neg=[r["features"][name] for r in rows if not r["strict_true"] and name in r["features"]]
        allv=pos+neg
        if len(pos)<3 or len(neg)<3:continue
        med,scale=robust(allv)
        eff=(statistics.median(pos)-statistics.median(neg))/scale
        if not math.isfinite(eff):continue
        effects.append({"feature":name,"effect":eff,"median":med,"scale":scale,
                        "positive_median":statistics.median(pos),"negative_median":statistics.median(neg),
                        "support":len(allv)})
    effects.sort(key=lambda z:abs(z["effect"]),reverse=True)
    return effects

def pairwise(rows,effects):
    base=sum(bool(r["strict_true"]) for r in rows)/max(1,len(rows))
    top=effects[:12];out=[]
    for i,a in enumerate(top):
        for b in top[i+1:]:
            sat=[]
            for r in rows:
                f=r.get("features") or {}
                if a["feature"] not in f or b["feature"] not in f:continue
                aa=f[a["feature"]]>=a["median"] if a["effect"]>0 else f[a["feature"]]<=a["median"]
                bb=f[b["feature"]]>=b["median"] if b["effect"]>0 else f[b["feature"]]<=b["median"]
                if aa and bb:sat.append(r)
            if len(sat)<8:continue
            rate=sum(bool(r["strict_true"]) for r in sat)/len(sat)
            out.append({"a":a["feature"],"b":b["feature"],"support":len(sat),
                        "positive_rate":rate,"baseline_rate":base,"lift":rate/max(base,1e-9)})
    out.sort(key=lambda z:(z["lift"],z["support"]),reverse=True)
    return out[:30]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshots",type=Path,required=True)
    ap.add_argument("--model-out",type=Path,required=True)
    ap.add_argument("--memory-out",type=Path,required=True)
    ap.add_argument("--report-out",type=Path,required=True)
    args=ap.parse_args()

    rows=[r for r in load(args.snapshots)
          if int(r.get("delay_s",-1)) in STAGES and r.get("side") in ("LOW","HIGH")]
    if not rows:raise SystemExit("no historical rows")
    model=LocalOnlyModel()
    report={"version":model.VERSION,"teacher":"strict_true H1 Local labels","heads":{},
            "historical_rows":len(rows),"leakage_guard":"strict_true and all target/eval fields are labels only"}
    memory={"version":"HYPE-LOCAL-RELATIONSHIP-MEMORY-v1","teacher":"strict_true","heads":{}}
    class_weights={}

    for side in ("LOW","HIGH"):
      for stage in STAGES:
        key=f"{side}_{stage}s"
        rr=[r for r in rows if r["side"]==side and int(r["delay_s"])==stage]
        train=[r for r in rr if int(r["candidate_ts_ms"])<TRAIN_END]
        valid=[r for r in rr if TRAIN_END<=int(r["candidate_ts_ms"])<OOS_START]
        oos=[r for r in rr if int(r["candidate_ts_ms"])>=OOS_START]
        pos=sum(bool(r["strict_true"]) for r in train)
        neg=max(0,len(train)-pos)
        pos_repeat=max(1,min(8,round(neg/max(1,pos))))
        class_weights[(side,stage)]=pos_repeat
        temp=LocalOnlyModel()
        for r in train:
            temp.learn(side,stage,r["features"],r["strict_true"],
                       repeat=(pos_repeat if r["strict_true"] else 1))
        vp=[temp.probability(side,stage,r["features"]) for r in valid]
        th=choose_threshold(valid,vp) if valid else .5
        op=[temp.probability(side,stage,r["features"]) for r in oos]
        model.thresholds[(side,stage)]=th
        report["heads"][key]={
            "train":stats(train,[temp.probability(side,stage,r["features"]) for r in train],th),
            "validation":stats(valid,vp,th),
            "oos":stats(oos,op,th),
            "threshold":th,
            "positive_oversample_repeat":pos_repeat,
        }
        fx=feature_effects(train+valid)
        memory["heads"][key]={
            "baseline_positive_rate":sum(bool(r["strict_true"]) for r in rr)/max(1,len(rr)),
            "top_feature_relationships":fx[:50],
            "top_pair_relationships":pairwise(train+valid,fx),
            "false_examples":sum(not bool(r["strict_true"]) for r in rr),
            "true_examples":sum(bool(r["strict_true"]) for r in rr),
        }

    # After honest OOS evaluation, final production research model consumes all 30d labels.
    for r in rows:
        key=(r["side"],int(r["delay_s"]))
        repeat=class_weights.get(key,1) if r["strict_true"] else 1
        model.learn(r["side"],int(r["delay_s"]),r["features"],r["strict_true"],repeat=repeat)
    model.history_meta={
        "period":["2026-10-04","2026-11-03"],
        "candidate_snapshots_total":6261,
        "used_stage_rows":len(rows),
        "teacher":"strict_true",
        "train_end":"2026-10-23","oos_start":"2026-10-27",
        "missing_historical_sources":"availability-aware; never imputed",
    }
    model.relationship_memory=memory
    args.model_out.parent.mkdir(parents=True,exist_ok=True)
    model.save(args.model_out)
    args.memory_out.write_text(json.dumps(memory,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    report["final_model"]=model.report()
    args.report_out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("LOCAL_ONLY_HISTORY="+json.dumps({
        "rows":len(rows),
        "labels":sum(model.labels.values()),
        "heads":{k:{"threshold":v["threshold"],"oos":v["oos"]} for k,v in report["heads"].items()}
    },separators=(",",":")))

if __name__=="__main__":main()
