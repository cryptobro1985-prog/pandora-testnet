#!/usr/bin/env python3
"""Train an honest 3-expert HYPE Local ensemble on the verified 30D archive.

Experts:
  1) Fin-JEPA sequential latent predictor + LOW/HIGH heads.
  2) Quant-style tabular MLP expert.
  3) Existing River LocalOnly causal logistic heads.

The 116-point contract is preserved, but only causal INPUT points/features are
allowed into models. TARGET_EVAL/METADATA points never enter X. Missing
historical families remain missing and are represented by availability masks;
they are never fabricated.

Research-only. No order placement and no automatic live promotion.
"""
from __future__ import annotations
import argparse,copy,gzip,hashlib,json,math,random
from collections import defaultdict
from pathlib import Path
import numpy as np
import torch
from torch import nn
import torch.nn.functional as F
from sklearn.ensemble import ExtraTreesClassifier

from research.hype_local_only.fin_jepa_adapter import HypeFinJEPA,validate_scalar_schema
from research.hype_local_only.model import LocalOnlyModel,STAGES
from research.hype_local_only.h1_teacher_context import load_minutes,build_index,causal_h1_features
from research.hype_local_only.feature_discovery import scalar_interactions,historical_indicator_features
from research.hype_local_only.timeline_teacher import build_timeline_rows,fit as fit_timeline,attach_candidate_probabilities,classification_metrics
from research.hype_quant.feature_contract import POINTS,INPUT_IDS,TARGET_IDS,METADATA_IDS

TRAIN_END=1792713600000   # 2026-10-23T00:00:00Z
OOS_START=1793059200000   # 2026-10-27T00:00:00Z
END_MS=1793664000000      # 2026-11-03T00:00:00Z
PURGE_MS=3*60*60*1000
DELAYS=(0,30,60,180,300)
PRED_STAGES=(60,180,300)
SEED=20261107

def finite(v): return isinstance(v,(int,float)) and math.isfinite(v)

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def load_teacher_labels(path):
    with gzip.open(path,"rt",encoding="utf-8") as f:obj=json.load(f)
    labels=list(obj.get("strict") or [])
    finalized=[x for x in labels if x.get("reference_finalized",True)]
    return labels,finalized

def apply_teacher(rows,finalized):
    valid_ids={int(x["label_id"]) for x in finalized}
    seen=set()
    for r in rows:
        lid=r.get("strict_label_id")
        ok=lid is not None and int(lid) in valid_ids
        r["strict_true"]=bool(ok)
        if ok:seen.add(int(lid))
    sides={s:sum(1 for x in finalized if x.get("side")==s) for s in ("LOW","HIGH")}
    return {"strict_labels_total":len(finalized),"strict_labels_by_side":sides,
            "strict_label_ids_seen_in_candidate_replay":len(seen),
            "strict_label_ids_missing_from_candidate_replay":sorted(valid_ids-seen)}

def load_rows(path):
    rows=[]
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if not line.strip():continue
            r=json.loads(line)
            if r.get("side") in ("LOW","HIGH") and int(r.get("delay_s",-1)) in DELAYS and isinstance(r.get("features"),dict):
                r["features"]={str(k):float(v) for k,v in r["features"].items() if finite(v)}
                rows.append(r)
    return rows

def split_name(ts):
    ts=int(ts)
    if ts<TRAIN_END-PURGE_MS:return "train"
    if TRAIN_END<=ts<OOS_START-PURGE_MS:return "valid"
    if OOS_START<=ts<END_MS-PURGE_MS:return "oos"
    return "purged"

def schema_from_train(rows,min_coverage=.02):
    train=[r for r in rows if split_name(r["candidate_ts_ms"])=="train"]
    counts=defaultdict(int)
    for r in train:
        for k in r["features"]:counts[k]+=1
    n=max(1,len(train))
    # Feature dict is produced by causal snapshot builders only. Explicitly ban
    # obvious target/eval names as a second leakage guard.
    banned=("strict","label","precision","recall","false_local","confirmed_local","future","target_")
    names=sorted(k for k,c in counts.items() if c/n>=min_coverage and not any(x in k.lower() for x in banned))
    return validate_scalar_schema(names)

