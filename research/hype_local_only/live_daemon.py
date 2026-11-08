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
    INTERNAL, STRICT, matured_pivot_label, teacher_contract,
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

def strict_pivots(state,ts_ms):
    rows=completed_h1(state,ts_ms);raw=[]
    for i in range(6,len(rows)-2):
        row=rows[i];past=rows[i-6:i];future=rows[i+1:i+3];win=rows[i-6:i+3]
        if any(b["start_ms"]!=a["start_ms"]+H for a,b in zip(win,win[1:])):continue
        hi=row["high"]>max(z["high"] for z in past) and row["high"]>=max(z["high"] for z in future)
        lo=row["low"]<min(z["low"] for z in past) and row["low"]<=min(z["low"] for z in future)
        if hi==lo:continue
        side="HIGH" if hi else "LOW";price=row["high"] if hi else row["low"]
        item={"side":side,"price":price,"hour_ms":row["start_ms"],"available_ms":row["start_ms"]+3*H}
        if raw and raw[-1]["side"]==side:
            better=price>raw[-1]["price"] if side=="HIGH" else price<raw[-1]["price"]
            if better:raw[-1]=item
        else:raw.append(item)
    return raw

def structural_replay_48h(state,ts_ms):
    """Recover the confirmed H1 Local sequence for the last 48h.

    Uses only pivots whose K2 confirmation was already available at ts_ms.
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
    return matured_pivot_label(
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
    rt=load_pickle(rp,{"candidates":{"LOW":None,"HIGH":None},"pending":[],"expected_side":None,
                       "last_teacher_local":None,"latest_by_hour":{},"structure_48h":{}})
    candidates=rt.get("candidates") or {"LOW":None,"HIGH":None}
    pending=[Pending(**z) if isinstance(z,dict) else z for z in rt.get("pending",[])]
    expected=rt.get("expected_side");last_teacher=rt.get("last_teacher_local")
    latest_by_hour=rt.get("latest_by_hour") or {}
    structure_48h=rt.get("structure_48h") or {}

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

            # H1 baseline learns every matured Local in the backfill/live history.
            model.train_h1_history(state,ts)

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
                    evidence={"proposal":"MULTIWINDOW_CAUSAL","windows":[n for n,_ in hit]}
                    c=Candidate(side,float(price),int(ts),f"{side[0]}-{ts}",evidence=evidence)
                    candidates[side]=c
                    hour=(int(ts)//H)*H
                    latest_by_hour[f"{side}:{hour}"]=c.candidate_id
                    append_jsonl(evlog,{"event":"NEW_CANDIDATE","ts_ms":ts,"side":side,"price":price,
                        "candidate_id":c.candidate_id,"evidence":evidence})

            for side in ("LOW","HIGH"):
                c=candidates.get(side)
                if c is None or c.invalidated:continue
                age=max(0.0,(ts-c.extreme_ts_ms)/1000.0)
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
            status={
                "status":"LEARNING_LIVE" if model.live_labels else "HISTORY_PRETRAINED_LIVE_WATCH",
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
            save_pickle(rp,{"candidates":candidates,"pending":[asdict(z) for z in pending],
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
    save_pickle(rp,{"candidates":candidates,"pending":[asdict(z) for z in pending],
        "expected_side":expected,"last_teacher_local":last_teacher,
        "latest_by_hour":latest_by_hour,"structure_48h":structure_48h})
    if status:
        status_path.write_text(json.dumps(status,indent=2)+"\n");publish_monitor(status);publish_issue(status)
    print("LOCAL_ONLY="+json.dumps(status,separators=(",",":"),ensure_ascii=False),flush=True)

if __name__=="__main__":main()
