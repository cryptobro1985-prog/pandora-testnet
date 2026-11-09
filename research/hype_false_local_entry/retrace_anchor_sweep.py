#!/usr/bin/env python3
from __future__ import annotations

import argparse,bisect,gzip,json,math
from collections import defaultdict
from pathlib import Path


def load_json_gz(path: Path):
    with gzip.open(path,"rt",encoding="utf-8") as f:
        return json.load(f)


def load_jsonl_gz(path: Path):
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def finalized(labels):
    out=[dict(x) for x in labels if bool(x.get("reference_finalized",True))]
    out.sort(key=lambda x:int(x["extreme_interval_start_ms"]))
    return out


def minute_price(side,row):
    if side=="LOW":
        return float(row.get("close",row.get("open")))
    return float(row.get("close",row.get("open")))


def dense_episode_candidates(mins,labels):
    """Generate every new target-side running extreme and its invalidation."""
    out=[]
    for i in range(1,len(labels)):
        prev,target=labels[i-1],labels[i]
        side=str(target["side"])
        left=int(prev["extreme_interval_start_ms"])
        right=int(target["extreme_interval_end_ms"])
        running=None
        eps=[]
        for r in mins:
            st=int(r["start_ms"])
            end=int(r.get("bar_end_ms",r.get("ts_ms",st+60_000)))
            if end<=left: continue
            if st>right: break
            if side=="LOW":
                px=float(r["low"]);ts=int(r.get("low_ts_ms",st))
                better=running is None or px<running
            else:
                px=float(r["high"]);ts=int(r.get("high_ts_ms",st))
                better=running is None or px>running
            if not better or ts<=left or ts>right:
                continue
            running=px
            c={
                "episode":i,"side":side,
                "target_label_id":int(target["label_id"]),
                "candidate_ts_ms":ts,"candidate_price":px,
                "invalidated_at_ms":None,
                "target_price":float(target["extreme_price"]),
                "target_ts_ms":int(target["extreme_interval_start_ms"]),
                "deadline_ms":int(labels[i+1]["extreme_interval_start_ms"]) if i+1<len(labels) else right+1,
            }
            c["strict_true"]=(
                int(target["extreme_interval_start_ms"])<=ts<=int(target["extreme_interval_end_ms"])
                and math.isclose(px,float(target["extreme_price"]),rel_tol=1e-10,abs_tol=1e-8)
            )
            if eps:
                eps[-1]["invalidated_at_ms"]=ts
            eps.append(c)
        out.extend(eps)
    return out


def precompute_crossings(mins,cands):
    """One causal scan per candidate lifetime; record first crossing for 20..60 bps."""
    starts=[int(r["start_ms"]) for r in mins]
    out={}
    for c in cands:
        side=c["side"];cp=float(c["candidate_price"])
        start=int(c["candidate_ts_ms"])
        stop=int(c["invalidated_at_ms"] or c["deadline_ms"])
        j=max(0,bisect.bisect_left(starts,start-60_000))
        k=min(len(mins),bisect.bisect_left(starts,stop))
        pending=set(range(20,61))
        hits={}
        for r in mins[j:k]:
            end=int(r.get("bar_end_ms",r.get("ts_ms",int(r["start_ms"])+60_000)))
            if end<=start: continue
            px=float(r["close"])
            retr=(px/cp-1.0)*10000.0 if side=="LOW" else (cp/px-1.0)*10000.0
            if retr<20: continue
            reached=[t for t in pending if retr>=t]
            if reached:
                sig={
                    "signal_ts_ms":end,
                    "signal_price":px,
                    "retrace_bps":retr,
                    "latency_s":max(0.0,(end-start)/1000.0),
                }
                for t in reached:
                    hits[t]=sig
                    pending.remove(t)
            if not pending: break
        out[(c["episode"],c["candidate_ts_ms"],c["side"])]=hits
    return out


