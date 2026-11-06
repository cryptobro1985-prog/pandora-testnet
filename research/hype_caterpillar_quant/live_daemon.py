#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,pickle,time,os
import requests
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


def compact_status(report):
    q=report.get("quant") or {}
    return {
        "status":report.get("learning_status","LEARNING"),
        "updated_ts_ms":report.get("updated_ts_ms") or report.get("completed_ts_ms"),
        "last_seen_ts_ms":report.get("last_seen_ts_ms"),
        "freshness_seconds":None if not report.get("last_seen_ts_ms") else max(0.0,(time.time()*1000-report["last_seen_ts_ms"])/1000.0),
        "sampled_states":report.get("sampled_states",0),
        "processed_micro_rows":report.get("processed_micro_rows",0),
        "relationships_total":report.get("relationships_total",0),
        "positive_relationships":report.get("positive_relationships",0),
        "negative_relationships":report.get("negative_relationships",0),
        "prediction_checks":report.get("prediction_checks",0),
        "errors_total":report.get("errors_total",0),
        "error_rate":report.get("error_rate"),
        "prediction_errors":report.get("prediction_errors") or {},
        "active_local":report.get("active_local"),
        "local_models":report.get("local_models") or {},
        "exit_model":report.get("exit_model") or {},
        "paper":{
            "equity":report.get("equity"),"return_pct":report.get("return_pct"),
            "max_drawdown_pct":report.get("max_drawdown_pct"),"closed_trades":report.get("closed_trades"),
            "win_rate":report.get("win_rate"),"profit_factor":report.get("profit_factor"),
            "reentries":report.get("reentries"),"mean_mfe_capture_ratio":report.get("mean_mfe_capture_ratio"),
            "caterpillar_path_return_pct":report.get("caterpillar_path_return_pct"),
            "straight_local_path_return_pct":report.get("straight_local_path_return_pct"),
            "caterpillar_vs_straight_delta_pct":report.get("caterpillar_vs_straight_delta_pct"),
            "open_position":report.get("open_position"),
        },
        "quant":{
            "labels":q.get("labels"),"pending":q.get("pending"),"champion_ready":q.get("champion_ready"),
            "promotions":q.get("promotions"),"drift_events":q.get("drift_events"),
            "last_action":q.get("last_action"),"action_counts":q.get("action_counts"),
        },
        "research_only":True,"real_orders":False,
        "github_run_id":os.environ.get("GITHUB_RUN_ID"),"github_sha":os.environ.get("GITHUB_SHA"),
    }

def publish_issue(report):
    token=os.environ.get("GITHUB_TOKEN")
    repo=os.environ.get("GITHUB_REPOSITORY","cryptobro1985-prog/pandora-testnet")
    issue=os.environ.get("CATERPILLAR_STATUS_ISSUE","24")
    if not token or not issue:return
    status=compact_status(report);p=status["paper"];fence=chr(96)*3
    fresh=status["freshness_seconds"]
    lines=[
        "# HYPE Caterpillar Quant — LIVE",
        f"**Status:** {status['status']}  ",
        f"**Freshness:** {fresh:.1f}s  " if fresh is not None else "**Freshness:** —  ",
        f"**Relationships:** {status['relationships_total']} · + {status['positive_relationships']} · − {status['negative_relationships']}  ",
        f"**Checks / errors:** {status['prediction_checks']} / {status['errors_total']}  ",
        f"**Local:** {status['active_local'] or 'WAIT'}  ",
        f"**Paper:** equity {p.get('equity')} · return {p.get('return_pct')}% · trades {p.get('closed_trades')} · re-entry {p.get('reentries')}  ",
        f"**MFE capture:** {p.get('mean_mfe_capture_ratio')} · Caterpillar vs straight: {p.get('caterpillar_vs_straight_delta_pct')} pp  ",
        "",fence+"json",json.dumps(status,separators=(',',':'),ensure_ascii=False),fence,
    ]
    try:
        r=requests.patch(f"https://api.github.com/repos/{repo}/issues/{issue}",
            headers={"Authorization":f"Bearer {token}","Accept":"application/vnd.github+json"},
            json={"body":"\n".join(lines)},timeout=10)
        r.raise_for_status()
    except Exception:
        pass

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
    next_save=0.0;next_publish=0.0;next_sample_ms=0
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
        if now>=next_publish:
            report=learner.report()
            report.update({"processed_micro_rows":processed_micro,"sampled_states":sampled,
                           "last_seen_ts_ms":last_seen_ts,"updated_ts_ms":int(now*1000),
                           "research_only":True,"real_orders":False})
            publish_issue(report)
            next_publish=now+30
        if not events:time.sleep(args.poll_seconds)

    learner.save(cp);save_state(state,fs_path)
    report=learner.report()
    report.update({"processed_micro_rows":processed_micro,"sampled_states":sampled,
                   "last_seen_ts_ms":last_seen_ts,"completed_ts_ms":int(time.time()*1000),
                   "feature_contract":state.coverage_report(),
                   "research_only":True,"real_orders":False})
    (args.checkpoint_dir/"CATERPILLAR_QUANT_REPORT.json").write_text(json.dumps(report,indent=2)+"\n")
    publish_issue(report)
    print("CATERPILLAR_QUANT="+json.dumps({
        "equity":report["equity"],"return_pct":report["return_pct"],
        "closed_trades":report["closed_trades"],"reentries":report["reentries"],
        "mean_mfe_capture_ratio":report["mean_mfe_capture_ratio"],
        "active_local":report["active_local"],
        "local_models":report["local_models"],"exit_model":report["exit_model"]
    },separators=(",",":")),flush=True)

if __name__=="__main__":
    main()