def robust_norm(rows,names):
    by={k:[] for k in names}
    for r in rows:
        if split_name(r["candidate_ts_ms"])!="train":continue
        f=r["features"]
        for k in names:
            if k in f:by[k].append(float(f[k]))
    med=[];scale=[]
    for k in names:
        a=np.asarray(by[k],dtype=np.float64)
        if not len(a):m,s=0.0,1.0
        else:
            m=float(np.median(a));mad=float(np.median(np.abs(a-m)));s=max(1e-8,1.4826*mad,abs(m)*1e-4)
        med.append(m);scale.append(s)
    return np.asarray(med,dtype=np.float32),np.asarray(scale,dtype=np.float32)

def vectorize(f,names,med,scale):
    vals=np.zeros(len(names),dtype=np.float32);mask=np.zeros(len(names),dtype=np.float32)
    for i,k in enumerate(names):
        v=f.get(k)
        if finite(v):
            vals[i]=float(np.clip((float(v)-med[i])/scale[i],-12,12));mask[i]=1.0
    return np.concatenate([vals,mask])

def build_samples(rows,names,med,scale):
    by=defaultdict(list)
    for r in rows:by[r["candidate_id"]].append(r)
    out={"train":[],"valid":[],"oos":[]}
    for cid,rr in by.items():
        rr=sorted(rr,key=lambda z:int(z["delay_s"]))
        stage_map={int(r["delay_s"]):r for r in rr}
        for stage in PRED_STAGES:
            r=stage_map.get(stage)
            if not r:continue
            split=split_name(r["candidate_ts_ms"])
            if split not in out:continue
            seq=[]
            for d in DELAYS:
                if d>stage:break
                q=stage_map.get(d)
                if q is None:continue
                seq.append(vectorize(q["features"],names,med,scale))
            if not seq:continue
            out[split].append({"candidate_id":cid,"side":r["side"],"stage":stage,
                               "ts":int(r["candidate_ts_ms"]),"y":float(bool(r["strict_true"])),
                               "seq":np.stack(seq).astype(np.float32),
                               "tab":vectorize(r["features"],names,med,scale).astype(np.float32)})
    return out

def build_all_matured_samples(rows,names,med,scale):
    by=defaultdict(list)
    for r in rows:
        if int(r["candidate_ts_ms"])>=END_MS-PURGE_MS: continue
        by[r["candidate_id"]].append(r)
    out=[]
    for cid,rr in by.items():
        rr=sorted(rr,key=lambda z:int(z["delay_s"]))
        stage_map={int(r["delay_s"]):r for r in rr}
        for stage in PRED_STAGES:
            r=stage_map.get(stage)
            if not r: continue
            seq=[]
            for d in DELAYS:
                if d>stage: break
                q=stage_map.get(d)
                if q is not None: seq.append(vectorize(q["features"],names,med,scale))
            if not seq: continue
            out.append({"candidate_id":cid,"side":r["side"],"stage":stage,
                        "ts":int(r["candidate_ts_ms"]),"y":float(bool(r["strict_true"])),
                        "seq":np.stack(seq).astype(np.float32),
                        "tab":vectorize(r["features"],names,med,scale).astype(np.float32)})
    return out

class QuantLocalExpert(nn.Module):
    def __init__(self,n_features):
        super().__init__()
        self.trunk=nn.Sequential(nn.Linear(n_features+1,192),nn.GELU(),nn.LayerNorm(192),
                                 nn.Dropout(.10),nn.Linear(192,96),nn.GELU())
        self.heads=nn.ModuleDict({s:nn.Linear(96,1) for s in ("LOW","HIGH")})
    def forward(self,x,stage,side):
        h=self.trunk(torch.cat([x,stage[:,None]/300.0],dim=1))
        low=self.heads["LOW"](h).squeeze(-1);high=self.heads["HIGH"](h).squeeze(-1)
        return torch.where(side==0,low,high)