def score_threshold(crossings,cands,labels,threshold_bps,side):
    byep=defaultdict(list)
    tkey=int(round(threshold_bps))
    for c in cands:
        if c["side"]!=side: continue
        sig=crossings.get((c["episode"],c["candidate_ts_ms"],c["side"]),{}).get(tkey)
        if sig is not None:
            byep[int(c["episode"])].append((sig["signal_ts_ms"],c,sig))

    episodes=0;tp=fp=0;lat=[];distance=[];false_cont=[];signals=[]
    for i in range(1,len(labels)-1):
        target=labels[i]
        if target["side"]!=side: continue
        episodes+=1
        q=byep.get(i) or []
        if not q: continue
        _,c,sig=min(q,key=lambda z:(z[0],z[1]["candidate_ts_ms"]))
        true=bool(c["strict_true"])
        if true:
            tp+=1
            lat.append(sig["latency_s"])
            tp_px=float(c["target_price"]);sp=float(sig["signal_price"])
            dist=max(0.0,(sp/tp_px-1)*10000.0) if side=="LOW" else max(0.0,(tp_px/sp-1)*10000.0)
            distance.append(dist)
        else:
            fp+=1
            cp=float(c["candidate_price"]);tp_px=float(c["target_price"])
            cont=max(0.0,(cp/tp_px-1)*10000.0) if side=="LOW" else max(0.0,(tp_px/cp-1)*10000.0)
            false_cont.append(cont)
        signals.append({
            "episode":i,"candidate_ts_ms":int(c["candidate_ts_ms"]),
            "candidate_price":float(c["candidate_price"]),
            "signal_ts_ms":int(sig["signal_ts_ms"]),
            "signal_price":float(sig["signal_price"]),
            "retrace_bps":float(sig["retrace_bps"]),
            "true_first":true,
        })

    n=tp+fp
    lat.sort();distance.sort();false_cont.sort()
    med=lambda x: None if not x else x[len(x)//2]
    return {
        "threshold_bps":float(threshold_bps),
        "threshold_pct":float(threshold_bps)/100.0,
        "episodes":episodes,"accepted_first":n,
        "true_first":tp,"false_first":fp,
        "precision":tp/n if n else None,
        "recall":tp/episodes if episodes else None,
        "coverage":n/episodes if episodes else None,
        "median_latency_s":med(lat),
        "median_true_distance_bps":med(distance),
        "median_false_continuation_bps":med(false_cont),
        "first_signals":signals,
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--compact",type=Path,required=True)
    ap.add_argument("--labels",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()

    mins=list(load_jsonl_gz(args.compact))
    labs=finalized(load_json_gz(args.labels).get("strict") or [])
    cands=dense_episode_candidates(mins,labs)
    crossings=precompute_crossings(mins,cands)

    sweep={}
    for side in ("LOW","HIGH"):
        rows=[]
        for bps in range(20,61):
            rows.append(score_threshold(crossings,cands,labs,float(bps),side))
        # Rank precision first, then recall, then smaller distance.
        def key(m):
            return (
                m["precision"] or 0.0,
                m["recall"] or 0.0,
                -(m["median_true_distance_bps"] if m["median_true_distance_bps"] is not None else 1e9),
            )
        best=max(rows,key=key)
        near_33=[m for m in rows if 30<=m["threshold_bps"]<=38]
        best_near=max(near_33,key=key)
        sweep[side]={
            "best_20_60bps":best,
            "best_30_38bps":best_near,
            "at_33bps":next(m for m in rows if m["threshold_bps"]==33),
            "at_35bps":next(m for m in rows if m["threshold_bps"]==35),
            "grid":[{k:v for k,v in m.items() if k!="first_signals"} for m in rows],
        }

    report={
        "version":"HYPE-DENSE-RETRACE-ANCHOR-SWEEP-v1",
        "teacher":"STRICT_L6_K2_REFERENCE_FINALIZED_ONLY",
        "candidate_contract":"EVERY_NEW_RUNNING_EXTREME_WITH_IMMEDIATE_INVALIDATION",
        "crossing":"first completed-M1 close reaching retracement threshold",
        "note":"Price retracement is an anchor only, not sufficient Local confirmation. Next stage overlays causal 116-input signature at/around the crossing.",
        "dense_candidates":len(cands),
        "by_side":sweep,
        "real_orders":False,
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("RETRACE_ANCHOR_SWEEP="+json.dumps({
        s:{
            "best":{k:v for k,v in sweep[s]["best_20_60bps"].items() if k!="first_signals"},
            "near33":{k:v for k,v in sweep[s]["best_30_38bps"].items() if k!="first_signals"},
            "at33":{k:v for k,v in sweep[s]["at_33bps"].items() if k!="first_signals"},
            "at35":{k:v for k,v in sweep[s]["at_35bps"].items() if k!="first_signals"},
        } for s in ("LOW","HIGH")
    },separators=(",",":")))


if __name__=="__main__":
    main()
