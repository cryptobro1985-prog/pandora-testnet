#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,pickle,time,os
import requests
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from research.hype_quant.features import FeatureState
from research.hype_quant.agents import augment_with_agents
from research.hype_quant.astra_cortex import AstraCortex,AstraPaperBook
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


def bootstrap_full_h1(state):
    """Deterministically seed the live learner with the relay's full H1 graph.

    This removes process-start ordering races between context_capture and the
    learner. Failure is non-fatal because websocket/context streams still run.
    """
    base=os.environ.get("HYPE_REST_RELAY_URL","").strip().rstrip("/")
    if not base:return {"ok":False,"reason":"relay_not_configured","h1":len(state.candles.get("60",{}))}
    try:
        r=requests.get(base+"/hype-context",headers={"User-Agent":"PANDORA-Caterpillar-H1-Bootstrap/1.0"},timeout=20)
        r.raise_for_status();obj=r.json()
        rows=((obj.get("candles") or {}).get("60") or [])
        if not isinstance(rows,list):rows=[]
        state.update_market_context({
            "received_ts_ms":int(time.time()*1000),
            "initial_backfill":True,
            "candles":{"60":rows},
            "ticker":obj.get("ticker") or {},
            "account_ratio":obj.get("account_ratio") or {},
            "server_time":{"ok":True,"value":obj.get("server_time") or {}},
            "rest_relay_configured":True,
        })
        return {"ok":True,"relay_rows":len(rows),"h1":len(state.candles.get("60",{}))}
    except Exception as exc:
        return {"ok":False,"reason":repr(exc),"h1":len(state.candles.get("60",{}))}


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
        "bounce_models":report.get("bounce_models") or {},
        "exit_model":report.get("exit_model") or {},
        "reentry_model":report.get("reentry_model") or {},
        "local_target":report.get("local_target"),
        "local_policy":report.get("local_policy"),
        "bootstrap_diagnostic":report.get("bootstrap_diagnostic") or {},
        "training_progress":report.get("training_progress") or {},
        "structural_history":report.get("structural_history") or {},
        "policy_state":report.get("policy_state"),
        "feature_contract":report.get("feature_contract") or {},
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
            "labels":q.get("labels"),"v2_labels":q.get("v2_labels"),"contract_version":q.get("contract_version"),
            "pending":q.get("pending"),"champion_ready":q.get("champion_ready"),
            "promotions":q.get("promotions"),"drift_events":q.get("drift_events"),
            "last_action":q.get("last_action"),"action_counts":q.get("action_counts"),
        },
        "astra":report.get("astra") or {},
        "astra_paper":report.get("astra_paper") or {},
        "astra_vs_quant_delta_pct":report.get("astra_vs_quant_delta_pct"),
        "research_only":True,"real_orders":False,
        "github_run_id":os.environ.get("GITHUB_RUN_ID"),"github_sha":os.environ.get("GITHUB_SHA"),
    }

def enrich_astra(report,cortex,astra_book):
    out=dict(report)
    out["astra"]=cortex.status()
    out["astra_paper"]=astra_book.report()
    qret=out.get("return_pct");aret=out["astra_paper"].get("return_pct")
    out["astra_vs_quant_delta_pct"]=(float(aret)-float(qret)) if qret is not None and aret is not None else None
    return out

