#!/usr/bin/env python3
"""Reproduce the exact 30D HARD120 first-signal audit from canonical artifacts.

Inputs are the canonical compact M1 tape and INTERNAL terminal labels. Candidate
generation is label-blind. Labels are used only after candidate generation to
score the first actionable signal per completed swing.

The replay intentionally mirrors INTERNAL_HARD120_CHECKPOINT_V2:
- candidate must be a 6h trailing extreme;
- causal 180 completed M1 bars define the pre-move;
- a more-extreme same-side 6h candidate replaces the lineage;
- HARD120 is sampled once at the first completed M1 bar at/after +120m;
- signal must happen before the next opposite finalized Local extreme;
- no late recovery crossing is accepted.
"""
from __future__ import annotations

import argparse
import bisect
import gzip
import json
import statistics
from collections import deque
from pathlib import Path
from typing import Any

HARD_AGE_MS=7_200_000
MIN_RETRACE_BPS=40.0
MIN_RETRACE_FRAC=0.45
LOOKBACKS=(5,15,60,180,360)


def read_jsonl_gz(path:Path)->list[dict[str,Any]]:
    out=[]
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip():out.append(json.loads(line))
    return out


def read_json_gz(path:Path)->dict[str,Any]:
    with gzip.open(path,"rt",encoding="utf-8") as f:return json.load(f)


def generate_candidates(bars:list[dict[str,Any]])->list[dict[str,Any]]:
    hist=deque(maxlen=max(LOOKBACKS));out=[]
    for b in bars:
        prior=list(hist);lo=float(b["low"]);hi=float(b["high"])
        low_hits=[];high_hits=[]
        for n in LOOKBACKS:
            if len(prior)<n:continue
            win=prior[-n:]
            if lo<=min(float(x["low"]) for x in win):low_hits.append(n)
            if hi>=max(float(x["high"]) for x in win):high_hits.append(n)
        if low_hits:
            out.append({
                "side":"LOW","extreme_ts_ms":int(b.get("low_ts_ms") or b["start_ms"]),
                "signal_ts_ms":int(b["bar_end_ms"]),"bar_start_ms":int(b["start_ms"]),
                "extreme_price":lo,"lookbacks_m":low_hits,
            })
        if high_hits:
            out.append({
                "side":"HIGH","extreme_ts_ms":int(b.get("high_ts_ms") or b["start_ms"]),
                "signal_ts_ms":int(b["bar_end_ms"]),"bar_start_ms":int(b["start_ms"]),
                "extreme_price":hi,"lookbacks_m":high_hits,
            })
        hist.append(b)
    return out


def pre_move_180_bps(side:str,price:float,idx:int,bars:list[dict[str,Any]])->float:
    if idx<180:return 0.0
    prior=bars[idx-180:idx]
    if side=="LOW":
        opp=max(float(x["high"]) for x in prior)
        return max(0.0,(opp/price-1.0)*10_000.0)
    opp=min(float(x["low"]) for x in prior)
    return max(0.0,(price/opp-1.0)*10_000.0) if opp>0 else 0.0


def more_extreme(side:str,new:float,old:float)->bool:
    return new<old if side=="LOW" else new>old


def checkpoint(candidate:dict[str,Any],end_ms:int,bars:list[dict[str,Any]],
               end_times:list[int],closes:list[float])->dict[str,Any]|None:
    target=int(candidate["extreme_ts_ms"])+HARD_AGE_MS
    i=bisect.bisect_left(end_times,target)
    if i>=len(bars) or int(end_times[i])>=int(end_ms):
        return None
    mark=float(closes[i]);p=float(candidate["extreme_price"])
    retrace=((mark/p-1.0)*10_000.0 if candidate["side"]=="LOW"
             else (p/mark-1.0)*10_000.0)
    pm=float(candidate["pre_move_180_bps"])
    frac=retrace/pm if pm>0 else 0.0
    if retrace<MIN_RETRACE_BPS or frac<MIN_RETRACE_FRAC:
        return None
    return {
        "signal_ts_ms":int(end_times[i]),"mark_price":mark,
        "retrace_bps":retrace,"retrace_fraction_pre_180":frac,
    }


