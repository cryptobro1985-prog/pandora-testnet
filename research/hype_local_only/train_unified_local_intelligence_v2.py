#!/usr/bin/env python3
"""HYPE Unified Local Intelligence v2.

Research-only three-brain stack:
  QUANTUM: numeric tabular/nonlinear causal learner.
  JEPA: sequential representation learner.
  CORTEX: deterministic relationship-memory expert + regime arbitration.

The LLM Cortex remains explanation-only. Predictive CORTEX here is a replayable
relationship model, so an invalid/empty LLM JSON response cannot change scores.

Anti-leakage:
- only causal/quality INPUT-derived features enter X;
- TARGET_EVAL/METADATA are labels/audit only;
- experts fit on train;
- meta-controller fits on early validation;
- threshold calibrates on later validation;
- OOS is evaluated once, never fitted.
"""
from __future__ import annotations
import argparse,bisect,copy,gzip,json,math,pickle,statistics,hashlib
from collections import defaultdict
from pathlib import Path
import numpy as np
import torch
from sklearn.linear_model import LogisticRegression

from research.hype_local_only.train_local_ensemble_30d import (
    DELAYS,PRED_STAGES,TRAIN_END,OOS_START,END_MS,PURGE_MS,finite,sha256,
    load_teacher_labels,apply_teacher,load_rows,split_name,schema_from_train,
    robust_norm,build_samples,train_models,train_river,train_trees,
    attach_probs,attach_river_probs,attach_tree_probs,
    build_all_matured_samples,finetune_all,train_river_all,
    candidate_metrics,classification_metrics,fit_timeline,attach_candidate_probabilities,
    build_timeline_rows
)
from research.hype_local_only.h1_teacher_context import load_minutes,build_index,causal_h1_features
from research.hype_local_only.feature_discovery import scalar_interactions,historical_indicator_features
from research.hype_quant.feature_contract import POINTS,INPUT_IDS,TARGET_IDS,METADATA_IDS

SEED=20261111

def _sigmoid(x):
    if x>=0:
        z=math.exp(-min(60.0,x));return 1.0/(1.0+z)
    z=math.exp(max(-60.0,x));return z/(1.0+z)

def _logit(p):
    p=min(.999999,max(.000001,float(p)))
    return math.log(p/(1-p))

def _minute_regime(minutes,end_times,ts_ms):
    """Absolute market regime using completed M1 bars only, including 6h/8h."""
    j=bisect.bisect_right(end_times,int(ts_ms))
    if j<2:return {}
    closes=[float(x["close"]) for x in minutes[max(0,j-500):j] if finite(x.get("close"))]
    if len(closes)<2:return {}
    px=closes[-1]
    out={}
    for n in (5,15,30,60,180,360,480):
        if len(closes)>n and closes[-n-1]>0:
            out[f"discovery__market_ret_{n}m"]=px/closes[-n-1]-1.0
    if len(closes)>=61:
        rr=[closes[i]/closes[i-1]-1 for i in range(max(1,len(closes)-60),len(closes)) if closes[i-1]>0]
        if rr: out["discovery__market_realized_vol_60m"]=statistics.pstdev(rr)
    r15=out.get("discovery__market_ret_15m",0.0)
    r60=out.get("discovery__market_ret_60m",0.0)
    r360=out.get("discovery__market_ret_360m",0.0)
    r480=out.get("discovery__market_ret_480m",0.0)
    # bounded trend score; all terms are causal returns ending at snapshot t.
    score=(.35*math.tanh(r15*80)+.30*math.tanh(r60*35)+
           .20*math.tanh(r360*12)+.15*math.tanh(r480*10))
    out["discovery__market_regime_score"]=score
    out["discovery__market_bull_strength"]=max(0.0,score)
    out["discovery__market_bear_strength"]=max(0.0,-score)
    out["discovery__market_transition_strength"]=max(0.0,1.0-abs(score)*2.0)
    out["discovery__market_accel_15v60"]=r15-r60/4.0
    out["discovery__market_accel_60v360"]=r60-r360/6.0
    out["discovery__market_accel_60v480"]=r60-r480/8.0
    return out