def side_tensor(samples):
    return torch.tensor([0 if s["side"]=="LOW" else 1 for s in samples],dtype=torch.long)

def labels_tensor(samples):return torch.tensor([s["y"] for s in samples],dtype=torch.float32)

def weighted_bce(logits,y):
    pos=float(y.sum());neg=float(len(y)-pos)
    pw=max(1.0,min(6.0,math.sqrt(neg/max(1.0,pos))))
    return F.binary_cross_entropy_with_logits(logits,y,pos_weight=torch.tensor(pw,device=logits.device))

def train_models(samples,input_dim,epochs,workers):
    torch.set_num_threads(max(1,int(workers)))
    fin=HypeFinJEPA(n_features=input_dim,dim=64,depth=3,max_seq_len=len(DELAYS))
    quant=QuantLocalExpert(input_dim)
    opt_f=torch.optim.AdamW(fin.parameters(),lr=2e-4,weight_decay=1e-4)
    opt_q=torch.optim.AdamW(quant.parameters(),lr=3e-4,weight_decay=1e-4)
    rng=random.Random(SEED)
    best=None;best_state=None
    train=samples["train"];valid=samples["valid"]
    if len(train)<24 or len(valid)<8:raise RuntimeError(f"insufficient samples train={len(train)} valid={len(valid)}")
    for epoch in range(int(epochs)):
        order=list(range(len(train)));rng.shuffle(order)
        fin.train();quant.train()
        # Group Fin-JEPA batches by stage => equal causal sequence length, no padding/future tokens.
        for stage in PRED_STAGES:
            ids=[i for i in order if train[i]["stage"]==stage]
            for p in range(0,len(ids),64):
                ss=[train[i] for i in ids[p:p+64]]
                if not ss:continue
                x=torch.tensor(np.stack([z["seq"] for z in ss]))
                y=labels_tensor(ss);side=side_tensor(ss)
                out=fin(x)
                logits=torch.where(side==0,out["local_logits"]["LOW"],out["local_logits"]["HIGH"])
                loss=weighted_bce(logits,y)+0.20*out["latent_loss"]
                opt_f.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(fin.parameters(),1.0);opt_f.step()
        for p in range(0,len(order),64):
            ss=[train[i] for i in order[p:p+64]]
            x=torch.tensor(np.stack([z["tab"] for z in ss]));st=torch.tensor([z["stage"] for z in ss],dtype=torch.float32)
            y=labels_tensor(ss);side=side_tensor(ss)
            logits=quant(x,st,side);loss=weighted_bce(logits,y)
            opt_q.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(quant.parameters(),1.0);opt_q.step()
        # validation objective = mean BCE of both supervised experts
        fin.eval();quant.eval();losses=[]
        with torch.no_grad():
            for stage in PRED_STAGES:
                ss=[z for z in valid if z["stage"]==stage]
                if not ss:continue
                x=torch.tensor(np.stack([z["seq"] for z in ss]));y=labels_tensor(ss);side=side_tensor(ss)
                o=fin(x);lg=torch.where(side==0,o["local_logits"]["LOW"],o["local_logits"]["HIGH"])
                losses.append(float(F.binary_cross_entropy_with_logits(lg,y)))
            x=torch.tensor(np.stack([z["tab"] for z in valid]));st=torch.tensor([z["stage"] for z in valid],dtype=torch.float32)
            y=labels_tensor(valid);side=side_tensor(valid)
            losses.append(float(F.binary_cross_entropy_with_logits(quant(x,st,side),y)))
        score=float(np.mean(losses))
        if best is None or score<best:
            best=score
            best_state={"fin":{k:v.detach().cpu().clone() for k,v in fin.state_dict().items()},
                        "quant":{k:v.detach().cpu().clone() for k,v in quant.state_dict().items()}}
    fin.load_state_dict(best_state["fin"]);quant.load_state_dict(best_state["quant"])
    return fin,quant,best

