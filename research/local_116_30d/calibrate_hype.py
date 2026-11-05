from __future__ import annotations
import argparse, gzip, json, math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

DISCOVERY=int(datetime(2026,10,11,tzinfo=timezone.utc).timestamp()*1000)
TRAIN_END=int(datetime(2026,10,23,tzinfo=timezone.utc).timestamp()*1000)
OOS=int(datetime(2026,10,27,tzinfo=timezone.utc).timestamp()*1000)
END=int(datetime(2026,11,3,tzinfo=timezone.utc).timestamp()*1000)

def load(path):
    rows=[]
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows

def side_norm(row):
    f=dict(row["features"])
    low=row["side"]=="LOW"
    for h in ("60m","6h","24h"):
        p=f.get("position_"+h)
        dl=f.get("distance_low_"+h+"_bps")
        dh=f.get("distance_high_"+h+"_bps")
        if p is not None:
            f["extreme_position_"+h]=p if low else 1-p
        if dl is not None and dh is not None:
            f["away_from_extreme_"+h+"_bps"]=dl if low else dh
    for w in (5,15,30,60,180,300):
        a=f.get(f"rev_eff_{w}s");b=f.get(f"old_eff_{w}s")
        if a is not None and b is not None:
            f[f"eff_delta_{w}s"]=a-b
    return {**row,"features":f}

def metrics(rows,rule,start,end):
    selected=[r for r in rows if start<=r["candidate_ts_ms"]<end and r["side"]==rule["side"] and r["delay_s"]==rule["delay_s"]]
    true_total=sum(bool(r["strict_true"]) for r in selected)
    accepted=[]
    for r in selected:
        f=r["features"]
        if f.get("retrace_bps",-1)<rule["min_retrace_bps"]:continue
        if f.get("extreme_position_60m",-1)<rule["min_extreme_position_60m"]:continue
        if f.get("extreme_position_6h",-1)<rule["min_extreme_position_6h"]:continue
        if f.get("eff_delta_30s",-999)<rule["min_eff_delta_30s"]:continue
        if f.get("rev_eff_60s",-999)<rule["min_rev_eff_60s"]:continue
        accepted.append(r)
    tp=sum(bool(r["strict_true"]) for r in accepted)
    n=len(accepted)
    return {
        "accepted":n,"true":tp,"false":n-tp,
        "precision":tp/n if n else None,
        "recall":tp/true_total if true_total else None,
        "reference_true_candidates":true_total,
    }

def choose(rows,side,stage):
    delays=sorted({r["delay_s"] for r in rows if r["side"]==side})
    if stage=="FORMING":
        allowed=[d for d in delays if d>=60]
        min_precision=.18; min_recall=.45
    elif stage=="CONFIRMED":
        allowed=[d for d in delays if d>=300]
        min_precision=.30; min_recall=.20
    else:
        allowed=[d for d in delays if d>=600]
        min_precision=.40; min_recall=.10
    if not allowed:
        allowed=[max(delays)]
    grid=[]
    for delay in allowed:
      for retr in (10,15,20,25,30,35,40,50,60,75):
       for p60 in (0.05,0.10,0.15,0.20,0.25,0.30,0.40):
        for p6 in (0.0,0.05,0.10,0.15):
         for ed in (-.01,0.0,.001,.003,.005,.01):
          for re60 in (0.0,.0005,.001,.003,.005):
            rule={"side":side,"stage":stage,"delay_s":delay,
                  "min_retrace_bps":retr,"min_extreme_position_60m":p60,
                  "min_extreme_position_6h":p6,"min_eff_delta_30s":ed,
                  "min_rev_eff_60s":re60}
            tr=metrics(rows,rule,DISCOVERY,TRAIN_END)
            va=metrics(rows,rule,TRAIN_END,OOS)
            if not va["accepted"] or va["accepted"]<3:continue
            p=va["precision"] or 0;r=va["recall"] or 0
            # Precision first. Recall and simplicity are tie-breakers.
            target=(p>=min_precision and r>=min_recall)
            objective=(1 if target else 0,p,r,-va["accepted"],-delay,-retr)
            grid.append((objective,rule,tr,va))
    if not grid:
        raise RuntimeError(f"no candidate rules for {side} {stage}")
    grid.sort(key=lambda x:x[0],reverse=True)
    _,rule,tr,va=grid[0]
    oo=metrics(rows,rule,OOS,END)
    return {"rule":rule,"train":tr,"validation":va,"oos":oo,
            "selection":"validation precision-first with stage-specific minimum recall; OOS untouched by selection"}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshots",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    rows=[side_norm(r) for r in load(args.snapshots)]
    if {r["symbol"] for r in rows}!={"HYPE"}:
        raise SystemExit("HYPE-only calibrator refuses non-HYPE data")
    result={"symbol":"HYPE","states":{},"notes":[
        "Every state requires candidate survival to the selected causal delay.",
        "Any new same-side extreme invalidates the older candidate before it can advance.",
        "LOW and HIGH are calibrated independently.",
        "No historical unavailable L50/OI/liquidation inputs are synthesized."
    ]}
    for side in ("LOW","HIGH"):
        result["states"][side]={}
        for stage in ("FORMING","CONFIRMED","HARD_CONFIRMED"):
            result["states"][side][stage]=choose(rows,side,stage)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/"hype_local_states.json").write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n")
    print("HYPE_LOCAL_STATES="+json.dumps(result,separators=(",",":"),sort_keys=True))

if __name__=="__main__":
    main()
