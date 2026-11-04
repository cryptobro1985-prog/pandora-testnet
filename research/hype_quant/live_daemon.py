#!/usr/bin/env python3
"""Tail the existing HYPE collector output and train/evaluate online.

This process never connects to private Bybit endpoints and never places orders.
It consumes exactly the research collector's 1s microstructure and 1m context.
"""
from __future__ import annotations
import argparse
import json
import pickle
import time
from pathlib import Path

from .features import FeatureState
from .learner import OnlineQuantLearner, load_config


def append_jsonl(path:Path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a",encoding="utf-8") as f:
        f.write(json.dumps(obj,separators=(",",":"),ensure_ascii=False)+"\n")


class Tailer:
    def __init__(self):
        self.offsets={}

    def read_new(self,path:Path):
        key=str(path)
        pos=self.offsets.get(key,0)
        try:size=path.stat().st_size
        except FileNotFoundError:return []
        if size<pos:pos=0
        rows=[]
        with path.open("r",encoding="utf-8") as f:
            f.seek(pos)
            while True:
                start=f.tell()
                line=f.readline()
                if not line:break
                if not line.endswith("\n"):
                    f.seek(start);break
                try:rows.append(json.loads(line))
                except Exception:pass
            self.offsets[key]=f.tell()
        return rows


def load_feature_state(path:Path):
    if path.exists():
        try:
            with path.open("rb") as f:return pickle.load(f)
        except Exception:pass
    return FeatureState()


def save_feature_state(state,path:Path):
    tmp=path.with_suffix(".tmp")
    with tmp.open("wb") as f:pickle.dump(state,f,pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--capture-root",type=Path,required=True)
    ap.add_argument("--checkpoint-dir",type=Path,required=True)
    ap.add_argument("--config",type=Path,default=Path("research/hype_quant/config.json"))
    ap.add_argument("--minutes",type=int,required=True)
    ap.add_argument("--poll-seconds",type=float,default=0.5)
    args=ap.parse_args()
    args.checkpoint_dir.mkdir(parents=True,exist_ok=True)
    cfg=load_config(args.config)
    cp=args.checkpoint_dir/"quant_learner.pkl"
    learner=OnlineQuantLearner.load(cp) if cp.exists() else OnlineQuantLearner(cfg)
    fs_path=args.checkpoint_dir/"feature_state.pkl"
    state=load_feature_state(fs_path)
    tail=Tailer()
    actions=args.checkpoint_dir/"quant_actions.jsonl"
    gaps=args.checkpoint_dir/"quant_gaps.jsonl"
    started=time.time();deadline=started+args.minutes*60
    next_save=0.0;next_sample_ms=0;last_seen_ts=state.last_ts_ms
    sample_ms=int(cfg.get("state_sample_seconds",5)*1000)
    processed=0;sampled=0

    while time.time()<deadline:
        # Context first, so each micro snapshot sees newest causally available context.
        for path in sorted(args.capture_root.rglob("HYPE_structural_context_1m.jsonl")):
            for row in tail.read_new(path):
                state.update_context(row)

        new_rows=[]
        for path in sorted(args.capture_root.rglob("HYPE_live_microstructure_1s.jsonl")):
            for row in tail.read_new(path):
                if isinstance(row,dict) and row.get("ts_ms"):
                    new_rows.append(row)
        new_rows.sort(key=lambda r:int(r.get("ts_ms") or 0))

        for row in new_rows:
            ts=int(row["ts_ms"])
            if last_seen_ts is not None and ts<=last_seen_ts:
                continue
            if last_seen_ts is not None:
                gap=(ts-last_seen_ts)/1000.0
                if gap>10:
                    append_jsonl(gaps,{"from_ts_ms":last_seen_ts,"to_ts_ms":ts,"gap_seconds":gap,
                                       "action":"drop_pending_to_avoid_false_path_labels"})
                    learner.pending.clear()
                    state.prices.clear()
            last_seen_ts=ts
            try:price,x=state.update_micro(row)
            except Exception:continue
            processed+=1
            if ts<next_sample_ms:
                continue
            next_sample_ms=ts+sample_ms
            decision=learner.observe(ts,price,x)
            sampled+=1
            append_jsonl(actions,{"ts_ms":ts,"price":price,"decision":decision})

        now=time.time()
        if now>=next_save:
            learner.save(cp);save_feature_state(state,fs_path)
            report=learner.report()
            report.update({
                "processed_micro_rows":processed,
                "sampled_states":sampled,
                "capture_root":str(args.capture_root),
                "checkpoint_dir":str(args.checkpoint_dir),
                "last_seen_ts_ms":last_seen_ts,
                "started_ts_ms":int(started*1000),
                "updated_ts_ms":int(now*1000),
                "research_only":True,
                "real_orders":False
            })
            (args.checkpoint_dir/"QUANT_REPORT.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
            next_save=now+60
        if not new_rows:
            time.sleep(args.poll_seconds)

    learner.save(cp);save_feature_state(state,fs_path)
    report=learner.report()
    report.update({"processed_micro_rows":processed,"sampled_states":sampled,
                   "last_seen_ts_ms":last_seen_ts,"completed_ts_ms":int(time.time()*1000),
                   "research_only":True,"real_orders":False})
    (args.checkpoint_dir/"QUANT_REPORT.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report),flush=True)


if __name__=="__main__":
    main()