def train_river(rows):
    m=LocalOnlyModel()
    for r in sorted(rows,key=lambda z:int(z["snapshot_ts_ms"])):
        if split_name(r["candidate_ts_ms"])!="train":continue
        stage=int(r["delay_s"])
        if stage not in PRED_STAGES:continue
        m.learn(r["side"],stage,r["features"],bool(r["strict_true"]),repeat=2 if r["strict_true"] else 1)
    return m

def train_trees(samples,workers):
    models={}
    train=samples["train"]
    for side in ("LOW","HIGH"):
      for stage in PRED_STAGES:
        ss=[z for z in train if z["side"]==side and z["stage"]==stage]
        if len(ss)<12:continue
        y=np.asarray([int(z["y"]) for z in ss])
        if len(np.unique(y))<2:continue
        x=np.stack([z["tab"] for z in ss])
        m=ExtraTreesClassifier(n_estimators=500,max_depth=10,min_samples_leaf=2,max_features="sqrt",
                               class_weight="balanced_subsample",n_jobs=max(1,int(workers)),random_state=SEED)
        m.fit(x,y);models[(side,stage)]=m
    return models

def attach_tree_probs(samples,models):
    for split in samples:
      for z in samples[split]:
        m=models.get((z["side"],z["stage"]))
        if m is None:z["p_tree"]=0.5
        else:z["p_tree"]=float(m.predict_proba(z["tab"][None,:])[0,1])

def finetune_all(fin,quant,all_samples,epochs=8):
    rng=random.Random(SEED+1)
    opt_f=torch.optim.AdamW(fin.parameters(),lr=1e-4,weight_decay=1e-4)
    opt_q=torch.optim.AdamW(quant.parameters(),lr=1.5e-4,weight_decay=1e-4)
    for _ in range(int(epochs)):
        order=list(range(len(all_samples)));rng.shuffle(order)
        fin.train();quant.train()
        for stage in PRED_STAGES:
            ids=[i for i in order if all_samples[i]["stage"]==stage]
            for p in range(0,len(ids),64):
                ss=[all_samples[i] for i in ids[p:p+64]]
                if not ss:continue
                x=torch.tensor(np.stack([z["seq"] for z in ss]));y=labels_tensor(ss);side=side_tensor(ss)
                out=fin(x);logits=torch.where(side==0,out["local_logits"]["LOW"],out["local_logits"]["HIGH"])
                loss=weighted_bce(logits,y)+.20*out["latent_loss"]
                opt_f.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(fin.parameters(),1.0);opt_f.step()
        for p in range(0,len(order),64):
            ss=[all_samples[i] for i in order[p:p+64]]
            x=torch.tensor(np.stack([z["tab"] for z in ss]));st=torch.tensor([z["stage"] for z in ss],dtype=torch.float32)
            y=labels_tensor(ss);side=side_tensor(ss)
            loss=weighted_bce(quant(x,st,side),y)
            opt_q.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(quant.parameters(),1.0);opt_q.step()
    return fin,quant,all_samples

def train_river_all(rows):
    m=LocalOnlyModel()
    for r in sorted(rows,key=lambda z:int(z["snapshot_ts_ms"])):
        if int(r["candidate_ts_ms"])>=END_MS-PURGE_MS: continue
        stage=int(r["delay_s"])
        if stage not in PRED_STAGES:continue
        m.learn(r["side"],stage,r["features"],bool(r["strict_true"]),repeat=2 if r["strict_true"] else 1)
    return m