class CortexRelationshipExpert:
    """Replayable train-only relationship memory.

    Learns robust true-vs-false feature effects separately for LOW/HIGH x stage.
    This is the predictive Cortex. The language model may explain it, but cannot
    inject untracked alpha or become a single point of failure.
    """
    def __init__(self,max_features=32,min_pos=4,min_neg=12):
        self.max_features=int(max_features);self.min_pos=int(min_pos);self.min_neg=int(min_neg)
        self.heads={}

    @staticmethod
    def _robust(vals):
        vals=[float(v) for v in vals if finite(v)]
        if not vals:return 0.0,1.0
        med=statistics.median(vals);mad=statistics.median(abs(v-med) for v in vals)
        return med,max(1e-9,1.4826*mad,abs(med)*.02)

    def fit(self,rows,allowed_names=None):
        allowed=set(allowed_names or [])
        for side in ("LOW","HIGH"):
            for stage in PRED_STAGES:
                rr=[r for r in rows if r["side"]==side and int(r["delay_s"])==stage
                    and split_name(r["candidate_ts_ms"])=="train"]
                base=sum(bool(r["strict_true"]) for r in rr)/max(1,len(rr))
                names=sorted({k for r in rr for k in r["features"] if not allowed or k in allowed})
                rel=[]
                for k in names:
                    pos=[r["features"][k] for r in rr if r["strict_true"] and k in r["features"]]
                    neg=[r["features"][k] for r in rr if not r["strict_true"] and k in r["features"]]
                    if len(pos)<self.min_pos or len(neg)<self.min_neg:continue
                    med,scale=self._robust(pos+neg)
                    effect=(statistics.median(pos)-statistics.median(neg))/scale
                    if not math.isfinite(effect) or abs(effect)<.08:continue
                    rel.append({"feature":k,"effect":float(effect),"median":float(med),
                                "pos":len(pos),"neg":len(neg)})
                rel.sort(key=lambda x:(abs(x["effect"]),x["pos"]+x["neg"]),reverse=True)
                rel=rel[:self.max_features]
                self.heads[(side,stage)]={"base_rate":float(base),"relationships":rel,
                                          "examples":len(rr),"positives":sum(bool(r["strict_true"]) for r in rr)}
        return self

    def predict(self,side,stage,features):
        h=self.heads.get((str(side),int(stage))) or {}
        rel=h.get("relationships") or []
        prior=float(h.get("base_rate",.05))
        if not rel:return prior
        num=den=0.0;seen=0
        for r in rel:
            k=r["feature"]
            if k not in features or not finite(features[k]):continue
            e=float(r["effect"]);w=min(3.0,abs(e))
            satisfied=(float(features[k])>=r["median"]) if e>0 else (float(features[k])<=r["median"])
            num+=w*(1.0 if satisfied else -1.0);den+=w;seen+=1
        if seen<4 or den<=0:return prior
        # conservative relationship adjustment around empirical base rate
        return _sigmoid(_logit(prior)+2.2*(num/den))

    def report(self):
        return {f"{s}_{h}s":v for (s,h),v in self.heads.items()}

def _row_index(rows):
    return {(r["candidate_id"],int(r["delay_s"])):r for r in rows}

def attach_cortex_probs(samples,rows,cortex):
    idx=_row_index(rows)
    for split in samples:
        for z in samples[split]:
            r=idx[(z["candidate_id"],z["stage"])]
            z["p_cortex"]=float(cortex.predict(z["side"],z["stage"],r["features"]))

def _meta_vector(z):
    ps=np.array([z["p_fin"],z["p_quant"],z["p_river"],z["p_tree"],z["p_timeline"],z["p_cortex"]],dtype=float)
    return np.array([
        *ps.tolist(),
        float(ps.mean()),float(ps.std()),float(ps.max()),float(ps.min()),
        float(z["stage"])/300.0,
        0.0 if z["side"]=="LOW" else 1.0,
        float(z.get("regime_score",0.0)),
        abs(float(z.get("regime_score",0.0))),
        float(z.get("regime_accel",0.0)),
    ],dtype=np.float32)

def attach_regime_to_samples(samples,rows):
    idx=_row_index(rows)
    for split in samples:
        for z in samples[split]:
            f=idx[(z["candidate_id"],z["stage"])]["features"]
            z["regime_score"]=float(f.get("discovery__market_regime_score",0.0) or 0.0)
            z["regime_accel"]=float(f.get("discovery__market_accel_60v360",0.0) or 0.0)

