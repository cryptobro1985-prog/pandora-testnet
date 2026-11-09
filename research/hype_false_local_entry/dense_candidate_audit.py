#!/usr/bin/env python3
from __future__ import annotations
import argparse,gzip,json,math
from collections import Counter
from pathlib import Path


def load_json_gz(path):
    with gzip.open(path,"rt",encoding="utf-8") as f:return json.load(f)


def load_jsonl_gz(path):
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip():yield json.loads(line)


def finalized(labels):
    out=[dict(x) for x in labels if bool(x.get("reference_finalized",True))]
    out.sort(key=lambda x:int(x["extreme_interval_start_ms"]))
    return out


def dense_swing_candidates(mins,labels):
    starts=[int(x["start_ms"]) for x in mins]
    out=[]
    for i in range(1,len(labels)):
        prev,target=labels[i-1],labels[i]
        side=str(target["side"])
        left=int(prev["extreme_interval_start_ms"])
        right=int(target["extreme_interval_end_ms"])
        running=None
        for r in mins:
            st=int(r["start_ms"]);end=int(r.get("bar_end_ms",r.get("ts_ms",st+60000)))
            if end<=left:continue
            if st>right:break
            if side=="LOW":
                px=float(r["low"]);ts=int(r.get("low_ts_ms",st))
                better=running is None or px<running
            else:
                px=float(r["high"]);ts=int(r.get("high_ts_ms",st))
                better=running is None or px>running
            if not better or ts<=left or ts>right:continue
            running=px
            true=(int(target["extreme_interval_start_ms"])<=ts<=int(target["extreme_interval_end_ms"])
                  and math.isclose(px,float(target["extreme_price"]),rel_tol=1e-12,abs_tol=1e-10))
            out.append({
                "episode":i,"target_label_id":int(target["label_id"]),"side":side,
                "candidate_ts_ms":ts,"candidate_price":px,"strict_true":bool(true),
            })
    return out


def legacy_6h_candidates(mins,labels):
    def matches(side,ts,px):
        for x in labels:
            if x["side"]!=side:continue
            if int(x["extreme_interval_start_ms"])<=ts<=int(x["extreme_interval_end_ms"]) and math.isclose(
                px,float(x["extreme_price"]),rel_tol=1e-12,abs_tol=1e-10):
                return int(x["label_id"])
        return None
    out=[];lows=[];highs=[]
    for i,r in enumerate(mins):
        if i>=360:
            recent=mins[i-360:i+1]
            contiguous=all(int(b["start_ms"])-int(a["start_ms"])==60000 for a,b in zip(recent,recent[1:]))
            if contiguous:
                lo=min(lows[-360:]);hi=max(highs[-360:])
                if float(r["low"])<lo:
                    ts=int(r.get("low_ts_ms",r["start_ms"]));px=float(r["low"])
                    lid=matches("LOW",ts,px)
                    out.append({"side":"LOW","candidate_ts_ms":ts,"candidate_price":px,"strict_true":lid is not None})
                if float(r["high"])>hi:
                    ts=int(r.get("high_ts_ms",r["start_ms"]));px=float(r["high"])
                    lid=matches("HIGH",ts,px)
                    out.append({"side":"HIGH","candidate_ts_ms":ts,"candidate_price":px,"strict_true":lid is not None})
        lows.append(float(r["low"]));highs.append(float(r["high"]))
    return out


def summarize(rows):
    d={}
    for side in ("LOW","HIGH"):
        q=[r for r in rows if r["side"]==side]
        ep=Counter(r.get("episode") for r in q)
        d[side]={
            "candidates":len(q),
            "true_candidates":sum(bool(r["strict_true"]) for r in q),
            "false_candidates":sum(not bool(r["strict_true"]) for r in q),
            "false_per_true":(sum(not bool(r["strict_true"]) for r in q)/max(1,sum(bool(r["strict_true"]) for r in q))),
            "episodes":len([k for k in ep if k is not None]),
            "median_candidates_per_episode":None,
        }
        counts=sorted(v for k,v in ep.items() if k is not None)
        if counts:
            d[side]["median_candidates_per_episode"]=counts[len(counts)//2]
            d[side]["p90_candidates_per_episode"]=counts[min(len(counts)-1,int(.9*(len(counts)-1)))]
            d[side]["max_candidates_per_episode"]=max(counts)
    return d


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--compact",type=Path,required=True)
    ap.add_argument("--labels",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    mins=list(load_jsonl_gz(args.compact))
    labs=finalized(load_json_gz(args.labels).get("strict") or [])
    dense=dense_swing_candidates(mins,labs)
    legacy=legacy_6h_candidates(mins,labs)
    dense_keys={(x["side"],x["candidate_ts_ms"],round(x["candidate_price"],10)) for x in dense}
    legacy_keys={(x["side"],x["candidate_ts_ms"],round(x["candidate_price"],10)) for x in legacy}
    report={
        "teacher":"STRICT_L6_K2_REFERENCE_FINALIZED_ONLY",
        "dense_definition":"every new target-side running extreme between consecutive finalized teacher locals",
        "legacy_definition":"new 6h rolling extreme",
        "labels":len(labs),
        "dense":summarize(dense),
        "legacy":summarize(legacy),
        "overlap":{
            "dense_candidates_also_legacy":len(dense_keys&legacy_keys),
            "dense_candidates_missing_from_legacy":len(dense_keys-legacy_keys),
            "legacy_candidates_outside_dense_swing_space":len(legacy_keys-dense_keys),
            "dense_coverage_by_legacy":len(dense_keys&legacy_keys)/max(1,len(dense_keys)),
        },
        "conclusion":"Training on legacy 6h candidates is distribution-mismatched if dense coverage is low.",
        "real_orders":False,
    }
    args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    print("DENSE_CANDIDATE_AUDIT="+json.dumps(report,separators=(",",":")))


if __name__=="__main__":main()