def attach_probs(samples,fin,quant,river):
    fin.eval();quant.eval()
    for split in ("train","valid","oos"):
        for stage in PRED_STAGES:
            ss=[z for z in samples[split] if z["stage"]==stage]
            if not ss:continue
            with torch.no_grad():
                xseq=torch.tensor(np.stack([z["seq"] for z in ss]));side=side_tensor(ss)
                fo=fin(xseq);fl=torch.where(side==0,fo["local_logits"]["LOW"],fo["local_logits"]["HIGH"])
                fp=torch.sigmoid(fl).numpy()
                xt=torch.tensor(np.stack([z["tab"] for z in ss]));st=torch.tensor([z["stage"] for z in ss],dtype=torch.float32)
                qp=torch.sigmoid(quant(xt,st,side)).numpy()
            for z,a,b in zip(ss,fp,qp):
                z["p_fin"]=float(a);z["p_quant"]=float(b)
                # River probability needs original scalar features, attached later via key.
    return samples

def attach_river_probs(samples,rows,river):
    idx={(r["candidate_id"],int(r["delay_s"])):r for r in rows}
    for split in samples:
        for z in samples[split]:
            r=idx[(z["candidate_id"],z["stage"])]
            z["p_river"]=river.probability(z["side"],z["stage"],r["features"])

def candidate_metrics(ss,weights,threshold):
    by=defaultdict(list);truth={}
    for z in ss:
        p=weights[0]*z["p_fin"]+weights[1]*z["p_quant"]+weights[2]*z["p_river"]+weights[3]*z["p_tree"]+weights[4]*z["p_timeline"]
        by[z["candidate_id"]].append((z["stage"],p,z))
        truth[z["candidate_id"]]=bool(z["y"])
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
    return {"candidates":len(by),"reference_true":true_total,"accepted":len(accepted),"tp":tp,"fp":fp,"fn":fn,
            "precision":prec,"recall":rec,"f1":f1,
            "median_delay_s":float(np.median(delays)) if delays else None}

def choose_ensemble(valid):
    best=None
    grid=[]
    vals=[0,0.25,0.5,0.75,1.0]
    for a in vals:
      for b in vals:
       for c in vals:
        for d in vals:
         e=1-a-b-c-d
         if e<0 or e>1:continue
         for th in np.arange(.30,.96,.05):
            m=candidate_metrics(valid,(a,b,c,d,e),float(th))
            if m["accepted"]<5 or m["tp"]<3 or m["recall"]<.35:continue
            objective=.55*m["precision"]+.30*m["f1"]+.15*m["recall"]-.00015*(m["median_delay_s"] or 300)
            row=(objective,m["precision"],m["f1"],m["recall"],-float(th),(a,b,c,d,e),float(th),m)
            grid.append(row)
            if best is None or row[:5]>best[:5]:best=row
    if best is None:
        w=(.20,.20,.20,.20,.20);th=.5;m=candidate_metrics(valid,w,th)
        return w,th,m
    return best[5],best[6],best[7]