def candidate_metrics_meta(ss,model,threshold):
    by=defaultdict(list);truth={}
    for z in ss:
        p=float(model.predict_proba(_meta_vector(z)[None,:])[0,1])
        by[z["candidate_id"]].append((z["stage"],p,z));truth[z["candidate_id"]]=bool(z["y"])
    accepted=[]
    for cid,rr in by.items():
        for stage,p,z in sorted(rr):
            if p>=threshold:
                accepted.append((cid,stage,p,z));break
    tp=sum(bool(z["y"]) for _,_,_,z in accepted);fp=len(accepted)-tp
    true_total=sum(truth.values());fn=max(0,true_total-tp)
    prec=tp/(tp+fp) if tp+fp else 0.0;rec=tp/(tp+fn) if tp+fn else 0.0
    f1=2*prec*rec/(prec+rec) if prec+rec else 0.0
    delays=[stage for _,stage,_,z in accepted if z["y"]]
    return {"candidates":len(by),"reference_true":true_total,"accepted":len(accepted),
            "tp":tp,"fp":fp,"fn":fn,"precision":prec,"recall":rec,"f1":f1,
            "median_delay_s":float(np.median(delays)) if delays else None}

def fit_meta(valid):
    """Chronological candidate-group split with a label-maturity purge.

    Never put stages (60/180/300) from the SAME candidate in both meta-fit and
    calibration: that was a source of selection leakage in the earlier prototype.
    The later calibration subset must have distinct candidate IDs AND no
    overlapping 3-hour teacher-maturity boundary.
    """
    if not valid:
        raise RuntimeError("no validation samples")
    first_ts={}
    for z in valid:
        cid=str(z["candidate_id"])
        first_ts[cid]=min(int(z["ts"]),first_ts.get(cid,int(z["ts"])))
    ordered=sorted(first_ts,key=lambda cid:(first_ts[cid],cid))
    if len(ordered)<12:
        raise RuntimeError("insufficient distinct validation candidates for meta split")
    cut_ts=first_ts[ordered[int(len(ordered)*.60)]]
    left={cid for cid,t in first_ts.items() if t<cut_ts-PURGE_MS}
    right={cid for cid,t in first_ts.items() if t>=cut_ts}
    train=sorted((z for z in valid if z["candidate_id"] in left),
                 key=lambda z:(z["ts"],z["candidate_id"],z["stage"]))
    cal=sorted((z for z in valid if z["candidate_id"] in right),
               key=lambda z:(z["ts"],z["candidate_id"],z["stage"]))
    assert {z["candidate_id"] for z in train}.isdisjoint(
           {z["candidate_id"] for z in cal})
    if not train or not cal:raise RuntimeError("meta split empty after chronology purge")
    X=np.stack([_meta_vector(z) for z in train]);y=np.asarray([int(z["y"]) for z in train])
    if len(np.unique(y))<2:
        raise RuntimeError("meta validation-fit segment has one class")
    m=LogisticRegression(C=.5,class_weight="balanced",max_iter=2000,random_state=SEED)
    m.fit(X,y)
    # Calibrate ONLY on later candidate groups, never in OOS. Gate will reject
    # insufficient positive support, even if a tiny subset looks perfect.
    best=None
    for th in np.arange(.30,.951,.025):
        met=candidate_metrics_meta(cal,m,float(th))
        if met["accepted"]<3:continue
        objective=.58*met["precision"]+.27*met["f1"]+.15*met["recall"]-.0001*(met["median_delay_s"] or 300)
        if met["recall"]<.25:objective-=.15
        row=(objective,met["precision"],met["f1"],met["recall"],float(th),met)
        if best is None or row[:4]>best[:4]:best=row
    th=best[4] if best is not None else .5
    metrics=best[5] if best is not None else candidate_metrics_meta(cal,m,.5)
    info={
        "meta_train_rows":len(train),"cal_rows":len(cal),
        "meta_train_candidates":len(left),"cal_candidates":len(right),
        "meta_train_positive_candidates":len({z["candidate_id"] for z in train if z["y"]}),
        "cal_positive_candidates":len({z["candidate_id"] for z in cal if z["y"]}),
        "cut_ts_ms":int(cut_ts),"purge_ms":int(PURGE_MS),
        "candidate_id_overlap":0,"support_gate_min_cal_positives":5,
    }
    info["calibration_support_pass"]=bool(info["cal_positive_candidates"]>=5 and
                                          info["cal_candidates"]>=30)
    return m,th,metrics,info

def by_regime(oos,model,threshold):
    groups={"BEAR":[],"TRANSITION":[],"BULL":[]}
    for z in oos:
        s=float(z.get("regime_score",0.0))
        groups["BULL" if s>.18 else "BEAR" if s<-.18 else "TRANSITION"].append(z)
    return {k:(candidate_metrics_meta(v,model,threshold) if v else None) for k,v in groups.items()}

