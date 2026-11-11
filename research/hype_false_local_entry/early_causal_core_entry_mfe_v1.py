#!/usr/bin/env python3
from __future__ import annotations
import argparse,gzip,json,bisect,statistics
from pathlib import Path

from research.hype_false_local_entry.causal_sequential_engine import CausalReversalMachine
from research.hype_false_local_entry.first_flip_path_audit import score_first_flips

def read_jsonl_gz(p):
    out=[]
    with gzip.open(p,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip(): out.append(json.loads(line))
    return out

def read_json_gz(p):
    with gzip.open(p,"rt",encoding="utf-8") as f:return json.load(f)

def finalized(doc,key):
    rows=[dict(x) for x in (doc.get(key) or []) if bool(x.get("reference_finalized",True))]
    rows.sort(key=lambda x:int(x["extreme_interval_start_ms"]))
    return rows

def bar_end(b):
    if b.get("bar_end_ms") is not None:return int(b["bar_end_ms"])
    if b.get("start_ms") is not None:return int(b["start_ms"])+int(b.get("interval_ms",60000))
    return int(b["ts_ms"])

def run_engine(bars):
    e=CausalReversalMachine(reset_anchors_on_flip=True)
    flips=[]
    for b in sorted(bars,key=bar_end):
        for s in e.on_bar(b):
            if s.core_flip:flips.append(s)
    return flips

def q(v,p):
    if not v:return None
    z=sorted(float(x) for x in v);x=(len(z)-1)*p;i=int(x);j=min(i+1,len(z)-1);w=x-i
    return z[i]*(1-w)+z[j]*w

def trade_path(bars,labels,matched):
    labs=sorted(labels,key=lambda x:int(x["extreme_interval_start_ms"]))
    byid={str(x.get("label_id")):i for i,x in enumerate(labs)}
    out=[]
    for r in matched[:-1]:
        if not r.get("first_signal_present"):continue
        idx=byid.get(str(r.get("label_id")))
        if idx is None or idx+1>=len(labs):continue
        local=labs[idx];nxt=labs[idx+1]
        sig_ts=int(r["signal_ts_ms"]);entry=float(r["entry_price"]);side=str(r["signal_side"])
        sign=1 if side=="LOW" else -1
        stop=int(nxt["extreme_interval_start_ms"])
        path=[b for b in bars if sig_ts < bar_end(b) <= stop]
        mfe=mae=0.0
        if path:
            for b in path:
                hi=float(b["high"]);lo=float(b["low"])
                fav=(hi/entry-1) if sign==1 else (1-lo/entry)
                adv=(1-lo/entry) if sign==1 else (hi/entry-1)
                mfe=max(mfe,fav,0.0);mae=max(mae,adv,0.0)
        correct=(side==str(local["side"]))
        target=float(nxt["extreme_price"])
        realized=sign*(target/entry-1)
        out.append({
          "label_id":r.get("label_id"),"teacher_side":local["side"],"signal_side":side,
          "correct_first":correct,"lag_min":(sig_ts-int(local["extreme_interval_start_ms"]))/60000,
          "entry_distance_pct":abs(entry/float(local["extreme_price"])-1)*100,
          "mfe_pct":100*mfe,"mae_pct":100*mae,
          "to_next_local_pct":100*realized
        })
    return out

def summary(rows):
    correct=[r for r in rows if r["correct_first"]];wrong=[r for r in rows if not r["correct_first"]]
    def dist(key,rr):
        v=[r[key] for r in rr]
        return {"median":q(v,.5),"p90":q(v,.9),"p95":q(v,.95),"max":max(v) if v else None}
    return {
      "signals":len(rows),"correct":len(correct),"wrong":len(wrong),
      "direction_precision_given_first":len(correct)/len(rows) if rows else None,
      "correct_lag_min":dist("lag_min",correct),
      "correct_entry_distance_pct":dist("entry_distance_pct",correct),
      "correct_mfe_pct":dist("mfe_pct",correct),
      "correct_mae_pct":dist("mae_pct",correct),
      "wrong_mae_pct":dist("mae_pct",wrong),
      "wrong_mfe_pct":dist("mfe_pct",wrong),
      "wrong_to_next_local_pct":dist("to_next_local_pct",wrong),
      "rows":rows
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--block",action="append",nargs=3,metavar=("NAME","COMPACT","LABELS"),required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    result={"version":"HYPE-EARLY-CAUSAL-CORE-ENTRY-MFE-v1","research_only":True,"real_orders":False,"blocks":{}}
    agg={"internal":[],"strict":[]}
    for name,cp,lp in a.block:
        bars=read_jsonl_gz(Path(cp));doc=read_json_gz(Path(lp));flips=run_engine(bars)
        b={}
        for key in ("internal","strict"):
            labs=finalized(doc,key)
            score=score_first_flips(bars,labs,flips,max_lag_ms=24*3600*1000)
            rows=trade_path(bars,labs,score["matched"])
            b[key]={"score":{k:v for k,v in score.items() if k not in ("matched","unassigned_false_flips","caveats")},
                    "trade_geometry":summary(rows)}
            agg[key]+=rows
        b["total_core_flips"]=len(flips)
        result["blocks"][name]=b
    result["aggregate"]={k:summary(v) for k,v in agg.items()}
    result["limitations"]=[
      "This reproduces the checked-in CausalReversalMachine, not the later Ultra detector.",
      "Teacher labels are used only after causal signal generation for scoring and path geometry.",
      "No execution latency/slippage/mark-price liquidation model.",
      "This baseline still includes wrong-first and duplicate core-flip behavior; veto/dedupe is the next optimization target."
    ]
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps({"aggregate":{k:{kk:vv for kk,vv in v.items() if kk!="rows"} for k,v in result["aggregate"].items()}},ensure_ascii=False))
if __name__=="__main__":main()
