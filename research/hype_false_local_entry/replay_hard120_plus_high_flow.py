#!/usr/bin/env python3
"""Reproducible HARD120 + HIGH seller-flow shadow replay.

Primary HARD120 is frozen. The challenger can add HIGH only when:
- the candidate is a 6h trailing extreme that survives to the exact +120m checkpoint;
- retrace >= 40 bps;
- retrace_fraction_pre_180 is in [0.35, 0.45), so primary did not fire;
- executed-trade flow over the first 15 complete M1 bars after the candidate
  is <= -0.05 with at least 100 trades.

Historical compact flow is the exact minute-aggregate analogue of the live raw
trade window. This is cross-period research, not untouched forward evidence.
"""
from __future__ import annotations

import argparse, json
from pathlib import Path
from typing import Any

from research.hype_false_local_entry.hard_survival_gate import (
    HardCandidate, checkpoint_sample, gate_metrics, MIN_RETRACE_BPS,
)
from research.hype_false_local_entry.high_flow_shadow import (
    MIN_FRACTION, PRIMARY_FRACTION, MAX_FLOW_IMBALANCE, MIN_TRADE_COUNT,
)
from research.hype_false_local_entry.replay_hard120_30d import (
    read_jsonl_gz, read_json_gz, generate_candidates, pre_move_180_bps, more_extreme,
)
from research.hype_local_v5.labels import structural_labels


def raw_checkpoint(candidate:dict[str,Any], end_ms:int, bars:list[dict[str,Any]])->dict[str,Any]|None:
    hc=HardCandidate(
        side=str(candidate["side"]),
        extreme_price=float(candidate["extreme_price"]),
        extreme_ts_ms=int(candidate["extreme_ts_ms"]),
        candidate_id="replay",
        pre_move_180_bps=float(candidate["pre_move_180_bps"]),
        origin_windows=["6h"],
    )
    sample=checkpoint_sample(hc,bars,observed_ms=int(end_ms)-1)
    if sample is None:
        return None
    m=gate_metrics(hc,now_ms=int(sample["sample_ts_ms"]),mark_price=float(sample["mark_price"]))
    return {
        "signal_ts_ms":int(sample["sample_ts_ms"]),
        "mark_price":float(sample["mark_price"]),
        "retrace_bps":float(m["retrace_bps"]),
        "retrace_fraction_pre_180":float(m["retrace_fraction_pre_180"]),
    }


def flow15(candidate:dict[str,Any], bars:list[dict[str,Any]], index_by_start:dict[int,int])->dict[str,Any]|None:
    idx=index_by_start.get(int(candidate["bar_start_ms"]))
    if idx is None:
        return None
    rows=bars[idx+1:idx+16]
    if len(rows)!=15:
        return None
    expected=int(bars[idx]["bar_end_ms"])
    for r in rows:
        if int(r["start_ms"])!=expected or bool(r.get("gap",False)):
            return None
        expected=int(r["bar_end_ms"])
    buy=sum(float(r.get("buy_notional") or 0.0) for r in rows)
    sell=sum(float(r.get("sell_notional") or 0.0) for r in rows)
    count=sum(int(r.get("trade_count") or 0) for r in rows)
    den=buy+sell
    if count<MIN_TRADE_COUNT or den<=0:
        return None
    return {"flow_15":(buy-sell)/den,"trade_count":count}


def decision(candidate:dict[str,Any], cp:dict[str,Any], bars:list[dict[str,Any]],
             index_by_start:dict[int,int])->tuple[str|None,dict[str,Any]|None]:
    retr=float(cp["retrace_bps"]); frac=float(cp["retrace_fraction_pre_180"])
    if retr>=MIN_RETRACE_BPS and frac>=PRIMARY_FRACTION:
        return "PRIMARY",None
    if str(candidate["side"])!="HIGH" or retr<MIN_RETRACE_BPS or not (MIN_FRACTION<=frac<PRIMARY_FRACTION):
        return None,None
    f=flow15(candidate,bars,index_by_start)
    if f is None or float(f["flow_15"])>MAX_FLOW_IMBALANCE:
        return None,f
    return "HIGH_FLOW_SHADOW",f


