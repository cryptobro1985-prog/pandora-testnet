#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math,os,pickle,signal,time
from dataclasses import dataclass,asdict
from pathlib import Path
import requests

from research.hype_quant.features import FeatureState
from research.hype_quant.live_daemon import Tailer,event_ts
from research.hype_local_only.model import LocalOnlyModel,Candidate,STAGES
from research.hype_local_only.live_features import live_to_archive_features
from research.hype_false_local_entry.dual_scope_teacher import (
    INTERNAL, STRICT, collapsed_pivots, finalized_terminal_label, teacher_contract,
)
from research.hype_false_local_entry.hard_survival_gate import (
    CHECKPOINT_GRACE_S, HardCandidate, checkpoint_sample as hard120_checkpoint_sample,
    contract as survival_contract, gate_metrics as hard120_gate_metrics,
    maybe_start_or_extend as survival_update, next_signal as survival_next_signal,
)
from research.hype_false_local_entry.high_flow_shadow import (
    HighFlowShadowState, capture_flow15 as capture_high_flow15,
    contract as high_flow_shadow_contract,
    should_emit_shadow as should_emit_high_flow_shadow,
)
from research.hype_false_local_entry.high_flow_shadow_v2 import (
    contract as high_flow_v2_contract,
    qualifies as qualifies_high_flow_v2,
)
from research.hype_false_local_entry.high_flow_regime_gate_v3 import (
    contract as high_flow_v3_contract,
    metrics as high_flow_v3_metrics,
)
from research.hype_false_local_entry.early60_strong_reversal_shadow import (
    Early60State, capture_flow15 as capture_early60_flow15,
    checkpoint_sample as early60_checkpoint_sample,
    contract as early60_shadow_contract,
    evaluate_once as evaluate_early60_once,
)
from research.hype_false_local_entry.hard120_persistence_shadow import (
    contract as hard120_persistence_contract,
    persistence_metrics as hard120_persistence_metrics,
)
from research.hype_false_local_entry.high60_retrace_veto import (
    contract as high60_veto_contract,
    sample_retrace60 as high60_sample_retrace,
    high_primary_confirmed as high60_primary_confirmed,
)
from research.hype_false_local_entry.time_to_confirmation_engine import (
    CHECKPOINTS_S as TTC_CHECKPOINTS_S,
    TimeToConfirmationEngine,
)
from research.hype_false_local_entry.time_to_confirmation_live import (
    build_confirmation_evidence,
)

H=3_600_000

@dataclass
class Pending:
    candidate_id:str
    side:str
    stage:int
    extreme_price:float
    extreme_ts_ms:int
    x:dict[str,float]
    mature_ms:int
    teacher_scope:str="STRICT_L6_K2"

def load_pickle(path,default):
    try:
        with path.open("rb") as f:return pickle.load(f)
    except Exception:return default

