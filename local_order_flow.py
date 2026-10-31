"""Strategy 1 execution from live Bybit Public Trades.

The confirmed H1 local defines the permitted direction. Entries, exits and
re-entries are driven by executed buyer/seller control on M1/M3/M5 windows.
MFE is recorded continuously for audit; it is never a fixed TP or standalone
exit trigger. The strategy closes when fresh M1 executed control transfers
against the position and re-enters only after real opposite pressure was seen
and H1-aligned M1/M3/M5 control resumes.
"""
import copy, math
POLICY = "Caterpillar H1-local pure M1/M3/M5 buyer-seller control"

def _f(value):
    try: value=float(value)
    except (TypeError,ValueError,OverflowError): return None
    return value if math.isfinite(value) else None

def _event_epoch(flow):
    return _f((flow or {}).get("decision_event_epoch") or (flow or {}).get("volume_window_end_epoch") or (flow or {}).get("latest_trade_epoch"))

def flow_profile(flow, side):
    side=int(side or 0)
    if side not in (-1,1) or not isinstance(flow,dict) or not flow.get("trade_data_fresh"): return None
    age=_f(flow.get("latest_trade_age_seconds"))
    if age is None or age < -1 or age > 15: return None
    raw60=_f(flow.get("flow_imbalance")); raw180=_f(flow.get("flow_imbalance_180s")); raw300=_f(flow.get("flow_imbalance_300s"))
    price300=_f(flow.get("price_return_300s")); coverage=_f(flow.get("trade_coverage_seconds")) or 0.0
    if raw60 is None or not -1 <= raw60 <= 1: return None
    m1=side*raw60; m3=side*raw180 if raw180 is not None and -1<=raw180<=1 else None; m5=side*raw300 if raw300 is not None and -1<=raw300<=1 else None
    price5=side*price300 if price300 is not None else None
    m3_ready=bool(coverage>=180 and m3 is not None); m5_ready=bool(coverage>=300 and m5 is not None)
    aligned=[m1]
    if m3_ready: aligned.append(m3)
    if m5_ready: aligned.append(m5)
    direct=bool(aligned and all(x>0 for x in aligned)); counter=bool(m1<0)
    return {"active":True,"event_epoch":_event_epoch(flow),"coverage_seconds":coverage,
            "m1":m1,"m3":m3,"m5":m5,"price5":price5,"m3_ready":m3_ready,"m5_ready":m5_ready,
            "direct_control":direct,"aligned_control":direct,"counter_takeover":counter,
            "absorbed_counter":False,"fast_counter":counter,"fast_aligned":direct,"resumed":direct}

def dominance(flow):
    if not isinstance(flow,dict) or not flow.get("trade_data_fresh"): return None
    value=_f(flow.get("flow_imbalance"))
    return None if value is None or not -1<=value<=1 else (1 if value>0 else -1 if value<0 else 0)

def _candidate(symbol,analysis,flow):
    side=int((analysis or {}).get("entry_side") or 0)
    h1=bool((analysis or {}).get("ready") and (analysis or {}).get("anchor_confirmed") and
            (analysis or {}).get("h1_direction_anchor") and not (analysis or {}).get("entry_blocked") and side in (-1,1))
    profile=flow_profile(flow,side); eligible=bool(h1 and profile and profile["aligned_control"])
    reason=("h1_local_m1_m3_m5_executed_control" if eligible else "waiting_for_h1_local" if not h1 else
            "waiting_for_fresh_executed_flow" if profile is None else "waiting_for_h1_side_m1_m3_m5_control")
    return {"symbol":symbol,"side":side,"eligible":eligible,"reason":reason,"policy":POLICY,
            "dominant_side":dominance(flow),"aligned_flow_60s":profile["m1"] if profile else None,
            "aligned_flow_180s":profile["m3"] if profile else None,"aligned_flow_300s":profile["m5"] if profile else None,
            "aligned_price_return_300s":profile["price5"] if profile else None,"m3_ready":profile["m3_ready"] if profile else False,
            "m5_ready":profile["m5_ready"] if profile else False,"absorbed_counter":False,
            "event_epoch":profile["event_epoch"] if profile else None}

def initial_entry_candidate(symbol,analysis,execution_context,flow,stamp): return _candidate(symbol,analysis,flow)

def entry_candidate(symbol,analysis,execution_context,flow,stamp):
    base=_candidate(symbol,analysis,flow); side=int((analysis or {}).get("entry_side") or 0); profile=flow_profile(flow,side)
    h1=bool((analysis or {}).get("ready") and (analysis or {}).get("anchor_confirmed") and
            (analysis or {}).get("h1_direction_anchor") and not (analysis or {}).get("entry_blocked") and side in (-1,1))
    base["eligible"]=bool(h1 and profile and profile["resumed"])
    if base["eligible"]: base["reason"]="h1_local_m1_m3_m5_direct_reentry"
    return base

def pressure_exit(position,execution_context,mark,flow):
    side=int((position or {}).get("side") or 0); entry=_f((position or {}).get("entry")); mark=_f(mark); profile=flow_profile(flow,side)
    if side not in (-1,1) or entry is None or entry<=0 or mark is None or profile is None:return None
    return "executed_flow_m1_opposite_control_exit" if profile["counter_takeover"] else None

def update_watch(watch,mark,execution_context,flow,stamp):
    out=copy.deepcopy(watch or {}); side=int(out.get("side") or 0); mark=_f(mark)
    if side not in (-1,1) or mark is None:return out
    ctx=out.setdefault("context",{}); extreme=_f(ctx.get("pullback_extreme"))
    if extreme is None: extreme=_f(out.get("exit_price")) or mark
    extreme=min(extreme,mark) if side>0 else max(extreme,mark)
    ctx.update(pullback_extreme=extreme,last_observed_epoch=_f(stamp),policy=POLICY)
    profile=flow_profile(flow,side)
    if profile:
        ctx.update(flow_m1=profile["m1"],flow_m3=profile["m3"],flow_m5=profile["m5"],price_m5=profile["price5"],
                   m3_ready=profile["m3_ready"],m5_ready=profile["m5_ready"],absorbed_counter=False)
        if profile["fast_counter"]:
            ctx["counter_pressure_seen"]=True;ctx["phase"]="WAIT_RESUMPTION";ctx["last_opposite_trade_epoch"]=profile["event_epoch"]
        elif not ctx.get("counter_pressure_seen"):ctx["phase"]="WAIT_COUNTER_CONTROL"
    return out

def reentry_ready(side,execution_context,mark,watch,flow,stamp):
    side=int(side or 0)
    if side not in (-1,1) or not watch or int(watch.get("side") or 0)!=side:return False
    ctx=watch.get("context") or {}
    if ctx.get("phase")!="WAIT_RESUMPTION" or not ctx.get("counter_pressure_seen"):return False
    profile=flow_profile(flow,side); opposite=_f(ctx.get("last_opposite_trade_epoch")); event=profile.get("event_epoch") if profile else None
    return bool(profile and profile["resumed"] and event is not None and opposite is not None and event>opposite)
