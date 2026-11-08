#!/usr/bin/env python3
"""EARLY60 + HARD120 + HIGH-flow with HIGH60 primary-confirmation veto.

The old full-stack replay is untouched. This challenger mirrors LOW primary
unchanged and mirrors HIGH primary only if +60m retrace >= 50 bps.
No orders. Labels are evaluation-only after causal signal construction.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
from typing import Any

from research.hype_false_local_entry.replay_hard120_30d import (
    read_jsonl_gz,read_json_gz,generate_candidates,pre_move_180_bps,more_extreme,
)
from research.hype_false_local_entry.replay_hard120_plus_high_flow import (
    raw_checkpoint as hard_checkpoint,decision as hard_or_high_flow_decision,
)
from research.hype_false_local_entry.replay_early60_plus_hard_stack import early_checkpoint
from research.hype_false_local_entry.high60_retrace_veto import (
    sample_retrace60,high_primary_confirmed,contract as veto_contract,
)
from research.hype_local_v5.labels import structural_labels


def replay(compact:Path,labels_gz:Path,derive_internal:bool=False)->dict[str,Any]:
    bars=read_jsonl_gz(compact)
    starts={int(b["start_ms"]):i for i,b in enumerate(bars)}
    candidates=[]
    for e in generate_candidates(bars):
        if 360 not in e["lookbacks_m"]: continue
        idx=starts[e["bar_start_ms"]]
        pm=pre_move_180_bps(e["side"],float(e["extreme_price"]),idx,bars)
        if pm<=0: continue
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

        def evaluate_lineage(cand,end_ms):
            if cand is None:return
            early=early_checkpoint(cand,end_ms,bars,starts)
            if early is not None:
                signals.append((int(early["signal_ts_ms"]),cand,early,"EARLY60"))
            hard=hard_checkpoint(cand,end_ms,bars)
            if hard is None:return
            kind,flow=hard_or_high_flow_decision(cand,hard,bars,starts)
            if not kind:return
            payload=dict(hard)
            if flow is not None:
                payload["flow_15"]=float(flow["flow_15"])
                payload["flow_trade_count"]=int(flow["trade_count"])
            if kind=="PRIMARY":
                s60=sample_retrace60(side=str(cand["side"]),candidate_ts_ms=int(cand["extreme_ts_ms"]),
                                     extreme_price=float(cand["extreme_price"]),
                                     completed_m1_rows=bars,observed_ms=int(hard["signal_ts_ms"]))
                confirmed,veto=high_primary_confirmed(side=str(cand["side"]),sample=s60)
                payload["high60_veto"]=veto
                if not confirmed:
                    return
                kind="PRIMARY_HIGH60_CONFIRMED" if str(cand["side"])=="HIGH" else "PRIMARY"
            signals.append((int(hard["signal_ts_ms"]),cand,payload,kind))

        for e in evs:
            if current is None:
                current=e;continue
            if not more_extreme(side,float(e["extreme_price"]),float(current["extreme_price"])):
                continue
            evaluate_lineage(current,int(e["extreme_ts_ms"]))
            current=e
        evaluate_lineage(current,deadline)

        if not signals:
            rows.append({"episode":j,"side":side,"accepted":False});continue
        signals.sort(key=lambda z:(z[0],0 if z[3]=="EARLY60" else 1))
        _,cand,sig,kind=signals[0]
        true=int(target["extreme_interval_start_ms"])<=int(cand["extreme_ts_ms"])<=int(target["extreme_interval_end_ms"])
        rows.append({
            "episode":j,"side":side,"accepted":True,"true_first":bool(true),"kind":kind,
            "candidate_ts_ms":int(cand["extreme_ts_ms"]),"signal_ts_ms":int(sig["signal_ts_ms"]),
            "retrace_bps":float(sig["retrace_bps"]),
            "retrace_fraction_pre_180":float(sig["retrace_fraction_pre_180"]),
            "flow_15":sig.get("flow_15"),"reversal_flow_15":sig.get("reversal_flow_15"),
            "high60_veto":sig.get("high60_veto"),
        })

    def summarize(rr):
        acc=[x for x in rr if x.get("accepted")]
        tp=sum(bool(x.get("true_first")) for x in acc);fp=len(acc)-tp
        kinds={}
        for x in acc:kinds[x["kind"]]=kinds.get(x["kind"],0)+1
        return {"episodes":len(rr),"accepted_first":len(acc),"true_first":tp,"false_first":fp,
                "precision":tp/len(acc) if acc else 0.0,"recall":tp/len(rr) if rr else 0.0,
                "kinds":kinds}

    return {
        "version":"HIGH60_VETO_FULL_STACK_REPLAY_V1",
        "research_only":True,"real_orders":False,"label_source":source,
        "internal_labels_finalized":len(labels),
        "contracts":{
            "early60":"EARLY60_STRONG_REVERSAL_SHADOW_V1",
            "primary":"INTERNAL_HARD120_CHECKPOINT_V2",
            "high_flow":"HARD120_HIGH_FLOW_SHADOW_V1",
            "high60_veto":veto_contract(),
            "core_flip_authorized":False,
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
    print("HIGH60_VETO_STACK="+json.dumps({"evaluation":out["evaluation"],"by_side":out["by_side"]},
          separators=(",",":"),ensure_ascii=False))

if __name__=="__main__":main()
