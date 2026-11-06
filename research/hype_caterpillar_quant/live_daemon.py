#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,pickle,time
from pathlib import Path

from research.hype_quant.features import FeatureState
from research.hype_quant.agents import augment_with_agents
from research.hype_quant.live_daemon import Tailer,event_ts,append_jsonl
from .learner import CaterpillarQuantLearner,new_from_config

def load_state(path):
    if path.exists():
        try:
            with path.open("rb") as f:return pickle.load(f)
        except Exception:pass
    return FeatureState()

def save_state(state,path):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(".tmp")
    with tmp.open("wb") as f:pickle.dump(state,f,pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--capture-root",type=Path,required=True)
    ap.add_argument("--checkpoint-dir",type=Path,required=True)
    ap.add_argument("--config",type=Path,default=Path("research/hype_quant/config.json"))
    ap.add_argument("--minutes",type=int,required=True)
    ap.add_argument("--poll-seconds",type=float,default=.5)
    args=ap.parse_args();args.checkpoint_dir.mkdir(parents=True,exist_ok=True)

    cp=args.checkpoint_dir/"caterpillar_quant.pkl"
    learner=CaterpillarQuantLearner.load(cp) if cp.exists() else new_from_config(args.config)
    fs_path=args.checkpoint_dir/"feature_state.pkl"
    state=load_state(fs_path)
    tail=Tailer()
    actions=args.checkpoint_dir/"caterpillar_actions.jsonl"
    gaps=args.checkpoint_dir/"caterpillar_gaps.jsonl"
    actions.touch(exist_ok=True);gaps.touch(exist_ok=True)

    started=time.time();deadline=started+args.minutes*60
    next_save=0.0;next_sample_ms=0
    last_seen_ts=state.last_ts_ms
    sample_ms=5000
    processed_micro=sampled=0

    while time.time()<deadline:
        events=[]
        for path in sorted(args.capture_root.rglob("HYPE_live_raw_frames.jsonl")):
            for row in tail.read_new(path):events.append((event_ts("raw",row),0,"raw",row))
        for path in sorted(args.capture_root.rglob("HYPE_market_context.jsonl")):
            for row in tail.read_new(path):events.append((event_ts("market",row),1,"market",row))
        for path in sorted(args.capture_root.rglob("HYPE_structural_context_1m.jsonl")):
            for row in tail.read_new(path):events.append((event_ts("struct",row),2,"struct",row))
        for path in sorted(args.capture_root.rglob("HYPE_live_microstructure_1s.jsonl")):
            for row in tail.read_new(path):events.append((event_ts("micro",row),3,"micro",row))
        events.sort(key=lambda z:(z[0],z[1]))

        for ts,_,kind,row in events:
            if ts<=0:continue
            if kind=="raw":
                state.update_raw_frame(row);continue
            if kind=="market":
                state.update_market_context(row);continue
            if kind=="struct":
                state.update_structural_context(row);continue

            if last_seen_ts is not None and ts<=last_seen_ts:continue
            if last_seen_ts is not None and (ts-last_seen_ts)/1000.0>10:
                gap=(ts-last_seen_ts)/1000.0
                append_jsonl(gaps,{"from_ts_ms":last_seen_ts,"to_ts_ms":ts,"gap_seconds":gap})
                learner.on_gap(ts,"MICRO_GAP")
                state.prices.clear()
            last_seen_ts=ts
            try:
                price,x=state.update_micro(row)
                x=augment_with_agents(x)
            except Exception as exc:
                append_jsonl(gaps,{"ts_ms":ts,"feature_error":repr(exc)})
                continue
            processed_micro+=1
            if ts<next_sample_ms:continue
            next_sample_ms=ts+sample_ms
            decision=learner.observe(ts,price,x,state)
            sampled+=1
            append_jsonl(actions,{"ts_ms":ts,"price":price,"feature_count":len(x),**decision})

        now=time.time()
        if now>=next_save:
            learner.save(cp);save_state(state,fs_path)
            report=learner.report()
            report.update({
                "processed_micro_rows":processed_micro,"sampled_states":sampled,
                "last_seen_ts_ms":last_seen_ts,"started_ts_ms":int(started*1000),
                "updated_ts_ms":int(now*1000),"feature_contract":state.coverage_report(),
                "research_only":True,"real_orders":False,
            })
            (args.checkpoint_dir/"CATERPILLAR_QUANT_REPORT.json").write_text(json.dumps(report,indent=2)+"\n")
            next_save=now+60
        if not events:time.sleep(args.poll_seconds)

    learner.save(cp);save_state(state,fs_path)
    report=learner.report()
    report.update({"processed_micro_rows":processed_micro,"sampled_states":sampled,
                   "last_seen_ts_ms":last_seen_ts,"completed_ts_ms":int(time.time()*1000),
                   "feature_contract":state.coverage_report(),
                   "research_only":True,"real_orders":False})
    (args.checkpoint_dir/"CATERPILLAR_QUANT_REPORT.json").write_text(json.dumps(report,indent=2)+"\n")
    print("CATERPILLAR_QUANT="+json.dumps({
        "equity":report["equity"],"return_pct":report["return_pct"],
        "closed_trades":report["closed_trades"],"reentries":report["reentries"],
        "mean_mfe_capture_ratio":report["mean_mfe_capture_ratio"],
        "active_local":report["active_local"],
        "local_models":report["local_models"],"exit_model":report["exit_model"]
    },separators=(",",":")),flush=True)

if __name__=="__main__":
    main()