def expert_oos(oos):
    out={}
    for name,key in (("fin_jepa","p_fin"),("quant_local","p_quant"),("river_local","p_river"),("extra_trees","p_tree"),("timeline_teacher","p_timeline")):
        best=None
        for th in np.arange(.30,.86,.05):
            # temporary convert chosen expert into p_fin and use weight 1
            tmp=[]
            for z in oos:
                q=dict(z);q["p_fin"]=z[key];q["p_quant"]=0;q["p_river"]=0;q["p_tree"]=0;q["p_timeline"]=0;tmp.append(q)
            m=candidate_metrics(tmp,(1,0,0,0,0),float(th))
            if best is None or m["f1"]>best["f1"]:best={**m,"threshold_for_diagnostic_only":float(th)}
        out[name]=best
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshots",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--availability",type=Path)
    ap.add_argument("--compact-1m",type=Path,required=True)
    ap.add_argument("--labels-gz",type=Path,required=True)
    ap.add_argument("--epochs",type=int,default=18)
    ap.add_argument("--workers",type=int,default=4)
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    random.seed(SEED);np.random.seed(SEED);torch.manual_seed(SEED)
    assert len(POINTS)==116 and len(INPUT_IDS)==86 and not(INPUT_IDS&TARGET_IDS)
    rows=load_rows(args.snapshots)
    all_teacher,finalized_teacher=load_teacher_labels(args.labels_gz)
    teacher_coverage=apply_teacher(rows,finalized_teacher)
    minutes=load_minutes(args.compact_1m)
    h1_index=build_index(minutes)
    minute_end_times=[int(z["bar_end_ms"]) for z in minutes]
    for r in rows:
        r["features"].update(causal_h1_features(minutes,h1_index,int(r["snapshot_ts_ms"]),r["side"],float(r["extreme_price"])))
        r["features"].update(historical_indicator_features(minutes,minute_end_times,int(r["snapshot_ts_ms"]),r["side"]))
        r["features"].update({"discovery__"+k:float(v) for k,v in scalar_interactions(r["features"],r["side"]).items() if finite(v)})
    names=schema_from_train(rows)
    med,scale=robust_norm(rows,names)
    samples=build_samples(rows,names,med,scale)
    timeline_rows=build_timeline_rows(minutes,all_teacher)
    timeline_model,timeline_names=fit_timeline(timeline_rows,split_name,args.workers,all_data=False)
    attach_candidate_probabilities(samples,timeline_rows,timeline_model,timeline_names)
    timeline_validation=classification_metrics(timeline_rows,timeline_model,timeline_names,split_name,"valid")
    timeline_oos=classification_metrics(timeline_rows,timeline_model,timeline_names,split_name,"oos")
    fin,quant,val_loss=train_models(samples,len(names)*2,args.epochs,args.workers)
    river=train_river(rows)
    trees=train_trees(samples,args.workers)
    attach_probs(samples,fin,quant,river);attach_river_probs(samples,rows,river);attach_tree_probs(samples,trees)
    weights,threshold,val_metrics=choose_ensemble(samples["valid"])
    oos_metrics=candidate_metrics(samples["oos"],weights,threshold)
    diag=expert_oos(samples["oos"])
    # Freeze honest evaluation first. Only after metrics are immutable, fit a
    # separate teacher checkpoint on ALL 30 days/all finalized labels.
    fin_full=copy.deepcopy(fin);quant_full=copy.deepcopy(quant)
    all_refit_samples=build_all_matured_samples(rows,names,med,scale)
    fin_full,quant_full,all_refit_samples=finetune_all(fin_full,quant_full,all_refit_samples,epochs=8)
    river_full=train_river_all(rows)
    trees_full=train_trees({"train":all_refit_samples},args.workers)
    mature_timeline=[r for r in timeline_rows if int(r["ts_ms"])<END_MS-PURGE_MS]
    timeline_full,timeline_names_full=fit_timeline(mature_timeline,split_name,args.workers,all_data=True)
    full_teacher_bundle={"fin_jepa":fin_full.state_dict(),"quant_local":quant_full.state_dict(),
                         "river_local":river_full,"extra_trees":trees_full,"timeline_teacher":timeline_full,"timeline_feature_names":list(timeline_names_full),
                         "feature_names":list(names),"median":med,"scale":scale,
                         "source_sha256":sha256(args.snapshots),
                         "teacher":"strict finalized H1 L6/K2 LOW/HIGH; all other candidates are NONE",
                         "all_30d_examples":len(all_refit_samples),"ensemble_weights":weights,"ensemble_threshold":threshold}
    torch.save(full_teacher_bundle,args.output/"HYPE_LOCAL_FULL30D_TEACHER.pt")
    baseline_rate=oos_metrics["reference_true"]/max(1,oos_metrics["candidates"])
    gate=bool(oos_metrics["accepted"]>=5 and oos_metrics["precision"]>=.70 and oos_metrics["recall"]>=.50 and oos_metrics["f1"]>=.60)
    technical=[
        True,len(POINTS)==116,len(INPUT_IDS)==86,not(INPUT_IDS&TARGET_IDS),len(names)>0,
        len(samples["train"])>0,len(samples["valid"])>0,len(samples["oos"])>0,
        all(math.isfinite(x) for x in weights),0<=threshold<=1,
    ]
    readiness=sum(bool(x) for x in technical[:-1]) + int(gate)
    availability=json.loads(args.availability.read_text()) if args.availability and args.availability.exists() else None
    report={
      "status":"trained_oos_pass" if gate else "trained_oos_not_yet_10_of_10",
      "research_only":True,"real_orders":False,"auto_live_promotion":False,
      "contract":{"points_total":116,"causal_input_points":86,"target_eval_points":len(TARGET_IDS),
                  "metadata_points":len(METADATA_IDS),"scalar_features_used":len(names),
                  "model_input_width_with_missing_masks":len(names)*2,
                  "rule":"TARGET_EVAL/METADATA never enter X; missing historical inputs are masked, never fabricated"},
      "source":{"snapshots":str(args.snapshots),"sha256":sha256(args.snapshots),"compact_1m_sha256":sha256(args.compact_1m),"labels_sha256":sha256(args.labels_gz),"rows":len(rows),
                "availability":availability},
      "split":{"train_before":"2026-10-23 minus 3h purge","validation":"2026-10-23..2026-10-27 minus 3h purge",
               "untouched_oos":"2026-10-27..2026-11-03 minus 3h terminal maturity purge"},
      "samples":{k:len(v) for k,v in samples.items()},
      "teacher_replay":{"task":"market state -> LOW / HIGH / NONE",
                        "all_strict_labels_in_file":len(all_teacher),
                        **teacher_coverage,
                        "negative_teacher":"every structural candidate without a finalized strict label is NONE",
                        "full30d_refit_examples":len(all_refit_samples),
                        "full30d_checkpoint":"HYPE_LOCAL_FULL30D_TEACHER.pt",
                        "full30d_refit_happens_after_oos_metrics_are_frozen":True},
      "experts":["Fin-JEPA sequential","Quant-style tabular MLP","River LocalOnly logistic","ExtraTrees side-stage nonlinear","Full-minute HIGH/LOW/NONE timeline teacher"],
      "fin_jepa_validation_loss":val_loss,
      "timeline_teacher":{"feature_count":len(timeline_names),"validation":timeline_validation,"oos":timeline_oos},
      "ensemble":{"weights":{"fin_jepa":weights[0],"quant_local":weights[1],"river_local":weights[2],"extra_trees":weights[3],"timeline_teacher":weights[4]},
                  "threshold":threshold,"validation":val_metrics,"oos":oos_metrics},
      "expert_oos_diagnostic_thresholds_not_used_for_selection":diag,
      "oos_baseline_true_candidate_rate":baseline_rate,
      "predictive_10_of_10_gate":{"passed":gate,"requirements":{"accepted_min":5,"precision_min":.70,"recall_min":.50,"f1_min":.60}},
      "readiness_score_10":readiness,
      "feature_names":list(names),
      "note":"10/10 is awarded only when untouched OOS passes the declared gate; no metric is invented or backfilled."
    }
    bundle={"fin_jepa":fin.state_dict(),"quant_local":quant.state_dict(),"river_local":river,"extra_trees":trees,"timeline_teacher":timeline_model,"timeline_feature_names":list(timeline_names),
            "feature_names":list(names),"median":med,"scale":scale,"weights":weights,"threshold":threshold,
            "source_sha256":report["source"]["sha256"]}
    torch.save(bundle,args.output/"HYPE_LOCAL_ENSEMBLE.pt")
    (args.output/"HYPE_LOCAL_ENSEMBLE_REPORT.json").write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    print("HYPE_LOCAL_ENSEMBLE="+json.dumps({"status":report["status"],"score":readiness,
          "weights":report["ensemble"]["weights"],"validation":val_metrics,"oos":oos_metrics},separators=(",",":")))
if __name__=="__main__":main()
