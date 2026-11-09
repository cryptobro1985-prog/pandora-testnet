#!/usr/bin/env python3
"""Replay frozen HARD120 HIGH + Flow V2 gated by V3.

Research/PAPER only. LOW is not evaluated or changed. Labels are scoring-only.
"""
from __future__ import annotations
import argparse,json,statistics
from pathlib import Path
from typing import Any

from research.hype_false_local_entry.replay_hard120_30d import (
    read_jsonl_gz,read_json_gz,generate_candidates,pre_move_180_bps,more_extreme,
)
from research.hype_false_local_entry.replay_hard120_plus_high_flow import raw_checkpoint,flow15
from research.hype_false_local_entry.high_flow_shadow_v2 import qualifies as v2_qualifies
from research.hype_false_local_entry.high_flow_regime_gate_v3 import metrics as v3_metrics,contract as v3_contract
from research.hype_local_v5.labels import structural_labels


def replay(compact:Path,labels_gz:Path,derive_internal:bool=False)->dict[str,Any]:
    bars=read_jsonl_gz(compact)
    starts={int(b["start_ms"]):i for i,b in enumerate(bars)}
    candidates=[]
    for e in generate_candidates(bars):
        if str(e["side"])!="HIGH" or 360 not in e["lookbacks_m"]:continue
        idx=starts[e["bar_start_ms"]]
        pm=pre_move_180_bps("HIGH",float(e["extreme_price"]),idx,bars)
        if pm<=0:continue
        z=dict(e);z["pre_move_180_bps"]=pm;candidates.append(z)

    doc=read_json_gz(labels_gz);internal=doc.get("internal") or [];source="artifact_internal"
    if not internal and derive_internal:
        internal,_=structural_labels(bars,lookback=3,lookahead=1)
        source="derived_from_compact_m1_L3_K1"
    labels=sorted((dict(x) for x in internal if bool(x.get("reference_finalized"))),
                  key=lambda x:int(x["extreme_interval_start_ms"]))

    rows=[]
    for j in range(1,len(labels)-1):
        prev,target,nxt=labels[j-1],labels[j],labels[j+1]
        if str(target["side"])!="HIGH":continue
        start=int(prev["extreme_interval_start_ms"])
        target_end=int(target["extreme_interval_end_ms"])
        deadline=int(nxt["extreme_interval_start_ms"])
        evs=sorted((e for e in candidates if start<int(e["extreme_ts_ms"])<=target_end),
                   key=lambda e:(int(e["extreme_ts_ms"]),int(e["signal_ts_ms"])))
        current=None;signals=[]

        def evaluate(cand,end_ms):
            if cand is None:return
            cp=raw_checkpoint(cand,end_ms,bars)
            if cp is None:return
            retr=float(cp["retrace_bps"]);frac=float(cp["retrace_fraction_pre_180"])
            if retr>=40.0 and frac>=0.45:
                signals.append((int(cp["signal_ts_ms"]),cand,cp,"HARD120",None))
                return
            f=flow15(cand,bars,starts)
            if f is None:return
            v2_ok,v2=v2_qualifies(
                side="HIGH",primary_emitted=False,expected_side_ok=True,checkpoint_fresh=True,
                retrace_bps=retr,retrace_fraction_pre_180=frac,
                flow_15=float(f["flow_15"]),trade_count=int(f["trade_count"]),
            )
            if not v2_ok:return
            v3=v3_metrics(
                side="HIGH",candidate_bar_start_ms=int(cand["bar_start_ms"]),
                extreme_price=float(cand["extreme_price"]),
                sample_ts_ms=int(cp["signal_ts_ms"]),completed_m1_rows=bars,
            )
            if bool(v3.get("ready")):
                signals.append((int(cp["signal_ts_ms"]),cand,cp,"HIGH_FLOW_V3",
                                {"v2":v2,"v3":v3,"flow_15":float(f["flow_15"])}))

        for e in evs:
            if current is None:
                current=e;continue
            if not more_extreme("HIGH",float(e["extreme_price"]),float(current["extreme_price"])):
                continue
            evaluate(current,int(e["extreme_ts_ms"]))
            current=e
        evaluate(current,deadline)

        if not signals:
            rows.append({"episode":j,"accepted":False});continue
        signals.sort(key=lambda z:z[0])
        _,cand,cp,kind,detail=signals[0]
        true=(int(target["extreme_interval_start_ms"])<=int(cand["extreme_ts_ms"])<=int(target["extreme_interval_end_ms"]))
        row={
            "episode":j,"accepted":True,"true_first":bool(true),"kind":kind,
            "candidate_ts_ms":int(cand["extreme_ts_ms"]),"candidate_price":float(cand["extreme_price"]),
            "signal_ts_ms":int(cp["signal_ts_ms"]),"mark_price":float(cp["mark_price"]),
            "retrace_bps":float(cp["retrace_bps"]),
            "retrace_fraction_pre_180":float(cp["retrace_fraction_pre_180"]),
            "detail":detail,
        }
        if true:
            tp=float(target["extreme_price"]);mark=float(cp["mark_price"])
            row["entry_distance_pct"]=abs(mark/tp-1.0)*100.0
        rows.append(row)

    acc=[x for x in rows if x.get("accepted")]
    tp=sum(bool(x.get("true_first")) for x in acc);fp=len(acc)-tp
    tr=[x for x in acc if x.get("true_first")]
    v3=[x for x in acc if x.get("kind")=="HIGH_FLOW_V3"]
    return {
        "version":"HARD120_HIGH_FLOW_V3_FOUR_REGIME_REPLAY_V1",
        "research_only":True,"real_orders":False,"low_logic_changed":False,
        "label_source":source,
        "contracts":{"primary":"INTERNAL_HARD120_CHECKPOINT_V2",
                     "v2":"HARD120_HIGH_FLOW_SHADOW_V2","v3":v3_contract()},
        "evaluation":{
            "episodes":len(rows),"accepted_first":len(acc),"true_first":tp,"false_first":fp,
            "precision":tp/len(acc) if acc else 0.0,
            "recall":tp/len(rows) if rows else 0.0,
            "median_entry_distance_pct":statistics.median(x["entry_distance_pct"] for x in tr) if tr else None,
            "v3_signals":len(v3),
            "v3_true":sum(bool(x.get("true_first")) for x in v3),
            "v3_false":sum(not bool(x.get("true_first")) for x in v3),
        },
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
    print("HIGH_V3="+json.dumps(out["evaluation"],separators=(",",":")))
if __name__=="__main__":main()
