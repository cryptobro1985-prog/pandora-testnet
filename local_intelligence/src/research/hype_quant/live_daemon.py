#!/usr/bin/env python3
"""Tail every HYPE110+ live source and train/evaluate online.

Research only. No private Bybit endpoints and no order placement.
"""
from __future__ import annotations
import argparse
import json
import pickle
import time
from pathlib import Path

from .features import FeatureState
from .learner import OnlineQuantLearner, load_config
from .agents import augment_with_agents


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
                try:
                    row=json.loads(line)
                    if isinstance(row,dict):
                        row["_source_path"]=key
                        rows.append(row)
                except Exception:
                    pass
            self.offsets[key]=f.tell()
        return rows


def load_feature_state(path:Path):
    if path.exists():
        try:
            with path.open("rb") as f:return pickle.load(f)
        except Exception:
            pass
    return FeatureState()


def save_feature_state(state,path:Path):
    tmp=path.with_suffix(".tmp")
    with tmp.open("wb") as f:pickle.dump(state,f,pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


def event_ts(kind,row):
    if kind=="raw":
        return int(row.get("received_ts_ms") or 0)
    return int(row.get("received_ts_ms") or row.get("ts_ms") or 0)


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
    actions.touch(exist_ok=True);gaps.touch(exist_ok=True)

    started=time.time();deadline=started+args.minutes*60
    next_save=0.0;next_sample_ms=0;last_seen_ts=state.last_ts_ms
    sample_ms=int(cfg.get("state_sample_seconds",5)*1000)
    processed_micro=sampled=raw_frames=market_rows=struct_rows=0

    while time.time()<deadline:
        events=[]
        # Priority on identical receipt timestamps: raw exchange frame -> market
        # context -> structural context -> 1s snapshot/prediction.
        for path in sorted(args.capture_root.rglob("HYPE_live_raw_frames.jsonl")):
            for row in tail.read_new(path):
                events.append((event_ts("raw",row),0,"raw",row))
        for path in sorted(args.capture_root.rglob("HYPE_market_context.jsonl")):
            for row in tail.read_new(path):
                events.append((event_ts("market",row),1,"market",row))
        for path in sorted(args.capture_root.rglob("HYPE_structural_context_1m.jsonl")):
            for row in tail.read_new(path):
                events.append((event_ts("struct",row),2,"struct",row))
        for path in sorted(args.capture_root.rglob("HYPE_live_microstructure_1s.jsonl")):
            for row in tail.read_new(path):
                events.append((event_ts("micro",row),3,"micro",row))
        events.sort(key=lambda z:(z[0],z[1]))

        for ts,_,kind,row in events:
            if ts<=0:continue
            if kind=="raw":
                state.update_raw_frame(row);raw_frames+=1
                continue
            if kind=="market":
                state.update_market_context(row);market_rows+=1
                continue
            if kind=="struct":
                state.update_structural_context(row);struct_rows+=1
                continue

            # micro is the prediction clock
            if last_seen_ts is not None and ts<=last_seen_ts:
                continue
            if last_seen_ts is not None:
                gap=(ts-last_seen_ts)/1000.0
                if gap>10:
                    append_jsonl(gaps,{"from_ts_ms":last_seen_ts,"to_ts_ms":ts,
                                      "gap_seconds":gap,
                                      "action":"drop_pending_to_avoid_false_path_labels"})
                    learner.pending.clear()
                    state.prices.clear()
            last_seen_ts=ts
            try:
                price,x=state.update_micro(row)
                x=augment_with_agents(x)
            except Exception as exc:
                append_jsonl(gaps,{"ts_ms":ts,"feature_error":repr(exc)})
                continue
            processed_micro+=1
            if ts<next_sample_ms:
                continue
            next_sample_ms=ts+sample_ms
            decision=learner.observe(ts,price,x)
            sampled+=1
            append_jsonl(actions,{"ts_ms":ts,"price":price,
                                  "feature_count":len(x),"decision":decision})

        now=time.time()
        if now>=next_save:
            learner.save(cp);save_feature_state(state,fs_path)
            coverage=state.coverage_report()
            (args.checkpoint_dir/"FEATURE_COVERAGE_116.json").write_text(
                json.dumps(coverage,indent=2)+"\n",encoding="utf-8")
            report=learner.report()
            report.update({
                "processed_micro_rows":processed_micro,
                "sampled_states":sampled,
                "raw_frames_consumed":raw_frames,
                "market_context_rows_consumed":market_rows,
                "structural_context_rows_consumed":struct_rows,
                "capture_root":str(args.capture_root),
                "checkpoint_dir":str(args.checkpoint_dir),
                "last_seen_ts_ms":last_seen_ts,
                "feature_contract":coverage,
                "started_ts_ms":int(started*1000),
                "updated_ts_ms":int(now*1000),
                "research_only":True,
                "real_orders":False
            })
            (args.checkpoint_dir/"QUANT_REPORT.json").write_text(
                json.dumps(report,indent=2)+"\n",encoding="utf-8")
            next_save=now+60
        if not events:
            time.sleep(args.poll_seconds)

    learner.save(cp);save_feature_state(state,fs_path)
    coverage=state.coverage_report()
    (args.checkpoint_dir/"FEATURE_COVERAGE_116.json").write_text(
        json.dumps(coverage,indent=2)+"\n",encoding="utf-8")
    report=learner.report()
    report.update({"processed_micro_rows":processed_micro,"sampled_states":sampled,
                   "raw_frames_consumed":raw_frames,
                   "market_context_rows_consumed":market_rows,
                   "structural_context_rows_consumed":struct_rows,
                   "last_seen_ts_ms":last_seen_ts,"completed_ts_ms":int(time.time()*1000),
                   "feature_contract":coverage,
                   "research_only":True,"real_orders":False})
    (args.checkpoint_dir/"QUANT_REPORT.json").write_text(
        json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report),flush=True)


if __name__=="__main__":
    main()