def inventory_extra(root):
    if not root or not Path(root).exists():return {"root":None,"files":[]}
    files=[]
    for p in sorted(Path(root).rglob("*")):
        if not p.is_file():continue
        try:size=p.stat().st_size
        except OSError:continue
        files.append({"path":str(p.relative_to(root)),"bytes":size})
    return {"root":str(root),"file_count":len(files),"files":files[:500],
            "note":"Extra saved artifacts are inventoried; only schema-compatible, causally aligned data are admitted to fitting."}

def merge_compatible_rows(base_rows,extra_root,valid_label_ids):
    rows=list(base_rows);seen={(r.get("candidate_id"),int(r.get("delay_s",-1)),int(r.get("snapshot_ts_ms",0))) for r in rows}
    admitted=[]
    if extra_root and Path(extra_root).exists():
        for p in Path(extra_root).rglob("candidate_snapshots*.jsonl.gz"):
            try:extra=load_rows(p)
            except Exception:continue
            n0=len(rows)
            for r in extra:
                key=(r.get("candidate_id"),int(r.get("delay_s",-1)),int(r.get("snapshot_ts_ms",0)))
                if key in seen:continue
                # Extra candidate artifacts are admitted only when they carry a
                # strict label id compatible with the current finalized teacher.
                # This prevents an older teacher generation from silently becoming
                # a huge pool of false negatives.
                if not (0<int(r.get("candidate_ts_ms",0))<END_MS):continue
                lid=r.get("strict_label_id")
                if lid is None or int(lid) not in valid_label_ids:continue
                rows.append(r);seen.add(key)
            if len(rows)>n0:admitted.append({"path":str(p),"rows_added":len(rows)-n0})
    return rows,admitted

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshots",type=Path,required=True)
    ap.add_argument("--compact-1m",type=Path,required=True)
    ap.add_argument("--labels-gz",type=Path,required=True)
    ap.add_argument("--availability",type=Path)
    ap.add_argument("--extra-root",type=Path)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--epochs",type=int,default=18)
    ap.add_argument("--workers",type=int,default=4)
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    assert len(POINTS)==116 and len(INPUT_IDS)==86 and not(INPUT_IDS&TARGET_IDS)

    base_rows=load_rows(args.snapshots)
    all_teacher,finalized=load_teacher_labels(args.labels_gz)
    valid_label_ids={int(x["label_id"]) for x in finalized}
    # FAIL-CLOSED: cross-artifact candidate IDs/teacher generations are not
    # sufficient proof of comparable negatives or feature timing. Inventory
    # extra full-micro / recent evidence, but do not silently concatenate it
    # into this 30D candidate-level classifier (selection-bias prevention).
    rows=list(base_rows)
    extra_admitted=[]
    extra_merge_verdict="QUARANTINED_UNTIL_FULL_TEACHER_AND_NEGATIVE_ALIGNMENT"
    teacher_coverage=apply_teacher(rows,finalized)
    minutes=load_minutes(args.compact_1m);h1_index=build_index(minutes)
    end_times=[int(z["bar_end_ms"]) for z in minutes]
    for r in rows:
        ts=int(r["snapshot_ts_ms"]);side=r["side"]
        r["features"].update(causal_h1_features(minutes,h1_index,ts,side,float(r["extreme_price"])))
        r["features"].update(historical_indicator_features(minutes,end_times,ts,side))
        r["features"].update({"discovery__"+k:float(v) for k,v in scalar_interactions(r["features"],side).items() if finite(v)})
        r["features"].update(_minute_regime(minutes,end_times,ts))

    names=schema_from_train(rows);med,scale=robust_norm(rows,names)
    samples=build_samples(rows,names,med,scale)

    timeline_rows=build_timeline_rows(minutes,all_teacher)
    timeline_model,timeline_names=fit_timeline(timeline_rows,split_name,args.workers,all_data=False)
    attach_candidate_probabilities(samples,timeline_rows,timeline_model,timeline_names)

    fin,quant,val_loss=train_models(samples,len(names)*2,args.epochs,args.workers)
    river=train_river(rows);trees=train_trees(samples,args.workers)
    attach_probs(samples,fin,quant,river);attach_river_probs(samples,rows,river);attach_tree_probs(samples,trees)

    cortex=CortexRelationshipExpert().fit(rows,allowed_names=names)
    attach_cortex_probs(samples,rows,cortex);attach_regime_to_samples(samples,rows)

    meta,threshold,cal_metrics,meta_split=fit_meta(samples["valid"])
    oos_metrics=candidate_metrics_meta(samples["oos"],meta,threshold)
    regime_oos=by_regime(samples["oos"],meta,threshold)

    # Fit final teacher only AFTER OOS metrics are frozen.
    fin_full=copy.deepcopy(fin);quant_full=copy.deepcopy(quant)
    all_refit=build_all_matured_samples(rows,names,med,scale)
    fin_full,quant_full,_=finetune_all(fin_full,quant_full,all_refit,epochs=8)
    river_full=train_river_all(rows)
    trees_full=train_trees({"train":all_refit},args.workers)

    gate=bool(meta_split["calibration_support_pass"] and
              oos_metrics["accepted"]>=5 and oos_metrics["precision"]>=.70 and
              oos_metrics["recall"]>=.40 and oos_metrics["f1"]>=.50)
    report={
      "version":"HYPE-UNIFIED-LOCAL-INTELLIGENCE-v2",
      "status":"OOS_GATE_PASS" if gate else "OOS_GATE_REJECT",
      "research_only":True,"real_orders":False,"auto_live_promotion":False,
      "architecture":{
        "JEPA":"sequential latent/representation agent",
        "QUANTUM":"tabular MLP + River + nonlinear tree evidence",
        "CORTEX":"train-only relationship-memory expert; LLM explanation is non-predictive",
        "META":"validation-only logistic arbiter using expert agreement/disagreement + causal regime",
        "regime_context":"5/15/30/60/180/360/480m completed-M1 returns, 60m realized vol, acceleration; no future bars"
      },
      "contract":{"points_total":116,"causal_quality_inputs":86,"target_eval":28,"metadata":2,
                  "scalar_features_used":len(names),"input_width_with_masks":len(names)*2},
      "sources":{"base_snapshots_sha256":sha256(args.snapshots),
                 "compact_sha256":sha256(args.compact_1m),"labels_sha256":sha256(args.labels_gz),
                 "base_rows":len(base_rows),"rows_after_compatible_merge":len(rows),
                 "extra_schema_compatible_admitted":extra_admitted,
                 "extra_merge_verdict":extra_merge_verdict,
                 "saved_source_inventory":inventory_extra(args.extra_root)},
      "split":{"train":"before 2026-10-23 with 3h purge",
               "meta_fit":"earliest 60% of distinct validation candidates, with 3h purge before cut",
               "meta_calibration":"later 40% of distinct validation candidates",
               "historical_oos_previously_inspected":"2026-10-27..2026-11-03 with terminal maturity purge; no longer untouched for model selection"},
      "samples":{k:len(v) for k,v in samples.items()},
      "teacher_coverage":teacher_coverage,
      "fin_jepa_validation_loss":val_loss,
      "meta_split":meta_split,
      "calibration":cal_metrics,
      "oos":oos_metrics,
      "oos_by_market_regime":regime_oos,
      "gate":{"passed":gate,"requirements":{"accepted_min":5,"precision_min":.70,"recall_min":.40,"f1_min":.50}},
      "cortex_relationship_heads":cortex.report(),
      "warning":"A local detector can be useful research without being safe for trading. No live promotion unless a genuinely fresh forward window confirms the frozen model."
    }
    bundle={
      "version":report["version"],"fin_jepa":fin_full.state_dict(),"quant_local":quant_full.state_dict(),
      "river_local":river_full,"extra_trees":trees_full,"cortex_relationship":cortex,
      "meta_model":meta,"meta_threshold":threshold,"feature_names":list(names),"median":med,"scale":scale,
      "regime_features":["5m","15m","30m","60m","180m","360m","480m"],
      "research_only":True,"real_orders":False
    }
    torch.save(bundle,args.output/"HYPE_UNIFIED_LOCAL_INTELLIGENCE_V2.pt")
    (args.output/"HYPE_UNIFIED_LOCAL_INTELLIGENCE_V2_REPORT.json").write_text(
        json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    print("UNIFIED_LOCAL_INTELLIGENCE="+json.dumps({
        "status":report["status"],"threshold":threshold,"calibration":cal_metrics,
        "oos":oos_metrics,"regimes":regime_oos
    },separators=(",",":"),ensure_ascii=False))

if __name__=="__main__":
    main()
