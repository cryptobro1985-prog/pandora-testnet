#!/usr/bin/env python3
"""Causally bootstrap HYPE Quant from all HYPE110-COMPACT-v1 streams."""
from __future__ import annotations
import argparse
import heapq
import json
from pathlib import Path

from research.hype_local_v5.decode_compact import decode_events, decode_table
from research.hype_quant.features import FeatureState
from research.hype_quant.learner import OnlineQuantLearner, load_config


def find_meta(chunk:dict,name:str):
    for s in chunk.get("streams",[]):
        if s.get("name")==name:return s
    return None


def ts_of(kind,row):
    if kind=="event":return int(row.get("received_ts_ms") or row.get("ts_ms") or 0)
    return int(row.get("received_ts_ms") or row.get("ts_ms") or 0)


def replay_chunk(root:Path,chunk:dict,state:FeatureState,q:OnlineQuantLearner,last_micro_ts:int|None,next_sample:int):
    cd=root/"chunks"/chunk["chunk"]
    specs=[]
    em=find_meta(chunk,"events.mpk.xz")
    if em and (cd/"events.mpk.xz").exists():
        specs.append(("event",0,iter(decode_events(cd/"events.mpk.xz",em))))
    for name,kind,priority in (
        ("market_context_1m.mpk.xz","market",1),
        ("structural_context_1m.mpk.xz","struct",2),
        ("microstructure_1s.mpk.xz","micro",3),
    ):
        if find_meta(chunk,name) and (cd/name).exists():
            specs.append((kind,priority,iter(decode_table(cd/name) or [])))

    heap=[];counter=0
    for kind,priority,it in specs:
        try:r=next(it)
        except StopIteration:continue
        heapq.heappush(heap,(ts_of(kind,r),priority,counter,kind,r,it));counter+=1

    used=0;events_used=market_used=struct_used=0
    sample_ms=int(q.config.get("state_sample_seconds",5)*1000)
    while heap:
        ts,priority,_,kind,row,it=heapq.heappop(heap)
        if ts>0:
            if kind=="event":
                state.update_event(row);events_used+=1
            elif kind=="market":
                state.update_market_context(row);market_used+=1
            elif kind=="struct":
                state.update_structural_context(row);struct_used+=1
            else:
                if last_micro_ts is None or ts>last_micro_ts:
                    if last_micro_ts is not None and ts-last_micro_ts>10_000:
                        q.pending.clear();state.prices.clear()
                    last_micro_ts=ts
                    try:price,x=state.update_micro(row)
                    except Exception:
                        x=None
                    if x is not None and ts>=next_sample:
                        next_sample=ts+sample_ms
                        q.observe(ts,price,x);used+=1
        try:nxt=next(it)
        except StopIteration:nxt=None
        if nxt is not None:
            heapq.heappush(heap,(ts_of(kind,nxt),priority,counter,kind,nxt,it));counter+=1
    return last_micro_ts,next_sample,used,events_used,market_used,struct_used


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--package",type=Path,action="append",required=True)
    ap.add_argument("--checkpoint-dir",type=Path,required=True)
    ap.add_argument("--config",type=Path,default=Path("research/hype_quant/config.json"))
    args=ap.parse_args()
    args.checkpoint_dir.mkdir(parents=True,exist_ok=True)
    cp=args.checkpoint_dir/"quant_learner.pkl"
    q=OnlineQuantLearner.load(cp) if cp.exists() else OnlineQuantLearner(load_config(args.config))
    state=FeatureState()
    last_ts=None;next_sample=0
    used=events_used=market_used=struct_used=0
    packages_ok=[]

    for pkg in args.package:
        try:
            manifest=json.loads((pkg/"PACK_MANIFEST.json").read_text(encoding="utf-8"))
            for chunk in manifest.get("chunks",[]):
                last_ts,next_sample,a,b,c,d=replay_chunk(pkg,chunk,state,q,last_ts,next_sample)
                used+=a;events_used+=b;market_used+=c;struct_used+=d
            packages_ok.append(str(pkg))
        except Exception as exc:
            print(f"[bootstrap] skip {pkg}: {exc}",flush=True)

    q.save(cp)
    coverage=state.coverage_report()
    (args.checkpoint_dir/"FEATURE_COVERAGE_116_BOOTSTRAP.json").write_text(
        json.dumps(coverage,indent=2)+"\n",encoding="utf-8")
    report=q.report()
    report.update({
        "bootstrap_packages":packages_ok,
        "bootstrap_states_used":used,
        "bootstrap_events_consumed":events_used,
        "bootstrap_market_context_rows":market_used,
        "bootstrap_structural_rows":struct_used,
        "bootstrap_last_ts_ms":last_ts,
        "feature_contract":coverage,
        "note":"progressive replay of all compact streams; discovery/bootstrap only, not final forward evidence"
    })
    (args.checkpoint_dir/"BOOTSTRAP_REPORT.json").write_text(
        json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report),flush=True)


if __name__=="__main__":
    main()