def save_pickle(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(".tmp")
    with tmp.open("wb") as f:pickle.dump(obj,f,pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)

def completed_h1(state,ts_ms):
    out=[]
    for start in sorted(state.candles.get("60",{})):
        if int(start)+H>int(ts_ms):continue
        b=state.candles["60"][start]
        try:
            out.append({"start_ms":int(start),"high":float(b["high"]),"low":float(b["low"]),
                        "open":float(b["open"]),"close":float(b["close"])})
        except Exception:pass
    return out

def completed_m1(state,ts_ms):
    """Completed M1 bars only; used by the causal HARD120 pre-move feature."""
    out=[]
    for start in sorted(state.candles.get("1",{})):
        if int(start)+60_000>int(ts_ms):continue
        b=state.candles["1"][start]
        try:
            out.append({"start_ms":int(start),"bar_end_ms":int(start)+60_000,
                        "high":float(b["high"]),"low":float(b["low"]),
                        "close":float(b["close"])})
        except Exception:pass
    return out

def strict_pivots(state,ts_ms):
    """Return only causally TERMINAL-finalized STRICT pivots.

    The last collapsed K2 pivot is still provisional.  A pivot becomes a
    terminal Local only when the next opposite K2 pivot has itself matured.
    Therefore each returned Local's available_ms is the next pivot's
    availability time, not its own K2 time.
    """
    raw=collapsed_pivots(completed_h1(state,ts_ms),STRICT,now_ms=ts_ms)
    out=[]
    for cur,nxt in zip(raw,raw[1:]):
        if cur["side"]==nxt["side"]:
            continue
        out.append({
            "side":cur["side"],
            "price":cur["price"],
            "hour_ms":cur["hour_ms"],
            "pivot_available_ms":cur["available_ms"],
            "available_ms":nxt["available_ms"],
            "finalized_by_opposite_hour_ms":nxt["hour_ms"],
            "terminal_finalized":True,
        })
    return out

def structural_replay_48h(state,ts_ms):
    """Recover the confirmed H1 Local sequence for the last 48h.

    Uses only terminal-finalized STRICT pivots.  The latest provisional K2
    pivot is deliberately excluded until a later opposite K2 pivot matures.
    This is causal structural memory, not a future-looking label feed.
    """
    cutoff=int(ts_ms)-48*H
    piv=[z for z in strict_pivots(state,ts_ms)
         if int(z.get("available_ms",0))<=int(ts_ms) and int(z.get("hour_ms",0))>=cutoff]
    highs=[z for z in piv if z["side"]=="HIGH"]
    lows=[z for z in piv if z["side"]=="LOW"]
    last=piv[-1] if piv else None
    previous=piv[-2] if len(piv)>=2 else None
    leg=("UP_TO_NEXT_HIGH" if last and last["side"]=="LOW"
         else "DOWN_TO_NEXT_LOW" if last and last["side"]=="HIGH" else "UNKNOWN")
    high_structure="UNKNOWN"
    low_structure="UNKNOWN"
    if len(highs)>=2:
        high_structure="HIGHER_HIGH" if highs[-1]["price"]>highs[-2]["price"] else "LOWER_HIGH"
    if len(lows)>=2:
        low_structure="HIGHER_LOW" if lows[-1]["price"]>lows[-2]["price"] else "LOWER_LOW"
    if high_structure=="HIGHER_HIGH" and low_structure=="HIGHER_LOW":
        regime="UP_STRUCTURE"
    elif high_structure=="LOWER_HIGH" and low_structure=="LOWER_LOW":
        regime="DOWN_STRUCTURE"
    else:
        regime="MIXED_STRUCTURE"
    current=float(getattr(state,"last_price",0) or 0)
    anchor_move_bps=None
    if last and current>0 and float(last["price"])>0:
        anchor_move_bps=(current/float(last["price"])-1.0)*10000.0
    swing_bps=None
    if last and previous and float(previous["price"])>0:
        swing_bps=abs(float(last["price"])/float(previous["price"])-1.0)*10000.0
    return {
        "window_hours":48,
        "confirmed_local_count":len(piv),
        "locals":piv,
        "last_local":last,
        "previous_local":previous,
        "active_leg":leg,
        "high_structure":high_structure,
        "low_structure":low_structure,
        "regime":regime,
        "anchor_move_bps":anchor_move_bps,
        "last_swing_bps":swing_bps,
        "hours_since_last_local":(None if not last else max(0.0,(int(ts_ms)-int(last["hour_ms"]))/H)),
    }

def replay48_features(replay,price,ts_ms):
    out={}
    if not replay:return out
    out["structure48_active_leg_up"]=1.0 if replay.get("active_leg")=="UP_TO_NEXT_HIGH" else 0.0
    out["structure48_active_leg_down"]=1.0 if replay.get("active_leg")=="DOWN_TO_NEXT_LOW" else 0.0
    out["structure48_regime_up"]=1.0 if replay.get("regime")=="UP_STRUCTURE" else 0.0
    out["structure48_regime_down"]=1.0 if replay.get("regime")=="DOWN_STRUCTURE" else 0.0
    out["structure48_higher_high"]=1.0 if replay.get("high_structure")=="HIGHER_HIGH" else 0.0
    out["structure48_lower_high"]=1.0 if replay.get("high_structure")=="LOWER_HIGH" else 0.0
    out["structure48_higher_low"]=1.0 if replay.get("low_structure")=="HIGHER_LOW" else 0.0
    out["structure48_lower_low"]=1.0 if replay.get("low_structure")=="LOWER_LOW" else 0.0
    out["structure48_confirmed_local_count"]=float(replay.get("confirmed_local_count") or 0)
    if isinstance(replay.get("hours_since_last_local"),(int,float)):
        out["structure48_hours_since_last_local"]=float(replay["hours_since_last_local"])
    if isinstance(replay.get("last_swing_bps"),(int,float)):
        out["structure48_last_swing_bps"]=float(replay["last_swing_bps"])
    last=replay.get("last_local") or {}
    if isinstance(last.get("price"),(int,float)) and float(last["price"])>0 and price>0:
        out["structure48_distance_from_last_local_bps"]=(float(price)/float(last["price"])-1.0)*10000.0
        out["structure48_last_side_low"]=1.0 if last.get("side")=="LOW" else 0.0
        out["structure48_last_side_high"]=1.0 if last.get("side")=="HIGH" else 0.0
    return out

def teacher_label(state,p,ts_ms):
    """Mature either INTERNAL L3/K1 or STRICT L6/K2 without future leakage."""
    if ts_ms<int(p.mature_ms):return None
    teacher_name=getattr(p,"teacher_scope",STRICT.name)
    return finalized_terminal_label(
        completed_h1(state,ts_ms),
        p.extreme_ts_ms,
        p.side,
        teacher_name,
        ts_ms,
    )

def append_jsonl(path,obj):
    with path.open("a",encoding="utf-8") as f:f.write(json.dumps(obj,separators=(",",":"),ensure_ascii=False)+"\n")

def publish_monitor(status):
    url=os.getenv("LOCAL_ONLY_MONITOR_URL","").strip()
    if not url:return
    payload=dict(status)
    payload["mode"]="LOCAL_ONLY"
    payload["local_target"]="DUAL_INTERNAL_L3_K1__STRICT_L6_K2"
    payload["github_run_id"]=os.getenv("GITHUB_RUN_ID")
    payload["github_sha"]=os.getenv("GITHUB_SHA")
    payload["research_only"]=True
    payload["real_orders"]=False
    try:
        r=requests.post(url,
            headers={"X-Caterpillar-Research":"1","User-Agent":"pandora-hype-local-only/1.0"},
            json=payload,timeout=6)
        r.raise_for_status()
    except Exception:
        pass

def publish_issue(status):
    token=os.getenv("GITHUB_TOKEN")
    if not token:return
    repo=os.getenv("GITHUB_REPOSITORY","cryptobro1985-prog/pandora-testnet")
    c=status.get("candidate") or {};p=c.get("probabilities") or {}
    lines=[
        "# HYPE LOCAL-ONLY — LIVE",
        f"**Status:** {status.get('status')}  ",
        f"**Expected next Local:** {status.get('expected_side') or 'UNKNOWN'}  ",
        f"**Last teacher Local:** {status.get('last_teacher_local') or '—'}  ",
        f"**48h leg:** {(status.get('structure_48h') or {}).get('active_leg','UNKNOWN')} · {(status.get('structure_48h') or {}).get('regime','UNKNOWN')}  ",
        f"**48h locals:** {[(z.get('side'),z.get('price')) for z in (status.get('structure_48h') or {}).get('locals',[])]}  ",
        f"**Candidate:** {c.get('side','—')} @ {c.get('extreme_price','—')} · age {c.get('age_s','—')}s  ",
        f"**P60/P180/P300:** {p.get('60','—')} / {p.get('180','—')} / {p.get('300','—')}  ",
        f"**Stage:** {c.get('stage','WAIT')}  ",
        f"**Historical labels:** {status.get('historical_labels')} · live matured {status.get('live_labels')} · pending {status.get('pending_labels')}  ",
        f"**Inputs seen:** {status.get('seen_input_count')}/86  ",
        f"**Cortex:** {status.get('cortex_state')}  ",
        "",
        "~~~json",json.dumps(status,separators=(",",":"),ensure_ascii=False),"~~~",
    ]
    try:
        r=requests.patch(f"https://api.github.com/repos/{repo}/issues/24",
            headers={"Authorization":f"Bearer {token}","Accept":"application/vnd.github+json"},
            json={"body":"\n".join(lines)},timeout=10)
        r.raise_for_status()
    except Exception:pass

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--capture-root",type=Path,required=True)
    ap.add_argument("--checkpoint-dir",type=Path,required=True)
    ap.add_argument("--minutes",type=int,required=True)
    args=ap.parse_args();args.checkpoint_dir.mkdir(parents=True,exist_ok=True)

    mp=args.checkpoint_dir/"local_only_model.pkl"
    if not mp.exists():raise SystemExit("local_only_model.pkl missing")
    model=LocalOnlyModel.load(mp)
    # Old v1 checkpoints do not contain the tactical INTERNAL learner.
    model._ensure_internal_scope()
    fp=args.checkpoint_dir/"feature_state.pkl";state=load_pickle(fp,FeatureState())
    rp=args.checkpoint_dir/"local_runtime.pkl"
    rt=load_pickle(rp,{"candidates":{"LOW":None,"HIGH":None},"hard_candidates":{"LOW":None,"HIGH":None},
                       "hard_high_flow_shadow":{"LOW":None,"HIGH":None},
                       "hard_high_flow_v2_emitted":{"LOW":None,"HIGH":None},
                       "hard_early60_shadow":{"LOW":None,"HIGH":None},
                       "pending":[],"expected_side":None,
                       "last_teacher_local":None,"latest_by_hour":{},"structure_48h":{}})
    candidates=rt.get("candidates") or {"LOW":None,"HIGH":None}
    hard_candidates={}
    for _side in ("LOW","HIGH"):
        _z=(rt.get("hard_candidates") or {}).get(_side)
        hard_candidates[_side]=HardCandidate(**_z) if isinstance(_z,dict) else _z
    hard_high_flow_shadow={}
    for _side in ("LOW","HIGH"):
        _z=(rt.get("hard_high_flow_shadow") or {}).get(_side)
        hard_high_flow_shadow[_side]=HighFlowShadowState(**_z) if isinstance(_z,dict) else _z
    hard_high_flow_v2_emitted=rt.get("hard_high_flow_v2_emitted") or {"LOW":None,"HIGH":None}
    hard_early60_shadow={}
    for _side in ("LOW","HIGH"):
        _z=(rt.get("hard_early60_shadow") or {}).get(_side)
        hard_early60_shadow[_side]=Early60State(**_z) if isinstance(_z,dict) else _z
    pending=[Pending(**z) if isinstance(z,dict) else z for z in rt.get("pending",[])]
    expected=rt.get("expected_side");last_teacher=rt.get("last_teacher_local")
    latest_by_hour=rt.get("latest_by_hour") or {}
    structure_48h=rt.get("structure_48h") or {}
    # Early time-to-confirmation is a shadow research layer. It never changes
    # expected/core direction and never places real orders.
    ttc_engine=TimeToConfirmationEngine()

    tail=Tailer();stop=False
    def stopfn(*_):
        nonlocal stop;stop=True
    signal.signal(signal.SIGTERM,stopfn);signal.signal(signal.SIGINT,stopfn)

    evlog=args.checkpoint_dir/"LOCAL_EVENTS.jsonl";evlog.touch(exist_ok=True)
    lablog=args.checkpoint_dir/"LOCAL_LIVE_LABELS.jsonl";lablog.touch(exist_ok=True)
    status_path=args.checkpoint_dir/"LOCAL_ONLY_STATUS.json"
    deadline=time.time()+args.minutes*60
    last_seen=state.last_ts_ms;next_sample=next_save=next_issue=next_monitor=0;status={}

    while time.time()<deadline and not stop:
        events=[]
        for pth in sorted(args.capture_root.rglob("HYPE_live_raw_frames.jsonl")):
            for row in tail.read_new(pth):events.append((event_ts("raw",row),0,"raw",row))
        for pth in sorted(args.capture_root.rglob("HYPE_market_context.jsonl")):
            for row in tail.read_new(pth):events.append((event_ts("market",row),1,"market",row))
        for pth in sorted(args.capture_root.rglob("HYPE_structural_context_1m.jsonl")):
            for row in tail.read_new(pth):events.append((event_ts("struct",row),2,"struct",row))
        for pth in sorted(args.capture_root.rglob("HYPE_live_microstructure_1s.jsonl")):
            for row in tail.read_new(pth):events.append((event_ts("micro",row),3,"micro",row))
        events.sort(key=lambda z:(z[0],z[1]))

        for ts,_,kind,row in events:
            if ts<=0:continue
            if kind=="raw":state.update_raw_frame(row);continue
            if kind=="market":state.update_market_context(row);continue
            if kind=="struct":state.update_structural_context(row);continue
            if last_seen is not None and ts<=last_seen:continue
            last_seen=ts
            try:price,x=state.update_micro(row)
            except Exception:continue
            if ts<next_sample:continue
            next_sample=ts+5000

            # H1 prior is scored with frozen clean finalized-history weights.
            # Online K2-pivot learning is disabled because the latest pivot is
            # provisional until an opposite terminal pivot matures.
            model.update_h1_shadow_only(state,ts)

            # Rebuild the last 48h structural memory from the REST/WS H1 backfill.
            # This makes workflow restarts remember the prior LOW/HIGH sequence.
            fresh48=structural_replay_48h(state,ts)
            if fresh48.get("confirmed_local_count"):
                structure_48h=fresh48
                recovered=fresh48.get("last_local")
                if recovered and (last_teacher is None or int(recovered["hour_ms"])>=int(last_teacher.get("hour_ms",0))):
                    last_teacher=recovered
                    expected="HIGH" if recovered["side"]=="LOW" else "LOW"

            piv=strict_pivots(state,ts)
            if piv:
                latest=piv[-1]
                if last_teacher is None or latest["hour_ms"]>int(last_teacher.get("hour_ms",0)):
                    last_teacher=latest
                    # Teacher Local is authoritative for the active structural leg:
                    # after LOW we search HIGH; after HIGH we search LOW.
                    expected="LOW" if latest["side"]=="HIGH" else "HIGH"

            # Dense causal proposals: 5m / 15m / 60m / 6h. These only propose;
            # strict H1 L6/K2 remains the teacher.
            struct=state.structural or {}
            levels={
                "LOW":[("5m",x.get("running_low_300s")),("15m",x.get("running_low_900s")),
                       ("60m",struct.get("rolling_60m_low")),("6h",struct.get("rolling_6h_low"))],
                "HIGH":[("5m",x.get("running_high_300s")),("15m",x.get("running_high_900s")),
                        ("60m",struct.get("rolling_60m_high")),("6h",struct.get("rolling_6h_high"))],
            }
            for side in ("LOW","HIGH"):
                valid=[(name,float(v)) for name,v in levels[side]
                       if isinstance(v,(int,float)) and math.isfinite(v)]
                if not valid:continue
                if side=="LOW":
                    hit=[(n,v) for n,v in valid if price<=v*(1+0.75/10000.0)]
                else:
                    hit=[(n,v) for n,v in valid if price>=v*(1-0.75/10000.0)]
                if not hit:continue
                old=candidates.get(side)
                extends=old is None or (price<old.extreme_price if side=="LOW" else price>old.extreme_price)
                stale=old is not None and ts-old.extreme_ts_ms>H
                if extends or stale:
                    windows=[n for n,_ in hit]
                    evidence={"proposal":"MULTIWINDOW_CAUSAL","windows":windows}
                    c=Candidate(side,float(price),int(ts),f"{side[0]}-{ts}",evidence=evidence)
                    candidates[side]=c
                    if old is not None and extends:
                        append_jsonl(evlog,{
                            "event":"TTC_INVALIDATED","ts_ms":int(ts),
                            "signal_ts_ms":int(ts),
                            "candidate_ts_ms":int(old.extreme_ts_ms),
                            "candidate_id":old.candidate_id,"side":side,
                            "price":float(old.extreme_price),
                            "replacement_price":float(price),
                            "reason":"new_same_side_extreme",
                            "research_only":True,"real_orders":False,
                        })
                    if stale and not extends:
                        ttc_engine.active[side]=None
                    ttc_engine.start_or_extend(side,int(ts),float(price))
                    # HARD120 keeps an independent lineage.  Hourly stale
                    # refreshes never reset it; only a genuinely more-extreme
                    # 6h candidate can replace the lineage.
                    if extends:
                        _old_hard=hard_candidates.get(side)
                        _new_hard=survival_update(
                            _old_hard,
                            side=side,price=float(price),ts_ms=int(ts),
                            candidate_id=c.candidate_id,windows=windows,
                            completed_m1_rows=completed_m1(state,ts),
                        )
                        hard_candidates[side]=_new_hard
                        if (_new_hard is not None
                                and (_old_hard is None or _new_hard.candidate_id!=_old_hard.candidate_id)):
                            hard_early60_shadow[side]=Early60State(_new_hard.candidate_id)
                            if side=="HIGH":
                                hard_high_flow_shadow[side]=HighFlowShadowState(_new_hard.candidate_id)
                                hard_high_flow_v2_emitted[side]=None
                    hour=(int(ts)//H)*H
                    latest_by_hour[f"{side}:{hour}"]=c.candidate_id
                    append_jsonl(evlog,{"event":"NEW_CANDIDATE","ts_ms":ts,"side":side,"price":price,
                        "candidate_id":c.candidate_id,"evidence":evidence})

            for side in ("LOW","HIGH"):
                c=candidates.get(side)
                if c is None or c.invalidated:continue
                age=max(0.0,(ts-c.extreme_ts_ms)/1000.0)

                # Earliest causal confirmation shadow. Only on-time checkpoints
                # are scored; a restart that arrives too late must not
                # retroactively manufacture a 30/60/90/180/300s signal.
                if ttc_engine.active.get(side) is None:
                    ttc_engine.start_or_extend(side,int(c.extreme_ts_ms),float(c.extreme_price))
                ttc_done={int(v) for v in c.evidence.get("ttc_done",[]) if str(v).isdigit()}
                for checkpoint_s in TTC_CHECKPOINTS_S:
                    if checkpoint_s in ttc_done or age<checkpoint_s:
                        continue
                    if age>checkpoint_s+20:
                        append_jsonl(evlog,{
                            "event":"TTC_CHECKPOINT_MISSED","ts_ms":int(ts),
                            "candidate_ts_ms":int(c.extreme_ts_ms),
                            "candidate_id":c.candidate_id,"side":side,
                            "stage":int(checkpoint_s),
                            "age_s":float(age),
                            "reason":"observation_arrived_after_checkpoint_grace",
                            "research_only":True,"real_orders":False,
                        })
                        ttc_done.add(int(checkpoint_s))
                        continue
                    ttc_ev,ttc_diag=build_confirmation_evidence(
                        side=side,candidate=c,checkpoint_s=int(checkpoint_s),
                        ts_ms=int(ts),price=float(price),x=x,state=state,
                    )
                    ttc_decision=ttc_engine.evaluate(ttc_ev)
                    append_jsonl(evlog,{
                        "event":"TTC_CHECKPOINT","ts_ms":int(ts),
                        "signal_ts_ms":int(ts),
                        "candidate_ts_ms":int(c.extreme_ts_ms),
                        "candidate_id":c.candidate_id,"side":side,
                        "price":float(c.extreme_price),"mark_price":float(price),
                        "stage":int(checkpoint_s),
                        "ttc_state":ttc_decision.state.value,
                        "evidence_score":float(ttc_decision.score),
                        "threshold":float(ttc_engine.checkpoint_thresholds[int(checkpoint_s)]),
                        "enter":bool(ttc_decision.enter),
                        "target_side":ttc_decision.target_side,
                        "invalidation_price":float(ttc_decision.invalidation_price),
                        "diagnostics":ttc_diag,
                        "research_only":True,"real_orders":False,
                    })
                    if ttc_decision.enter and (expected is None or side==expected):
                        append_jsonl(evlog,{
                            "event":"TTC_SHADOW_SIGNAL","ts_ms":int(ts),
                            "signal_ts_ms":int(ts),
                            "candidate_ts_ms":int(c.extreme_ts_ms),
                            "candidate_id":c.candidate_id,"side":side,
                            "price":float(c.extreme_price),"mark_price":float(price),
                            "stage":int(checkpoint_s),
                            "probability":float(ttc_decision.score),
                            "evidence_score":float(ttc_decision.score),
                            "target_side":ttc_decision.target_side,
                            "teacher":STRICT.name,
                            "shadow_contract":"TIME_TO_CONFIRMATION_V1",
                            "core_flip_authorized":False,
                            "research_only":True,"real_orders":False,
                            "diagnostics":ttc_diag,
                        })
                    ttc_done.add(int(checkpoint_s))
                c.evidence["ttc_done"]=sorted(ttc_done)

                for stage in STAGES:
                    if age<stage or stage in c.stages_done:continue
                    fx=live_to_archive_features(side,age,c.extreme_price,price,x,state)
                    fx.update(replay48_features(structure_48h,price,ts))
                    prob,accepted=model.predict(side,stage,fx)
                    internal_prob,internal_accepted=model.predict_internal(side,stage,fx)
                    h1_prior=model.h1_prior(side)
                    c.snapshots[stage]=fx;c.probabilities[stage]=prob;c.stages_done.add(stage)
                    c.evidence.setdefault("internal_probabilities",{})[str(stage)]=internal_prob
                    c.evidence.setdefault("internal_accepted",{})[str(stage)]=internal_accepted
                    h=(c.extreme_ts_ms//H)*H
                    # One feature snapshot learns against TWO non-mixed teachers.
                    # INTERNAL matures at K1 (+2H from pivot-hour start), STRICT at
                    # K2 (+3H).  Neither label is available before its maturity.
                    pending.append(Pending(c.candidate_id,side,stage,c.extreme_price,c.extreme_ts_ms,fx,h+2*H,INTERNAL.name))
                    pending.append(Pending(c.candidate_id,side,stage,c.extreme_price,c.extreme_ts_ms,fx,h+3*H,STRICT.name))
                    relation=model.relationship_evidence(side,stage,fx)
                    append_jsonl(evlog,{"event":"LOCAL_STAGE","ts_ms":ts,"side":side,"stage":stage,
                        "probability":prob,"threshold":model.thresholds[(side,stage)],
                        "accepted":accepted,"h1_prior":h1_prior,"expected_side":expected,
                        "internal_probability":internal_prob,
                        "internal_threshold":model.internal_thresholds[(side,stage)],
                        "internal_ready":model.internal_ready(side,stage),
                        "internal_accepted":internal_accepted,
                        "candidate_id":c.candidate_id,"relationship_evidence":relation})
                    if internal_accepted and (expected is None or side==expected):
                        append_jsonl(evlog,{"event":"INTERNAL_TACTICAL_SIGNAL","ts_ms":ts,
                            "signal_ts_ms":int(ts),"candidate_ts_ms":int(c.extreme_ts_ms),
                            "side":side,"price":c.extreme_price,"candidate_id":c.candidate_id,
                            "stage":stage,"probability":internal_prob,
                            "teacher":INTERNAL.name,"core_flip_authorized":False})
                    if accepted and (expected is None or side==expected):
                        signal_state="FORMING_LOCAL" if stage==60 else "PROBABLE_LOCAL" if stage==180 else "LOCAL_SIGNAL"
                        model.last_signal={"side":side,"price":c.extreme_price,"candidate_id":c.candidate_id,
                            "detected_ts_ms":ts,"probability":prob,"h1_prior":h1_prior,
                            "stage":stage,"state":signal_state,"teacher":STRICT.name}
                        if stage==300:
                            expected="HIGH" if side=="LOW" else "LOW"
                        append_jsonl(evlog,{"event":signal_state,**model.last_signal,"next_expected":expected})

            # Independent high-confidence survival layer.  It is paper/tactical
            # only and never changes expected/core direction by itself.
            hard120_live={}
            high_flow_shadow_live={}
            high_flow_v2_live={}
            high_flow_v3_live={}
            early60_shadow_live={}
            high60_veto_live={}
            hard120_persistence_live={}
            for side in ("LOW","HIGH"):
                hc=hard_candidates.get(side)
                if hc is None:
                    hard120_live[side]=None
                    high_flow_shadow_live[side]=None
                    high_flow_v2_live[side]=None
                    high_flow_v3_live[side]=None
                    early60_shadow_live[side]=None
                    high60_veto_live[side]=None
                    hard120_persistence_live[side]=None
                    continue

                early_state=hard_early60_shadow.get(side)
                if early_state is None or early_state.candidate_id!=hc.candidate_id:
                    early_state=Early60State(hc.candidate_id)
                    hard_early60_shadow[side]=early_state
                early_flow_capture=capture_early60_flow15(
                    early_state,candidate_ts_ms=int(hc.extreme_ts_ms),
                    trades=list(state.trades),observed_ms=int(ts)
                )
                early_sample=early60_checkpoint_sample(
                    int(hc.extreme_ts_ms),completed_m1(state,ts),int(ts)
                )
                early_ready=False
                if early_sample is None:
                    early_metrics={"ready":False,"reason":"waiting_checkpoint",
                                   "flow_capture":early_flow_capture}
                elif not early_state.checkpoint_evaluated:
                    early_ready,early_metrics=evaluate_early60_once(
                        early_state,side=side,extreme_price=float(hc.extreme_price),
                        pre_move_180_bps=float(hc.pre_move_180_bps),
                        sample=early_sample,expected_side=expected
                    )
                    early_metrics["flow_capture"]=early_flow_capture
                    if early_ready:
                        append_jsonl(evlog,{
                            "event":"INTERNAL_EARLY60_STRONG_REVERSAL_SHADOW",
                            "ts_ms":int(ts),
                            "signal_ts_ms":int(early_sample.get("sample_ts_ms") or ts),
                            "candidate_ts_ms":int(hc.extreme_ts_ms),
                            "candidate_id":hc.candidate_id,"side":hc.side,
                            "price":float(hc.extreme_price),
                            "mark_price":float(early_sample.get("mark_price") or price),
                            "teacher":INTERNAL.name,
                            "shadow_contract":"EARLY60_STRONG_REVERSAL_SHADOW_V1",
                            "primary_contract":"INTERNAL_HARD120_CHECKPOINT_V2",
                            "core_flip_authorized":False,
                            "metrics":early_metrics,
                        })
                else:
                    early_metrics={
                        "ready":False,
                        "reason":"already_emitted" if early_state.emitted else "checkpoint_already_consumed",
                        "checkpoint_evaluated":early_state.checkpoint_evaluated,
                        "checkpoint_missed":early_state.checkpoint_missed,
                        "flow_15":early_state.flow_15,
                        "flow_15_trade_count":early_state.flow_15_trade_count,
                        "flow_capture":early_flow_capture,
                    }
                early60_shadow_live[side]={
                    "candidate_id":early_state.candidate_id,
                    "flow_15":early_state.flow_15,
                    "flow_15_trade_count":early_state.flow_15_trade_count,
                    "flow_15_sample_end_ms":early_state.flow_15_sample_end_ms,
                    "flow_15_missed":early_state.flow_15_missed,
                    "checkpoint_evaluated":early_state.checkpoint_evaluated,
                    "checkpoint_missed":early_state.checkpoint_missed,
                    "emitted":early_state.emitted,
                    "checkpoint":early_metrics,
                }

                shadow_state=hard_high_flow_shadow.get(side)
                if side=="HIGH":
                    if shadow_state is None or shadow_state.candidate_id!=hc.candidate_id:
                        shadow_state=HighFlowShadowState(hc.candidate_id)
                        hard_high_flow_shadow[side]=shadow_state
                    flow_capture=capture_high_flow15(
                        shadow_state,candidate_ts_ms=int(hc.extreme_ts_ms),
                        trades=list(state.trades),observed_ms=int(ts)
                    )
                else:
                    flow_capture={"ready":False,"missed":False}
                sample=hard120_checkpoint_sample(hc,completed_m1(state,ts),int(ts))
                if sample is None:
                    hard_stage=None
                    hard_metrics=hard120_gate_metrics(
                        hc,now_ms=int(ts),mark_price=float(price)
                    )
                    hard_metrics["checkpoint_sample_ready"]=False
                elif sample["fresh_observation"]:
                    hard_stage,hard_metrics=survival_next_signal(
                        hc,now_ms=int(sample["sample_ts_ms"]),
                        mark_price=float(sample["mark_price"]),expected_side=expected
                    )
                    hard_metrics.update(sample)
                    hard_metrics["checkpoint_sample_ready"]=True
                else:
                    # The exact checkpoint bar exists but was only observed
                    # after a long restart/gap. Consume the one-shot checkpoint
                    # as missed; never emit a retroactive trade signal.
                    hard_stage,hard_metrics=survival_next_signal(
                        hc,now_ms=int(ts),mark_price=float(price),expected_side=expected
                    )
                    hard_metrics.update(sample)
                    hard_metrics["checkpoint_sample_ready"]=True
                    hard_metrics["checkpoint_missed_due_to_observation_delay"]=True
                hard120_live[side]={
                    "candidate_id":hc.candidate_id,"side":hc.side,
                    "extreme_price":hc.extreme_price,"extreme_ts_ms":hc.extreme_ts_ms,
                    "emitted":hc.emitted,**hard_metrics,
                }

                shadow_ready=False
                shadow_metrics={
                    "ready":False,"flow_capture":flow_capture,
                    "reason":"HIGH_ONLY" if side!="HIGH" else "WAITING_CHECKPOINT"
                }
                if side=="HIGH" and shadow_state is not None and sample is not None:
                    shadow_ready,shadow_metrics=should_emit_high_flow_shadow(
                        side=side,
                        primary_emitted=bool(hard_stage),
                        expected_side_ok=bool(hard_metrics.get("expected_side_ok")),
                        checkpoint_fresh=bool(sample.get("fresh_observation")),
                        retrace_bps=float(hard_metrics.get("retrace_bps") or 0.0),
                        retrace_fraction_pre_180=float(hard_metrics.get("retrace_fraction_pre_180") or 0.0),
                        state=shadow_state,
                    )
                    shadow_metrics["flow_capture"]=flow_capture
                    if shadow_ready:
                        shadow_state.emitted=True
                        append_jsonl(evlog,{
                            "event":"INTERNAL_HARD120_HIGH_FLOW_SHADOW",
                            "ts_ms":int(ts),"signal_ts_ms":int(ts),
                            "candidate_ts_ms":int(hc.extreme_ts_ms),
                            "candidate_id":hc.candidate_id,"side":"HIGH",
                            "price":float(hc.extreme_price),
                            "mark_price":float(sample.get("mark_price") or price),
                            "teacher":INTERNAL.name,
                            "shadow_contract":"HARD120_HIGH_FLOW_SHADOW_V1",
                            "primary_contract":"INTERNAL_HARD120_CHECKPOINT_V2",
                            "core_flip_authorized":False,
                            "metrics":shadow_metrics,
                        })
                high_flow_shadow_live[side]=None if side!="HIGH" else {
                    "candidate_id":shadow_state.candidate_id,
                    "flow_15":shadow_state.flow_15,
                    "flow_15_trade_count":shadow_state.flow_15_trade_count,
                    "flow_15_sample_end_ms":shadow_state.flow_15_sample_end_ms,
                    "flow_15_missed":shadow_state.flow_15_missed,
                    "emitted":shadow_state.emitted,
                    "checkpoint":shadow_metrics,
                }

                v2_ready=False
                v2_metrics={
                    "ready":False,
                    "reason":"HIGH_ONLY" if side!="HIGH" else "WAITING_CHECKPOINT",
                }
                v3_ready=False
                v3_metrics={
                    "ready":False,
                    "reason":"HIGH_ONLY" if side!="HIGH" else "V2_NOT_READY",
                }
                if side=="HIGH" and shadow_state is not None and sample is not None:
                    v2_ready,v2_metrics=qualifies_high_flow_v2(
                        side=side,
                        primary_emitted=bool(hard_stage),
                        expected_side_ok=bool(hard_metrics.get("expected_side_ok")),
                        checkpoint_fresh=bool(sample.get("fresh_observation")),
                        retrace_bps=float(hard_metrics.get("retrace_bps") or 0.0),
                        retrace_fraction_pre_180=float(hard_metrics.get("retrace_fraction_pre_180") or 0.0),
                        flow_15=shadow_state.flow_15,
                        trade_count=int(shadow_state.flow_15_trade_count or 0),
                        already_emitted=(hard_high_flow_v2_emitted.get(side)==hc.candidate_id),
                    )
                    v2_metrics["flow_capture"]=flow_capture
                    if v2_ready:
                        hard_high_flow_v2_emitted[side]=hc.candidate_id
                        append_jsonl(evlog,{
                            "event":"INTERNAL_HARD120_HIGH_FLOW_V2_SHADOW",
                            "ts_ms":int(ts),
                            "signal_ts_ms":int(sample.get("sample_ts_ms") or ts),
                            "candidate_ts_ms":int(hc.extreme_ts_ms),
                            "candidate_id":hc.candidate_id,
                            "side":"HIGH",
                            "price":float(hc.extreme_price),
                            "mark_price":float(sample.get("mark_price") or price),
                            "teacher":INTERNAL.name,
                            "shadow_contract":"HARD120_HIGH_FLOW_SHADOW_V2",
                            "primary_contract":"INTERNAL_HARD120_CHECKPOINT_V2",
                            "core_flip_authorized":False,
                            "metrics":v2_metrics,
                        })
                        v3_metrics=high_flow_v3_metrics(
                            side="HIGH",
                            candidate_bar_start_ms=(int(hc.extreme_ts_ms)//60_000)*60_000,
                            extreme_price=float(hc.extreme_price),
                            sample_ts_ms=int(sample.get("sample_ts_ms") or ts),
                            completed_m1_rows=completed_m1(state,ts),
                        )
                        v3_ready=bool(v3_metrics.get("ready"))
                        if v3_ready:
                            append_jsonl(evlog,{
                                "event":"INTERNAL_HARD120_HIGH_FLOW_V3_SHADOW",
                                "ts_ms":int(ts),
                                "signal_ts_ms":int(sample.get("sample_ts_ms") or ts),
                                "candidate_ts_ms":int(hc.extreme_ts_ms),
                                "candidate_id":hc.candidate_id,
                                "side":"HIGH",
                                "price":float(hc.extreme_price),
                                "mark_price":float(sample.get("mark_price") or price),
                                "teacher":INTERNAL.name,
                                "shadow_contract":"HARD120_HIGH_FLOW_REGIME_GATE_V3",
                                "parent_shadow_contract":"HARD120_HIGH_FLOW_SHADOW_V2",
                                "primary_contract":"INTERNAL_HARD120_CHECKPOINT_V2",
                                "core_flip_authorized":False,
                                "metrics":v3_metrics,
                            })
                high_flow_v2_live[side]=None if side!="HIGH" else {
                    "candidate_id":hc.candidate_id,
                    "flow_15":None if shadow_state is None else shadow_state.flow_15,
                    "flow_15_trade_count":0 if shadow_state is None else shadow_state.flow_15_trade_count,
                    "emitted":hard_high_flow_v2_emitted.get(side)==hc.candidate_id,
                    "checkpoint":v2_metrics,
                }
                high_flow_v3_live[side]=None if side!="HIGH" else {
                    "candidate_id":hc.candidate_id,
                    "v2_ready":bool(v2_ready),
                    "ready":bool(v3_ready),
                    "checkpoint":v3_metrics,
                }

                high60_sample=None
                high60_confirmed=False
                high60_metrics={"ready":False,"reason":"PRIMARY_HARD120_NOT_EMITTED"}
                if hard_stage and sample is not None and bool(sample.get("fresh_observation")):
                    high60_sample=high60_sample_retrace(
                        side=side,
                        candidate_ts_ms=int(hc.extreme_ts_ms),
                        extreme_price=float(hc.extreme_price),
                        completed_m1_rows=completed_m1(state,ts),
                        observed_ms=int(sample.get("sample_ts_ms") or ts),
                    )
                    high60_confirmed,high60_metrics=high60_primary_confirmed(
                        side=side,sample=high60_sample
                    )
                    high60_metrics["primary_hard120_emitted"]=True
                    high60_metrics["core_flip_authorized"]=False
                    if high60_confirmed:
                        append_jsonl(evlog,{
                            "event":"INTERNAL_HARD120_HIGH60_VETO_STACK_SIGNAL",
                            "ts_ms":int(ts),
                            "signal_ts_ms":int(sample.get("sample_ts_ms") or ts),
                            "candidate_ts_ms":int(hc.extreme_ts_ms),
                            "candidate_id":hc.candidate_id,"side":hc.side,
                            "price":float(hc.extreme_price),
                            "mark_price":float(sample.get("mark_price") or price),
                            "teacher":INTERNAL.name,
                            "shadow_contract":"HARD120_HIGH60_RETRACE_VETO_SHADOW_V1",
                            "primary_contract":"INTERNAL_HARD120_CHECKPOINT_V2",
                            "core_flip_authorized":False,
                            "metrics":high60_metrics,
                        })
                high60_veto_live[side]={
                    "candidate_id":hc.candidate_id,
                    "side":hc.side,
                    "primary_emitted":bool(hard_stage),
                    "confirmed_for_veto_stack":bool(high60_confirmed),
                    "sample":high60_sample,
                    "metrics":high60_metrics,
                }

                persistence_metrics={"ready":False,"reason":"PRIMARY_HARD120_NOT_EMITTED"}
                persistence_ready=False
                if hard_stage and sample is not None and bool(sample.get("fresh_observation")):
                    persistence_metrics=hard120_persistence_metrics(
                        side=side,
                        extreme_price=float(hc.extreme_price),
                        retrace_bps=float(hard_metrics.get("retrace_bps") or 0.0),
                        candidate_ts_ms=int(hc.extreme_ts_ms),
                        sample_ts_ms=int(sample.get("sample_ts_ms") or ts),
                        completed_m1_rows=completed_m1(state,ts),
                    )
                    persistence_ready=bool(persistence_metrics.get("ready"))
                    if persistence_ready:
                        append_jsonl(evlog,{
                            "event":"INTERNAL_HARD120_PERSISTENCE_SHADOW",
                            "ts_ms":int(ts),
                            "signal_ts_ms":int(sample.get("sample_ts_ms") or ts),
                            "candidate_ts_ms":int(hc.extreme_ts_ms),
                            "candidate_id":hc.candidate_id,"side":hc.side,
                            "price":float(hc.extreme_price),
                            "mark_price":float(sample.get("mark_price") or price),
                            "teacher":INTERNAL.name,
                            "shadow_contract":"HARD120_REVERSAL_PERSISTENCE_SHADOW_V1",
                            "primary_contract":"INTERNAL_HARD120_CHECKPOINT_V2",
                            "core_flip_authorized":False,
                            "metrics":persistence_metrics,
                        })
                hard120_persistence_live[side]={
                    "candidate_id":hc.candidate_id,
                    "side":hc.side,
                    "primary_emitted":bool(hard_stage),
                    "shadow_ready":persistence_ready,
                    "metrics":persistence_metrics,
                }

                if hard_stage:
                    hc.emitted=True
                    append_jsonl(evlog,{
                        "event":"INTERNAL_HARD120_SIGNAL",
                        "survival_stage":"HARD120",
                        "ts_ms":int(ts),"signal_ts_ms":int(ts),
                        "candidate_ts_ms":int(hc.extreme_ts_ms),
                        "candidate_id":hc.candidate_id,"side":hc.side,
                        "price":float(hc.extreme_price),
                        "mark_price":float(price),
                        "teacher":INTERNAL.name,
                        "hard_contract":"INTERNAL_HARD120_CHECKPOINT_V2",
                        "core_flip_authorized":False,
                        "metrics":hard_metrics,
                    })

            keep=[]
            for item in pending:
                teacher_name=getattr(item,"teacher_scope",STRICT.name)
                y=teacher_label(state,item,ts)
                if y is None:
                    keep.append(item);continue
                hour=(int(item.extreme_ts_ms)//H)*H
                is_latest=(latest_by_hour.get(f"{item.side}:{hour}")==item.candidate_id)
                y=bool(y and is_latest)
                if teacher_name==INTERNAL.name:
                    model.learn_internal(item.side,item.stage,item.x,y,source="live",
                                         repeat=(4 if y else 1))
                else:
                    model.learn(item.side,item.stage,item.x,y,source="live",
                                repeat=(4 if y else 1))
                append_jsonl(lablog,{"ts_ms":ts,"candidate_id":item.candidate_id,"side":item.side,
                    "stage":item.stage,"label":bool(y),"is_latest_extreme_in_hour":is_latest,
                    "extreme_ts_ms":int(item.extreme_ts_ms),"extreme_price":float(item.extreme_price),
                    "teacher_finalized_ts_ms":int(ts),
                    "teacher":teacher_name,
                    "teacher_role":"TACTICAL" if teacher_name==INTERNAL.name else "CORE",
                    "core_flip_authorized":False if teacher_name==INTERNAL.name else None,
                    "feature_count":len(item.x),
                    "discovery_feature_count":sum(str(k).startswith("discovery__") for k in item.x),
                    "features":item.x})
            pending=keep

            c=candidates.get(expected) if expected else None
            if c is None:
                opts=[z for z in candidates.values() if z is not None]
                c=max(opts,key=lambda z:max(z.probabilities.values(),default=0.0),default=None)
            cov=state.coverage_report()
            forward_first_signal={}
            fsp=args.checkpoint_dir/"FIRST_SIGNAL_FORWARD_STATUS.json"
            if fsp.exists():
                try:forward_first_signal=json.loads(fsp.read_text(encoding="utf-8"))
                except Exception:forward_first_signal={}
            hard120_forward={}
            hsp=args.checkpoint_dir/"HARD120_FORWARD_STATUS.json"
            if hsp.exists():
                try:hard120_forward=json.loads(hsp.read_text(encoding="utf-8"))
                except Exception:hard120_forward={}
            high_flow_shadow_forward={}
            sfp=args.checkpoint_dir/"HARD120_HIGH_FLOW_SHADOW_FORWARD_STATUS.json"
            if sfp.exists():
                try:high_flow_shadow_forward=json.loads(sfp.read_text(encoding="utf-8"))
                except Exception:high_flow_shadow_forward={}
            high_flow_v2_forward={}
            v2fp=args.checkpoint_dir/"HARD120_HIGH_FLOW_V2_FORWARD_STATUS.json"
            if v2fp.exists():
                try:high_flow_v2_forward=json.loads(v2fp.read_text(encoding="utf-8"))
                except Exception:high_flow_v2_forward={}
            hard120_plus_v2_forward={}
            v2cfp=args.checkpoint_dir/"HARD120_PLUS_HIGH_FLOW_V2_FORWARD_STATUS.json"
            if v2cfp.exists():
                try:hard120_plus_v2_forward=json.loads(v2cfp.read_text(encoding="utf-8"))
                except Exception:hard120_plus_v2_forward={}
            high_flow_v3_forward={}
            v3fp=args.checkpoint_dir/"HARD120_HIGH_FLOW_V3_FORWARD_STATUS.json"
            if v3fp.exists():
                try:high_flow_v3_forward=json.loads(v3fp.read_text(encoding="utf-8"))
                except Exception:high_flow_v3_forward={}
            hard120_plus_v3_forward={}
            v3cfp=args.checkpoint_dir/"HARD120_PLUS_HIGH_FLOW_V3_FORWARD_STATUS.json"
            if v3cfp.exists():
                try:hard120_plus_v3_forward=json.loads(v3cfp.read_text(encoding="utf-8"))
                except Exception:hard120_plus_v3_forward={}
            hard120_plus_shadow_forward={}
            cfp=args.checkpoint_dir/"HARD120_PLUS_HIGH_FLOW_FORWARD_STATUS.json"
            if cfp.exists():
                try:hard120_plus_shadow_forward=json.loads(cfp.read_text(encoding="utf-8"))
                except Exception:hard120_plus_shadow_forward={}
            early60_shadow_forward={}
            e60p=args.checkpoint_dir/"EARLY60_STRONG_REVERSAL_FORWARD_STATUS.json"
            if e60p.exists():
                try:early60_shadow_forward=json.loads(e60p.read_text(encoding="utf-8"))
                except Exception:early60_shadow_forward={}
            full_shadow_stack_forward={}
            fssp=args.checkpoint_dir/"EARLY60_PLUS_HARD120_HIGH_FLOW_FORWARD_STATUS.json"
            if fssp.exists():
                try:full_shadow_stack_forward=json.loads(fssp.read_text(encoding="utf-8"))
                except Exception:full_shadow_stack_forward={}
            high60_veto_forward={}
            hvp=args.checkpoint_dir/"HIGH60_VETO_FORWARD_STATUS.json"
            if hvp.exists():
                try:high60_veto_forward=json.loads(hvp.read_text(encoding="utf-8"))
                except Exception:high60_veto_forward={}
            high60_full_stack_forward={}
            hvsp=args.checkpoint_dir/"EARLY60_PLUS_HIGH60_VETO_HIGH_FLOW_FORWARD_STATUS.json"
            if hvsp.exists():
                try:high60_full_stack_forward=json.loads(hvsp.read_text(encoding="utf-8"))
                except Exception:high60_full_stack_forward={}
            persistence_forward={}
            pfp=args.checkpoint_dir/"HARD120_PERSISTENCE_FORWARD_STATUS.json"
            if pfp.exists():
                try:persistence_forward=json.loads(pfp.read_text(encoding="utf-8"))
                except Exception:persistence_forward={}
            persistence_full_stack_forward={}
            pfsp=args.checkpoint_dir/"EARLY60_PLUS_PERSISTENCE_HARD120_HIGH_FLOW_FORWARD_STATUS.json"
            if pfsp.exists():
                try:persistence_full_stack_forward=json.loads(pfsp.read_text(encoding="utf-8"))
                except Exception:persistence_full_stack_forward={}
            status={
                "status":"LEARNING_LIVE" if (model.live_labels or model.internal_live_labels) else "HISTORY_PRETRAINED_LIVE_WATCH",
                "updated_ts_ms":ts,"expected_side":expected,"last_teacher_local":last_teacher,
                "structure_48h":structure_48h,
                "candidate":None if c is None else {
                    "candidate_id":c.candidate_id,"side":c.side,"extreme_price":c.extreme_price,
                    "age_s":round(max(0.0,(ts-c.extreme_ts_ms)/1000.0),1),
                    "probabilities":{str(k):round(v,6) for k,v in c.probabilities.items()},
                    "thresholds":{str(k):model.thresholds[(c.side,k)] for k in STAGES},
                    "internal_probabilities":dict((getattr(c,"evidence",{}) or {}).get("internal_probabilities") or {}),
                    "internal_accepted":dict((getattr(c,"evidence",{}) or {}).get("internal_accepted") or {}),
                    "internal_thresholds":{str(k):model.internal_thresholds[(c.side,k)] for k in STAGES},
                    "internal_ready":{str(k):model.internal_ready(c.side,k) for k in STAGES},
                    "h1_prior":round(model.h1_prior(c.side),6),
                    "evidence":getattr(c,"evidence",{}),
                    "relationship_evidence":(
                        model.relationship_evidence(c.side,max(c.stages_done),c.snapshots[max(c.stages_done)])
                        if c.stages_done else {"supports":[],"contradicts":[],"pairs":[]}
                    ),
                    "stage":"LOCAL_SIGNAL" if 300 in c.stages_done and c.probabilities.get(300,0)>=model.thresholds[(c.side,300)]
                            else "PROBABLE" if 180 in c.stages_done and c.probabilities.get(180,0)>=model.thresholds[(c.side,180)]
                            else "FORMING" if 60 in c.stages_done and c.probabilities.get(60,0)>=model.thresholds[(c.side,60)]
                            else "WATCH"
                },
                "historical_labels":sum(model.labels.values())-model.live_labels,
                "live_labels":model.live_labels,
                "internal_live_labels":model.internal_live_labels,
                "pending_labels":len(pending),
                "teacher_contract":teacher_contract(),
                "hard120_contract":survival_contract(),
                "hard120":hard120_live,
                "hard120_forward":hard120_forward,
                "high60_veto_contract":high60_veto_contract(),
                "high60_veto":high60_veto_live,
                "high60_veto_forward":high60_veto_forward,
                "early60_plus_high60_veto_high_flow_forward":high60_full_stack_forward,
                "hard120_persistence_contract":hard120_persistence_contract(),
                "hard120_persistence":hard120_persistence_live,
                "hard120_persistence_forward":persistence_forward,
                "early60_shadow_contract":early60_shadow_contract(),
                "early60_shadow":early60_shadow_live,
                "early60_shadow_forward":early60_shadow_forward,
                "preferred_high_forward_candidate":"HARD120_PLUS_HIGH_FLOW_V3_SHADOW_FORWARD_ONLY",
                "high_flow_v2_contract":high_flow_v2_contract(),
                "high_flow_v2":high_flow_v2_live,
                "high_flow_v2_forward":high_flow_v2_forward,
                "hard120_plus_high_flow_v2_forward":hard120_plus_v2_forward,
                "high_flow_v3_contract":high_flow_v3_contract(),
                "high_flow_v3":high_flow_v3_live,
                "high_flow_v3_forward":high_flow_v3_forward,
                "hard120_plus_high_flow_v3_forward":hard120_plus_v3_forward,
                "high_flow_shadow_contract":high_flow_shadow_contract(),
                "high_flow_shadow":high_flow_shadow_live,
                "high_flow_shadow_forward":high_flow_shadow_forward,
                "hard120_plus_high_flow_forward":hard120_plus_shadow_forward,
                "early60_plus_hard120_high_flow_forward":full_shadow_stack_forward,
                "early60_plus_persistence_hard120_high_flow_forward":persistence_full_stack_forward,
                "forward_first_signal":forward_first_signal,
                "model_report":model.report(),
                "h1_baseline":model.h1_shadow,
                "h1_training":{"labels":model.h1_labels,"positive":model.h1_positive},
                "seen_input_count":cov.get("seen_input_count"),"feature_contract":cov,
                "discovery_feature_count":(sum(str(k).startswith("discovery__") for k in c.snapshots[max(c.stages_done)]) if c is not None and c.stages_done else 0),
                "last_signal":model.last_signal,
                "mode":"LOCAL_ONLY","local_target":"DUAL_INTERNAL_L3_K1__STRICT_L6_K2",
                "github_run_id":os.getenv("GITHUB_RUN_ID"),"github_sha":os.getenv("GITHUB_SHA"),
                "cortex_state":"RELATIONSHIP_MEMORY_READY",
                "cortex":{},
                "research_only":True,"real_orders":False
            }
            cortex_path=args.checkpoint_dir/"CORTEX_LOCAL_ONLY_STATUS.json"
            if cortex_path.exists():
                try:
                    status["cortex"]=json.loads(cortex_path.read_text(encoding="utf-8"))
                    status["cortex_state"]=status["cortex"].get("state","RELATIONSHIP_MEMORY_READY")
                except Exception:
                    pass

        now=time.time()
        if now>=next_save:
            model.save(mp);save_pickle(fp,state)
            save_pickle(rp,{"candidates":candidates,
                "hard_candidates":{k:(None if v is None else v.to_dict()) for k,v in hard_candidates.items()},
                "hard_high_flow_shadow":{k:(None if v is None else v.to_dict()) for k,v in hard_high_flow_shadow.items()},
                "hard_high_flow_v2_emitted":hard_high_flow_v2_emitted,
                "hard_early60_shadow":{k:(None if v is None else v.to_dict()) for k,v in hard_early60_shadow.items()},
                "pending":[asdict(z) for z in pending],
                "expected_side":expected,"last_teacher_local":last_teacher,
                "latest_by_hour":latest_by_hour,"structure_48h":structure_48h})
            if status:status_path.write_text(json.dumps(status,indent=2)+"\n")
            next_save=now+30
        if now>=next_monitor and status:
            publish_monitor(status);next_monitor=now+10
        if now>=next_issue and status:
            publish_issue(status);next_issue=now+30
        if not events:time.sleep(.5)

    model.save(mp);save_pickle(fp,state)
    save_pickle(rp,{"candidates":candidates,
        "hard_candidates":{k:(None if v is None else v.to_dict()) for k,v in hard_candidates.items()},
        "hard_high_flow_shadow":{k:(None if v is None else v.to_dict()) for k,v in hard_high_flow_shadow.items()},
        "hard_high_flow_v2_emitted":hard_high_flow_v2_emitted,
        "hard_early60_shadow":{k:(None if v is None else v.to_dict()) for k,v in hard_early60_shadow.items()},
        "pending":[asdict(z) for z in pending],
        "expected_side":expected,"last_teacher_local":last_teacher,
        "latest_by_hour":latest_by_hour,"structure_48h":structure_48h})
    if status:
        status_path.write_text(json.dumps(status,indent=2)+"\n");publish_monitor(status);publish_issue(status)
    print("LOCAL_ONLY="+json.dumps(status,separators=(",",":"),ensure_ascii=False),flush=True)

if __name__=="__main__":main()
