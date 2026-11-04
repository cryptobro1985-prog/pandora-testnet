#!/usr/bin/env python3
"""Causally bootstrap HYPE Quant from HYPE110-COMPACT-v1 packages."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from research.hype_local_v5.decode_compact import decode_table
from research.hype_quant.features import FeatureState
from research.hype_quant.learner import OnlineQuantLearner, load_config


def stream_meta(chunk:dict,name:str):
    for s in chunk.get("streams",[]):
        if s.get("name")==name:return s
    return None


def load_package(root:Path):
    manifest=json.loads((root/"PACK_MANIFEST.json").read_text(encoding="utf-8"))
    micro=[];context=[]
    for c in manifest.get("chunks",[]):
        cd=root/"chunks"/c["chunk"]
        if stream_meta(c,"microstructure_1s.mpk.xz") and (cd/"microstructure_1s.mpk.xz").exists():
            micro.extend(decode_table(cd/"microstructure_1s.mpk.xz") or [])
        if stream_meta(c,"structural_context_1m.mpk.xz") and (cd/"structural_context_1m.mpk.xz").exists():
            context.extend(decode_table(cd/"structural_context_1m.mpk.xz") or [])
    return micro,context


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
    all_micro=[];all_context=[]
    for pkg in args.package:
        try:
            m,c=load_package(pkg);all_micro.extend(m);all_context.extend(c)
        except Exception as exc:
            print(f"[bootstrap] skip {pkg}: {exc}",flush=True)
    all_micro.sort(key=lambda r:int(r.get("ts_ms") or 0))
    all_context.sort(key=lambda r:int(r.get("ts_ms") or 0))
    ci=0;last_ts=None;sample_ms=int(q.config.get("state_sample_seconds",5)*1000);next_sample=0
    seen=set();used=0
    for row in all_micro:
        ts=int(row.get("ts_ms") or 0)
        if ts<=0 or ts in seen:continue
        seen.add(ts)
        while ci<len(all_context) and int(all_context[ci].get("ts_ms") or 0)<=ts:
            state.update_context(all_context[ci]);ci+=1
        if last_ts is not None and ts-last_ts>10_000:
            q.pending.clear();state.prices.clear()
        last_ts=ts
        try:price,x=state.update_micro(row)
        except Exception:continue
        if ts<next_sample:continue
        next_sample=ts+sample_ms
        q.observe(ts,price,x);used+=1
    q.save(cp)
    report=q.report()
    report.update({"bootstrap_packages":[str(p) for p in args.package],
                   "bootstrap_states_used":used,
                   "bootstrap_last_ts_ms":last_ts,
                   "note":"historical progressive replay; not final forward evidence"})
    (args.checkpoint_dir/"BOOTSTRAP_REPORT.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report),flush=True)


if __name__=="__main__":
    main()