def publish_monitor(report):
    url=os.environ.get("CATERPILLAR_MONITOR_URL","").strip()
    if not url:return
    try:
        r=requests.post(
            url,
            headers={"X-Caterpillar-Research":"1","User-Agent":"pandora-caterpillar-quant/2.0"},
            json=compact_status(report),
            timeout=5,
        )
        r.raise_for_status()
    except Exception:
        pass

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
        f"**Policy:** {status.get('policy_state') or 'WAIT'} · target {status.get('local_target') or '—'}  ",
        f"**Training maturity:** {(status.get('training_progress') or {}).get('overall_percent','—')}% · {(status.get('training_progress') or {}).get('status','—')}  ",
        f"**Structural history:** {(status.get('structural_history') or {}).get('bars_loaded','—')} H1 · {(status.get('structural_history') or {}).get('strict_pivots','—')} pivots · {(status.get('structural_history') or {}).get('closed_legs','—')} legs  ",
        f"**Inputs seen:** {(status.get('feature_contract') or {}).get('seen_input_count','—')} / {len((status.get('feature_contract') or {}).get('supported_input_ids') or [])}  ",
        f"**Paper:** equity {p.get('equity')} · return {p.get('return_pct')}% · trades {p.get('closed_trades')} · re-entry {p.get('reentries')}  ",
        f"**MFE capture:** {p.get('mean_mfe_capture_ratio')} · Caterpillar vs straight: {p.get('caterpillar_vs_straight_delta_pct')} pp  ",
        f"**Astra:** {(status.get('astra') or {}).get('state','—')} · decision {((status.get('astra') or {}).get('last_decision') or {}).get('decision','—')} · calls {(status.get('astra') or {}).get('calls',0)}  ",
        f"**Astra PAPER:** equity {(status.get('astra_paper') or {}).get('equity')} · return {(status.get('astra_paper') or {}).get('return_pct')}% · delta vs Quant {status.get('astra_vs_quant_delta_pct')} pp  ",
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
    h1_bootstrap=bootstrap_full_h1(state)
    print("CATERPILLAR_H1_BOOTSTRAP "+json.dumps(h1_bootstrap,separators=(",",":")),flush=True)
    tail=Tailer()
    actions=args.checkpoint_dir/"caterpillar_actions.jsonl"
    gaps=args.checkpoint_dir/"caterpillar_gaps.jsonl"
    astra_actions=args.checkpoint_dir/"astra_actions.jsonl"
    actions.touch(exist_ok=True);gaps.touch(exist_ok=True);astra_actions.touch(exist_ok=True)
    cortex=AstraCortex(args.checkpoint_dir)
    astra_book=AstraPaperBook(args.checkpoint_dir,learner.round_trip_cost)
    astra_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix="astra-cortex")
    astra_future=None

    started=time.time();deadline=started+args.minutes*60
    next_save=0.0;next_issue=0.0;next_monitor=0.0;next_sample_ms=0
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
            astra_book.mark(ts,price)
            if astra_future is not None and astra_future.done():
                try:
                    ar=astra_future.result()
                    if ar.get("new_decision") and isinstance(ar.get("decision"),dict):
                        adec=dict(ar["decision"])
                        source_ts=int(adec.get("ts_ms") or ts)
                        latency_s=max(0.0,(ts-source_ts)/1000.0)
                        adec["applied_latency_seconds"]=latency_s
                        applied=latency_s<=90.0
                        if applied:
                            astra_book.apply(ts,price,adec)
                        append_jsonl(astra_actions,{
                            "source_ts_ms":source_ts,"applied_ts_ms":ts,"applied_price":price,
                            "applied":applied,"latency_seconds":latency_s,"decision":adec,
                        })
                except Exception as exc:
                    append_jsonl(astra_actions,{"ts_ms":ts,"worker_error":repr(exc)})
                astra_future=None
            base_report=learner.report()
            if astra_future is None and cortex.due(ts,x,decision,base_report):
                astra_future=astra_pool.submit(
                    cortex.observe,ts,price,dict(x),decision,base_report,learner.round_trip_cost
                )
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
            report=enrich_astra(report,cortex,astra_book)
            (args.checkpoint_dir/"CATERPILLAR_QUANT_REPORT.json").write_text(json.dumps(report,indent=2)+"\n")
            next_save=now+60
        if now>=next_monitor:
            report=learner.report()
            report.update({"processed_micro_rows":processed_micro,"sampled_states":sampled,
                           "last_seen_ts_ms":last_seen_ts,"updated_ts_ms":int(now*1000),
                           "feature_contract":state.coverage_report(),
                           "research_only":True,"real_orders":False})
            report=enrich_astra(report,cortex,astra_book)
            publish_monitor(report)
            next_monitor=now+10
        if now>=next_issue:
            report=learner.report()
            report.update({"processed_micro_rows":processed_micro,"sampled_states":sampled,
                           "last_seen_ts_ms":last_seen_ts,"updated_ts_ms":int(now*1000),
                           "feature_contract":state.coverage_report(),
                           "research_only":True,"real_orders":False})
            report=enrich_astra(report,cortex,astra_book)
            publish_issue(report)
            next_issue=now+30
        if not events:time.sleep(args.poll_seconds)

    learner.save(cp);save_state(state,fs_path)
    report=learner.report()
    report.update({"processed_micro_rows":processed_micro,"sampled_states":sampled,
                   "last_seen_ts_ms":last_seen_ts,"completed_ts_ms":int(time.time()*1000),
                   "feature_contract":state.coverage_report(),
                   "research_only":True,"real_orders":False})
    report=enrich_astra(report,cortex,astra_book)
    cortex.save();astra_book.save()
    (args.checkpoint_dir/"CATERPILLAR_QUANT_REPORT.json").write_text(json.dumps(report,indent=2)+"\n")
    publish_monitor(report)
    publish_issue(report)
    astra_pool.shutdown(wait=False,cancel_futures=True)
    print("CATERPILLAR_QUANT="+json.dumps({
        "equity":report["equity"],"return_pct":report["return_pct"],
        "closed_trades":report["closed_trades"],"reentries":report["reentries"],
        "mean_mfe_capture_ratio":report["mean_mfe_capture_ratio"],
        "active_local":report["active_local"],
        "local_models":report["local_models"],"exit_model":report["exit_model"]
    },separators=(",",":")),flush=True)

if __name__=="__main__":
    main()
