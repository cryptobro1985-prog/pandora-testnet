#!/usr/bin/env python3
"""Mine true-vs-false Local relationships from matured live labels.

Consumes only examples whose strict H1 L6/K2 label has matured. Supports dynamic
feature names, so newly observed L50/liquidation/pattern features can become
relationship candidates without changing the canonical 116-point contract.
"""
from __future__ import annotations
import argparse,json,math,statistics
from collections import defaultdict
from pathlib import Path

def finite(v):return isinstance(v,(int,float)) and math.isfinite(v)

def load(path):
    rows=[]
    if not path.exists():return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():continue
        try:r=json.loads(line)
        except Exception:continue
        if r.get("side") in ("LOW","HIGH") and int(r.get("stage",0)) in (60,180,300) and isinstance(r.get("features"),dict):
            r["features"]={str(k):float(v) for k,v in r["features"].items() if finite(v)}
            rows.append(r)
    return rows

def robust(vals):
    vals=[float(v) for v in vals if finite(v)]
    if not vals:return 0.0,1.0
    med=statistics.median(vals);mad=statistics.median(abs(v-med) for v in vals)
    return med,max(1e-9,1.4826*mad,abs(med)*.02)

def effects(rows):
    names=sorted({k for r in rows for k in r["features"]})
    out=[]
    for k in names:
        pos=[r["features"][k] for r in rows if r.get("label") is True and k in r["features"]]
        neg=[r["features"][k] for r in rows if r.get("label") is False and k in r["features"]]
        if len(pos)<3 or len(neg)<5:continue
        med,scale=robust(pos+neg)
        e=(statistics.median(pos)-statistics.median(neg))/scale
        if not math.isfinite(e):continue
        out.append({"feature":k,"effect":e,"median":med,"scale":scale,
                    "positive_median":statistics.median(pos),"negative_median":statistics.median(neg),
                    "positive_support":len(pos),"negative_support":len(neg),"support":len(pos)+len(neg),
                    "family":("discovery" if k.startswith("discovery__") else "canonical_or_live")})
    out.sort(key=lambda z:(abs(z["effect"]),z["support"]),reverse=True)
    return out

def pairs(rows,fx):
    base=sum(bool(r.get("label")) for r in rows)/max(1,len(rows));out=[]
    top=fx[:16]
    for i,a in enumerate(top):
        for b in top[i+1:]:
            sat=[]
            for r in rows:
                f=r["features"]
                if a["feature"] not in f or b["feature"] not in f:continue
                aa=f[a["feature"]]>=a["median"] if a["effect"]>0 else f[a["feature"]]<=a["median"]
                bb=f[b["feature"]]>=b["median"] if b["effect"]>0 else f[b["feature"]]<=b["median"]
                if aa and bb:sat.append(r)
            if len(sat)<6:continue
            rate=sum(bool(r.get("label")) for r in sat)/len(sat)
            out.append({"a":a["feature"],"b":b["feature"],"support":len(sat),
                        "positive_rate":rate,"baseline_rate":base,"lift":rate/max(base,1e-9)})
    out.sort(key=lambda z:(z["lift"],z["support"]),reverse=True)
    return out[:50]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--labels",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    rows=load(args.labels);heads={}
    for side in ("LOW","HIGH"):
      for stage in (60,180,300):
        rr=[r for r in rows if r["side"]==side and int(r["stage"])==stage]
        fx=effects(rr)
        heads[f"{side}_{stage}s"]={
          "examples":len(rr),"true_examples":sum(bool(r.get("label")) for r in rr),
          "false_examples":sum(not bool(r.get("label")) for r in rr),
          "discovery_feature_names_seen":len({k for r in rr for k in r["features"] if k.startswith("discovery__")}),
          "top_feature_relationships":fx[:80],"top_pair_relationships":pairs(rr,fx)
        }
    out={"version":"HYPE-LIVE-DISCOVERY-RELATIONSHIPS-v1","teacher":"H1_L6_K2_STRICT matured only",
         "labels_total":len(rows),"heads":heads}
    args.output.write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("LIVE_DISCOVERY="+json.dumps({"labels_total":len(rows),
      "heads":{k:{"n":v["examples"],"true":v["true_examples"],"discovery_features":v["discovery_feature_names_seen"]} for k,v in heads.items()}},separators=(",",":")))
if __name__=="__main__":main()