def replay(compact:Path,labels_gz:Path)->dict[str,Any]:
    bars=read_jsonl_gz(compact)
    starts={int(b["start_ms"]):i for i,b in enumerate(bars)}
    end_times=[int(b["bar_end_ms"]) for b in bars]
    closes=[float(b["close"]) for b in bars]

    candidates=[]
    for e in generate_candidates(bars):
        if 360 not in e["lookbacks_m"]:continue
        idx=starts[e["bar_start_ms"]]
        pm=pre_move_180_bps(e["side"],float(e["extreme_price"]),idx,bars)
        if pm<=0:continue
        e=dict(e);e["pre_move_180_bps"]=pm;candidates.append(e)

    labels=[
        dict(x) for x in (read_json_gz(labels_gz).get("internal") or [])
        if bool(x.get("reference_finalized"))
    ]
    labels.sort(key=lambda x:int(x["extreme_interval_start_ms"]))

    rows=[]
    for j in range(1,len(labels)-1):
        prev,target,nxt=labels[j-1],labels[j],labels[j+1]
        start=int(prev["extreme_interval_start_ms"])
        target_end=int(target["extreme_interval_end_ms"])
        deadline=int(nxt["extreme_interval_start_ms"])
        side=str(target["side"])
        evs=[
            e for e in candidates
            if e["side"]==side and start<int(e["extreme_ts_ms"])<=target_end
        ]
        evs.sort(key=lambda e:(int(e["extreme_ts_ms"]),int(e["signal_ts_ms"])))

        current=None;signals=[]
        for e in evs:
            if current is None:
                current=e;continue
            if not more_extreme(side,float(e["extreme_price"]),float(current["extreme_price"])):
                continue
            sig=checkpoint(current,int(e["extreme_ts_ms"]),bars,end_times,closes)
            if sig:signals.append((int(sig["signal_ts_ms"]),current,sig))
            current=e
        if current is not None:
            sig=checkpoint(current,deadline,bars,end_times,closes)
            if sig:signals.append((int(sig["signal_ts_ms"]),current,sig))

        if not signals:
            rows.append({"episode":j,"side":side,"target_label_id":int(target["label_id"]),"accepted":False})
            continue
        signals.sort(key=lambda z:z[0])
        _,cand,sig=signals[0]
        true=(
            int(target["extreme_interval_start_ms"])
            <=int(cand["extreme_ts_ms"])
            <=int(target["extreme_interval_end_ms"])
        )
        row={
            "episode":j,"side":side,"target_label_id":int(target["label_id"]),
            "accepted":True,"true_first":bool(true),
            "candidate_ts_ms":int(cand["extreme_ts_ms"]),
            "candidate_price":float(cand["extreme_price"]),**sig,
        }
        if true:
            tp=float(target["extreme_price"]);np=float(nxt["extreme_price"]);mark=float(sig["mark_price"])
            full=abs(np/tp-1.0)*100.0
            entry=abs(mark/tp-1.0)*100.0
            if side=="LOW" and np>tp:
                remaining=max(0.0,np-mark)/max(1e-12,np-tp)
            elif side=="HIGH" and tp>np:
                remaining=max(0.0,mark-np)/max(1e-12,tp-np)
            else:remaining=0.0
            row.update({"entry_distance_pct":entry,"remaining_swing_fraction":remaining,"full_swing_pct":full})
        rows.append(row)

    def summarize(rr:list[dict[str,Any]])->dict[str,Any]:
        acc=[x for x in rr if x.get("accepted")]
        tp=sum(bool(x.get("true_first")) for x in acc);fp=len(acc)-tp
        return {
            "episodes":len(rr),"accepted_first":len(acc),"true_first":tp,"false_first":fp,
            "no_signal":len(rr)-len(acc),
            "precision":tp/len(acc) if acc else 0.0,
            "recall":tp/len(rr) if rr else 0.0,
        }

    overall=summarize(rows)
    by_side={s:summarize([x for x in rows if x["side"]==s]) for s in ("LOW","HIGH")}
    blocks=[]
    for i in range(0,len(rows),30):
        m=summarize(rows[i:i+30]);m["episodes_range"]=f"{i+1}-{min(i+30,len(rows))}";blocks.append(m)
    true_rows=[x for x in rows if x.get("accepted") and x.get("true_first")]
    tradeoff={
        "true_actionable_signals":len(true_rows),
        "median_entry_distance_from_local_extreme_pct":statistics.median(x["entry_distance_pct"] for x in true_rows),
        "median_remaining_swing_fraction":statistics.median(x["remaining_swing_fraction"] for x in true_rows),
        "median_full_swing_pct":statistics.median(x["full_swing_pct"] for x in true_rows),
    }
    rem=sorted(x["remaining_swing_fraction"] for x in true_rows)
    if rem:
        def q(p:float)->float:
            pos=(len(rem)-1)*p;lo=int(pos);hi=min(lo+1,len(rem)-1);w=pos-lo
            return rem[lo]*(1-w)+rem[hi]*w
        tradeoff["remaining_swing_fraction_iqr"]=[q(.25),q(.75)]

    return {
        "version":"HYPE-HARD120-EXACT-REPLAY-v1",
        "contract":"INTERNAL_HARD120_CHECKPOINT_V2",
        "research_only":True,"real_orders":False,
        "candidate_generation":{"events_total":len(generate_candidates(bars)),"hard_6h_candidates":len(candidates)},
        "evaluation":overall,"by_side":by_side,"chronological_blocks":blocks,
        "tradeoff":tradeoff,"episode_rows":rows,
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--compact-1m",type=Path,required=True)
    ap.add_argument("--labels-gz",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--assert-reference",action="store_true")
    args=ap.parse_args()
    out=replay(args.compact_1m,args.labels_gz)
    if args.assert_reference:
        m=out["evaluation"]
        assert m["episodes"]==120,m
        assert m["true_first"]==53,m
        assert m["false_first"]==4,m
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("HARD120_REPLAY="+json.dumps({
        "evaluation":out["evaluation"],"by_side":out["by_side"],
        "blocks":out["chronological_blocks"],"tradeoff":out["tradeoff"],
    },separators=(",",":"),ensure_ascii=False))


if __name__=="__main__":
    main()