def replay(compact:Path, labels_gz:Path, derive_internal:bool=False)->dict[str,Any]:
    bars=read_jsonl_gz(compact)
    starts={int(b["start_ms"]):i for i,b in enumerate(bars)}
    candidates=[]
    for e in generate_candidates(bars):
        if 360 not in e["lookbacks_m"]:
            continue
        idx=starts[e["bar_start_ms"]]
        pm=pre_move_180_bps(e["side"],float(e["extreme_price"]),idx,bars)
        if pm<=0:
            continue
        z=dict(e);z["pre_move_180_bps"]=pm;candidates.append(z)

    doc=read_json_gz(labels_gz)
    internal=doc.get("internal") or []
    source="artifact_internal"
    if not internal and derive_internal:
        internal,_=structural_labels(bars,lookback=3,lookahead=1)
        source="derived_from_compact_m1_L3_K1"
    labels=sorted((dict(x) for x in internal if bool(x.get("reference_finalized"))),
                  key=lambda x:int(x["extreme_interval_start_ms"]))

    rows=[]
    for j in range(1,len(labels)-1):
        prev,target,nxt=labels[j-1],labels[j],labels[j+1]
        start=int(prev["extreme_interval_start_ms"])
        target_end=int(target["extreme_interval_end_ms"])
        deadline=int(nxt["extreme_interval_start_ms"])
        side=str(target["side"])
        evs=sorted((e for e in candidates if e["side"]==side and start<int(e["extreme_ts_ms"])<=target_end),
                   key=lambda e:(int(e["extreme_ts_ms"]),int(e["signal_ts_ms"])))
        current=None;signals=[]
        for e in evs:
            if current is None:
                current=e;continue
            if not more_extreme(side,float(e["extreme_price"]),float(current["extreme_price"])):
                continue
            cp=raw_checkpoint(current,int(e["extreme_ts_ms"]),bars)
            if cp:
                kind,flow=decision(current,cp,bars,starts)
                if kind:signals.append((int(cp["signal_ts_ms"]),current,cp,kind,flow))
            current=e
        if current is not None:
            cp=raw_checkpoint(current,deadline,bars)
            if cp:
                kind,flow=decision(current,cp,bars,starts)
                if kind:signals.append((int(cp["signal_ts_ms"]),current,cp,kind,flow))

        if not signals:
            rows.append({"episode":j,"side":side,"accepted":False});continue
        signals.sort(key=lambda z:z[0])
        _,cand,cp,kind,flow=signals[0]
        true=(int(target["extreme_interval_start_ms"])<=int(cand["extreme_ts_ms"])<=int(target["extreme_interval_end_ms"]))
        rows.append({
            "episode":j,"side":side,"accepted":True,"true_first":bool(true),
            "kind":kind,"candidate_ts_ms":int(cand["extreme_ts_ms"]),
            "signal_ts_ms":int(cp["signal_ts_ms"]),
            "retrace_bps":float(cp["retrace_bps"]),
            "retrace_fraction_pre_180":float(cp["retrace_fraction_pre_180"]),
            "flow_15":None if flow is None else float(flow["flow_15"]),
            "flow_trade_count":None if flow is None else int(flow["trade_count"]),
        })

    def summarize(rr):
        acc=[x for x in rr if x.get("accepted")]
        tp=sum(bool(x.get("true_first")) for x in acc);fp=len(acc)-tp
        sh=[x for x in acc if x.get("kind")=="HIGH_FLOW_SHADOW"]
        return {
            "episodes":len(rr),"accepted_first":len(acc),"true_first":tp,"false_first":fp,
            "precision":tp/len(acc) if acc else 0.0,
            "recall":tp/len(rr) if rr else 0.0,
            "shadow_signals":len(sh),
            "shadow_true":sum(bool(x.get("true_first")) for x in sh),
            "shadow_false":sum(not bool(x.get("true_first")) for x in sh),
        }

    return {
        "version":"HARD120_PLUS_HIGH_FLOW_CROSS_PERIOD_V1",
        "research_only":True,"real_orders":False,
        "label_source":source,"internal_labels_finalized":len(labels),
        "contract":{
            "primary":"INTERNAL_HARD120_CHECKPOINT_V2",
            "shadow":"HARD120_HIGH_FLOW_SHADOW_V1",
            "primary_unchanged":True,
            "shadow_core_flip_authorized":False,
        },
        "evaluation":summarize(rows),
        "by_side":{s:summarize([x for x in rows if x["side"]==s]) for s in ("LOW","HIGH")},
        "episode_rows":rows,
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--compact-1m",type=Path,required=True)
    ap.add_argument("--labels-gz",type=Path,required=True)
    ap.add_argument("--derive-internal",action="store_true")
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    out=replay(args.compact_1m,args.labels_gz,args.derive_internal)
    args.output.write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("HARD120_PLUS_HIGH_FLOW="+json.dumps({
        "evaluation":out["evaluation"],"by_side":out["by_side"],
        "labels":out["internal_labels_finalized"],"label_source":out["label_source"],
    },separators=(",",":"),ensure_ascii=False))


if __name__=="__main__":
    main()
