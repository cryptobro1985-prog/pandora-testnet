"""Train Fin-JEPA LOW/HIGH on 30-day candidate snapshots without future leakage.

Requires real candidate_snapshots.jsonl.gz and an explicit ordered 116-feature
schema. Historical labels are used ONLY as targets; validation/OOS never fit.
Research-only: does not overwrite Local-Only, Quant, or Cortex checkpoints.
"""
from __future__ import annotations
import argparse,gzip,json,random,hashlib
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from research.hype_local_only.fin_jepa_adapter import HypeFinJEPA,validate_contract
from research.hype_local_only.train_history import TRAIN_END,OOS_START

def load_rows(path):
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r=json.loads(line)
                if r.get("side") in ("LOW","HIGH") and isinstance(r.get("features"),dict):
                    yield r

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--snapshots",type=Path,required=True)
    p.add_argument("--schema",type=Path,required=True,help="JSON list of 116 ordered feature names")
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--epochs",type=int,default=12)
    p.add_argument("--workers",type=int,default=4)
    args=p.parse_args()
    torch.set_num_threads(max(1,args.workers))
    random.seed(42);np.random.seed(42);torch.manual_seed(42)
    names=validate_contract(json.loads(args.schema.read_text()))
    rows=sorted(load_rows(args.snapshots),key=lambda r:int(r["candidate_ts_ms"]))
    if not rows:raise RuntimeError("No actual historical snapshots")
    # Require complete features; never zero-impute absent OI/book/flow families.
    rows=[r for r in rows if all(k in r["features"] and isinstance(r["features"][k],(int,float))
                               and np.isfinite(r["features"][k]) for k in names)]
    if not rows:raise RuntimeError("No complete 116-feature rows; cannot claim 116-feature training")
    def split(r):
        t=int(r["candidate_ts_ms"])
        return "train" if t<TRAIN_END else "valid" if t<OOS_START else "oos"
    partitions={s:[r for r in rows if split(r)==s] for s in ("train","valid","oos")}
    if min(map(len,partitions.values()))<16:raise RuntimeError("Insufficient chronological train/valid/OOS coverage")
    # Prevent target overlap across boundaries: labels mature after candidate extreme.
    # Conservatively purge 3 hours before each boundary (H1 L6/K2 target).
    partitions["train"]=[r for r in partitions["train"] if int(r["candidate_ts_ms"])<TRAIN_END-10800000]
    partitions["valid"]=[r for r in partitions["valid"] if int(r["candidate_ts_ms"])<OOS_START-10800000]
    if min(map(len,partitions.values()))<16:raise RuntimeError("Insufficient purged train/valid/OOS coverage")
    med=np.median(np.array([[r["features"][k] for k in names] for r in partitions["train"]],dtype=np.float32),axis=0)
    mad=np.median(np.abs(np.array([[r["features"][k] for k in names] for r in partitions["train"]],dtype=np.float32)-med)),axis=0)
    scale=np.maximum(mad*1.4826,1e-6)
    def sequences(part,steps=8):
        # Never join different sides or cross >5m gaps in a sequential sample.
        x=[];ys={"LOW":[],"HIGH":[]}
        for i in range(steps-1,len(part)):
            window=part[i-steps+1:i+1]
            if len({r["side"] for r in window})!=1:continue
            ts=[int(r["candidate_ts_ms"]) for r in window]
            if any(b<=a or b-a>300000 for a,b in zip(ts,ts[1:])):continue
            arr=np.array([[r["features"][k] for k in names] for r in window],dtype=np.float32)
            x.append(np.clip((arr-med)/scale,-20,20))
            for side in ys:ys[side].append(float(window[-1]["strict_true"] and window[-1]["side"]==side))
        if not x:return None
        return torch.tensor(np.stack(x)),{k:torch.tensor(v) for k,v in ys.items()}
    data={s:sequences(v) for s,v in partitions.items()}
    if any(v is None for v in data.values()):raise RuntimeError("No continuous 116-feature sequences in one or more chronological partitions")
    model=HypeFinJEPA();optimizer=torch.optim.AdamW(model.parameters(),lr=2e-4)
    def evaluate(dataset):
        model.eval();x,y=dataset
        with torch.no_grad():
            out=model(x);scores={s:torch.sigmoid(out["local_logits"][s]).numpy() for s in y}
        metrics={}
        for s in y:
            labels=y[s].numpy().astype(bool);pred=scores[s]>=0.5
            tp=int((pred&labels).sum());fp=int((pred&~labels).sum());fn=int((~pred&labels).sum())
            metrics[s]={"n":len(labels),"positives":int(labels.sum()),"tp":tp,"fp":fp,"fn":fn,
                        "precision":tp/(tp+fp) if tp+fp else None,"recall":tp/(tp+fn) if tp+fn else None}
        return metrics
    best=float("inf");best_state=None
    for epoch in range(args.epochs):
        model.train();x,y=data["train"];order=torch.randperm(len(x))
        for ids in order.split(64):
            optimizer.zero_grad();loss,_=model.supervised_loss(x[ids],{s:v[ids] for s,v in y.items()})
            loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1.0);optimizer.step()
        model.eval()
        with torch.no_grad():
            vx,vy=data["valid"];vl,_=model.supervised_loss(vx,vy);score=float(vl)
        if score<best:best=score;best_state={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
    model.load_state_dict(best_state)
    metrics={s:evaluate(data[s]) for s in data}
    args.output.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(args.snapshots.read_bytes()).hexdigest()
    report={"status":"trained_research_only","feature_count":116,"feature_names":list(names),
            "dataset_sha256":digest,"rows":{s:len(v) for s,v in partitions.items()},
            "sequences":{s:len(data[s][0]) for s in data},"metrics":metrics,
            "validation_loss":best,"no_live_promotion":True,
            "warning":"Candidate-level metrics are NOT first-signal swing precision or proven trading performance"}
    torch.save({"state_dict":best_state,"feature_names":list(names),"median":med.tolist(),
                "scale":scale.tolist(),"dataset_sha256":digest},args.output/"fin_jepa_research.pt")
    (args.output/"fin_jepa_report.json").write_text(json.dumps(report,indent=2))
    print(json.dumps({"status":report["status"],"metrics":metrics,"rows":report["rows"]}))
if __name__=="__main__":main()
