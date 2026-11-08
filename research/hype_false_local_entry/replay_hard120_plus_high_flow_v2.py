#!/usr/bin/env python3
"""HARD120 primary + HIGH-flow V2 expansion replay. Research only."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from typing import Any
from research.hype_false_local_entry.replay_hard120_30d import (
    read_jsonl_gz,read_json_gz,generate_candidates,pre_move_180_bps,more_extreme,
)
from research.hype_false_local_entry.replay_hard120_plus_high_flow import raw_checkpoint,flow15
from research.hype_false_local_entry.high_flow_shadow_v2 import qualifies,contract as v2_contract
from research.hype_local_v5.labels import structural_labels

PRIMARY_FRACTION=0.45
MIN_RETRACE_BPS=40.0

def replay(compact:Path,labels_gz:Path,derive_internal:bool=False)->dict[str,Any]:
    bars=read_jsonl_gz(compact); starts={int(b["start_ms"]):i for i,b in enumerate(bars)}
    candidates=[]
    for e in generate_candidates(bars):
        if 360 not in e["lookbacks_m"]:continue
        idx=starts[e["bar_start_ms"]]
        pm=pre_move_180_bps(e["side"],float(e["extreme_price"]),idx,bars)
        if pm<=0:continue
        z=dict(e);z["pre_move_180_bps"]=pm;candidates.append(z)
    doc=read_json_gz(labels_gz); internal=doc.get("internal") or []; source="artifact_internal"
    if not internal and derive_internal:
        internal,_=structural_labels(bars,lookback=3,lookahead=1);source="derived_from_compact_m1_L3_K1"
    labels=sorted((dict(x) for x in internal if bool(x.get("reference_finalized"))),
                  key=lambda x:int(x["extreme_interval_start_ms"]))
    rows=[]
    for j in range(1,len(labels)-1):
        prev,target,nxt=labels[j-1],labels[j],labels[j+1]
        start=int(prev["extreme_interval_start_ms"]); target_end=int(target["extreme_interval_end_ms"])
        deadline=int(nxt["extreme_interval_start_ms"]); side=str(target["side"])
        evs=sorted((e for e in candidates if e["side"]==side and start<int(e["extreme_ts_ms"])<=target_end),
                   key=lambda e:(int(e["extreme_ts_ms"]),int(e["signal_ts_ms"])))
        current=None;signals=[]
        def evaluate(cand,end_ms):
            if cand is None:return
            cp=raw_checkpoint(cand,end_ms,bars)
            if cp is None:return
            retr=float(cp["retrace_bps"]);frac=float(cp["retrace_fraction_pre_180"])
            if retr>=MIN_RETRACE_BPS and frac>=PRIMARY_FRACTION:
                signals.append((int(cp["signal_ts_ms"]),cand,cp,"PRIMARY",None));return
            if side!="HIGH":return
            f=flow15(cand,bars,starts)
            if f is None:return
            ok,m=qualifies(side=side,primary_emitted=False,expected_side_ok=True,
                           checkpoint_fresh=True,retrace_bps=retr,
                           retrace_fraction_pre_180=frac,flow_15=float(f["flow_15"]),
                           trade_count=int(f["trade_count"]))
            if ok:
                payload=dict(cp);payload["v2"]=m
                signals.append((int(cp["signal_ts_ms"]),cand,payload,"HIGH_FLOW_V2",f))
        for e in evs:
            if current is None:current=e;continue
            if not more_extreme(side,float(e["extreme_price"]),float(current["extreme_price"])):continue
            evaluate(current,int(e["extreme_ts_ms"]));current=e
        evaluate(current,deadline)
        if not signals:
            rows.append({"episode":j,"side":side,"accepted":False});continue
        signals.sort(key=lambda z:z[0]);_,cand,cp,kind,f=signals[0]
        true=int(target["extreme_interval_start_ms"])<=int(cand["extreme_ts_ms"])<=int(target["extreme_interval_end_ms"])
        rows.append({"episode":j,"side":side,"accepted":True,"true_first":bool(true),"kind":kind,
                     "candidate_ts_ms":int(cand["extreme_ts_ms"]),"signal_ts_ms":int(cp["signal_ts_ms"]),
                     "retrace_bps":float(cp["retrace_bps"]),
                     "retrace_fraction_pre_180":float(cp["retrace_fraction_pre_180"]),
                     "flow_15":None if f is None else float(f["flow_15"]),
                     "flow_trade_count":None if f is None else int(f["trade_count"])})
    def summary(rr):
        acc=[x for x in rr if x.get("accepted")];tp=sum(bool(x.get("true_first")) for x in acc);fp=len(acc)-tp
        v=[x for x in acc if x.get("kind")=="HIGH_FLOW_V2"]
        return {"episodes":len(rr),"accepted_first":len(acc),"true_first":tp,"false_first":fp,
                "precision":tp/len(acc) if acc else 0.0,"recall":tp/len(rr) if rr else 0.0,
                "v2_signals":len(v),"v2_true":sum(bool(x.get("true_first")) for x in v),
                "v2_false":sum(not bool(x.get("true_first")) for x in v)}
    return {"version":"HARD120_PLUS_HIGH_FLOW_V2_REPLAY_V1","research_only":True,"real_orders":False,
            "label_source":source,"internal_labels_finalized":len(labels),
            "contracts":{"primary":"INTERNAL_HARD120_CHECKPOINT_V2","high_flow_v2":v2_contract(),
                         "core_flip_authorized":False},
            "evaluation":summary(rows),
            "by_side":{s:summary([x for x in rows if x["side"]==s]) for s in ("LOW","HIGH")},
            "episode_rows":rows}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--compact-1m",type=Path,required=True)
    ap.add_argument("--labels-gz",type=Path,required=True);ap.add_argument("--derive-internal",action="store_true")
    ap.add_argument("--output",type=Path,required=True);args=ap.parse_args()
    out=replay(args.compact_1m,args.labels_gz,args.derive_internal)
    args.output.write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("HIGH_FLOW_V2="+json.dumps({"evaluation":out["evaluation"],"by_side":out["by_side"]},separators=(",",":")))
if __name__=="__main__":main()
