"""Audit causal features of the first dense core flip in every strict swing."""
import argparse,json
from pathlib import Path
from statistics import median
import numpy as np
from sklearn.metrics import roc_auc_score

from .dense_post_local_model_cv import load, build_events, feature_names


def first_rows(rows):
    g={}
    for r in sorted(rows,key=lambda x:x["ts_ms"]):
        g.setdefault((r["period"],r["interval"]),r)
    return list(g.values())


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--period",action="append",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args()
    periods=[]
    for spec in args.period:
        n,b=spec.split("=",1); periods.append(load(b,n))
    by={}
    allr=[]
    for per in periods:
        rr=first_rows(build_events(per)); by[per["name"]]=rr; allr+=rr
    names=feature_names(allr)
    out={}
    for side in ("LOW","HIGH"):
        rec=[]
        for name in names:
            perstats={}
            aucs=[]
            directions=[]
            for period,rr in by.items():
                z=[r for r in rr if r["signal_side"]==side]
                y=[r["y"] for r in z]
                x=[float(r["features"].get(name,0.0) or 0.0) for r in z]
                true=[v for v,t in zip(x,y) if t==1]; false=[v for v,t in zip(x,y) if t==0]
                if len(set(y))<2:
                    auc=None
                else:
                    auc=float(roc_auc_score(y,x))
                    aucs.append(max(auc,1-auc))
                    directions.append(1 if auc>=0.5 else -1)
                perstats[period]={"n":len(z),"true":len(true),"wrong":len(false),
                                  "true_median":median(true) if true else None,
                                  "wrong_median":median(false) if false else None,
                                  "auc":auc}
            valid=[a for a in aucs if a is not None]
            consistent=len(set(directions))<=1 if directions else False
            direction=("HIGHER_IS_TRUE" if directions and directions[0]==1 else
                       "LOWER_IS_TRUE" if directions else None)
            rec.append({"feature":name,"consistent_direction":consistent,
                        "direction":direction,
                        "worst_auc_strength":min(valid) if valid else None,
                        "median_auc_strength":median(valid) if valid else None,
                        "periods":perstats})
        rec.sort(key=lambda r:(
            1 if r["consistent_direction"] else 0,
            r["worst_auc_strength"] if r["worst_auc_strength"] is not None else -1,
            r["median_auc_strength"] if r["median_auc_strength"] is not None else -1
        ),reverse=True)
        out[side]=rec
        print("TOP",side,json.dumps([{k:v for k,v in r.items() if k!="periods"} for r in rec[:20]],separators=(",",":")))
        for r in rec[:8]:
            print("DETAIL",side,r["feature"],json.dumps(r["periods"],separators=(",",":")))
    result={"status":"research_only_orders_off","by_signal_side":out}
    Path(args.out).write_text(json.dumps(result,indent=2)+"\n")


if __name__=="__main__":main()
