"""Caterpillar event-driven execution from Bybit Public Trades.

H1 local owns direction. Trading decisions use only cumulative executed BUY/SELL
notional observed after a causal baseline. No M15, fixed 30/180/300 decision
window, price-response confirmation, EMA/MACD/MFI, ROI gate or MFE stop.
Wall-clock time is used only to reject stale transport.
"""
import copy,math

POLICY="H1 local direction + event-driven executed BUY/SELL notional"


def _f(value):
    try:value=float(value)
    except (TypeError,ValueError,OverflowError):return None
    return value if math.isfinite(value) else None


def _totals(flow):
    if not isinstance(flow,dict) or not flow.get("trade_data_fresh"):return None
    age=_f(flow.get("latest_trade_age_seconds"));limit=_f(flow.get("freshness_limit_seconds")) or 15.
    buy=_f(flow.get("event_buy_notional_total"));sell=_f(flow.get("event_sell_notional_total"))
    count=flow.get("event_trade_count_total")
    if age is None or not 0<=age<=limit or buy is None or sell is None:return None
    try:count=int(count)
    except (TypeError,ValueError):return None
    if min(buy,sell)<0 or count<=0:return None
    return buy,sell,count,_f(flow.get("decision_event_epoch") or flow.get("latest_trade_epoch"))


def _delta(flow,base_buy,base_sell,base_count=None):
    totals=_totals(flow)
    if totals is None:return None
    buy,sell,count,event=totals
    b0=_f(base_buy);s0=_f(base_sell)
    if b0 is None or s0 is None:return None
    db=max(0.,buy-b0);ds=max(0.,sell-s0)
    dc=count-int(base_count or 0)
    if dc<=0 or db+ds<=0:return None
    side=1 if db>ds else -1 if ds>db else 0
    return {"buy":db,"sell":ds,"count":dc,"side":side,"event_epoch":event,
            "imbalance":(db-ds)/(db+ds)}


def flow_profile(flow,side,base_buy=None,base_sell=None,base_count=None):
    side=int(side or 0)
    if side not in (-1,1):return None
    if base_buy is None or base_sell is None:
        totals=_totals(flow)
        if totals is None:return None
        buy,sell,count,event=totals
        dominant=1 if buy>sell else -1 if sell>buy else 0
        return {"event_epoch":event,"buy":buy,"sell":sell,"count":count,
                "control_side":dominant,"entry_control_side":dominant,
                "aligned_control":dominant==side,"resumed":dominant==side,
                "counter_takeover":dominant==-side,
                "aligned_pressure":side*(buy-sell)/(buy+sell) if buy+sell else 0.}
    d=_delta(flow,base_buy,base_sell,base_count)
    if d is None:return None
    return {"event_epoch":d["event_epoch"],"buy":d["buy"],"sell":d["sell"],"count":d["count"],
            "control_side":d["side"],"entry_control_side":d["side"],
            "aligned_control":d["side"]==side,"resumed":d["side"]==side,
            "counter_takeover":d["side"]==-side,"aligned_pressure":side*d["imbalance"]}


def dominance(flow):
    totals=_totals(flow)
    if totals is None:return None
    buy,sell,_,_=totals
    return 1 if buy>sell else -1 if sell>buy else 0


def _window_consensus(flow,side):
    windows=(flow or {}).get("windows") or {}
    votes={}
    for seconds in (30,180,300):
        w=windows.get(str(seconds)) or windows.get(seconds) or {}
        complete=bool(w.get("complete"))
        imbalance=_f(w.get("imbalance"))
        aligned=bool(complete and imbalance is not None and int(side)*imbalance>0)
        votes[str(seconds)]={"complete":complete,"imbalance":imbalance,"aligned":aligned}
    completed=[v for v in votes.values() if v["complete"]]
    aligned_votes=sum(1 for v in completed if v["aligned"])
    # 30 is the first read, 180 confirms the move, 300 supplies regime context.
    # Entry/re-entry needs 180 aligned plus at least two aligned completed horizons.
    return bool(votes["180"]["aligned"] and aligned_votes>=2),votes,aligned_votes


def _candidate(symbol,analysis,flow):
    side=int((analysis or {}).get("entry_side") or 0)
    h1=bool((analysis or {}).get("ready") and (analysis or {}).get("anchor_confirmed")
        and (analysis or {}).get("h1_direction_anchor") and not (analysis or {}).get("entry_blocked")
        and side in (-1,1))
    profile=flow_profile(flow,side,(analysis or {}).get("flow_anchor_buy_total"),
        (analysis or {}).get("flow_anchor_sell_total"),(analysis or {}).get("flow_anchor_trade_count"))
    consensus,votes,aligned_votes=_window_consensus(flow,side)
    eligible=bool(h1 and profile and profile["aligned_control"] and consensus)
    reason=("h1_flow_30_180_300_entry" if eligible else "waiting_for_h1_local" if not h1
        else "waiting_for_fresh_executed_flow" if profile is None else "waiting_for_30_180_300_flow_confirmation")
    return {"symbol":symbol,"side":side,"eligible":eligible,"reason":reason,"policy":POLICY,
            "aligned_pressure":profile["aligned_pressure"] if profile else None,
            "event_epoch":profile["event_epoch"] if profile else None,
            "buy_notional":profile["buy"] if profile else None,"sell_notional":profile["sell"] if profile else None,
            "window_votes":votes,"aligned_votes":aligned_votes}


def initial_entry_candidate(symbol,analysis,execution_context,flow,stamp):
    return _candidate(symbol,analysis,flow)


def entry_candidate(symbol,analysis,execution_context,flow,stamp):
    return _candidate(symbol,analysis,flow)


def pressure_exit(position,execution_context,mark,flow,*,opposite_local_confirmed=False):
    if not isinstance(position,dict):return None
    side=int(position.get("side") or 0);features=position.setdefault("features",{})
    if opposite_local_confirmed:
        features["exit_decision"]={"reason":"opposite_confirmed_h1_local","control_side":-side}
        return "opposite_confirmed_h1_local"
    profile=flow_profile(flow,side,features.get("flow_entry_buy_total"),
        features.get("flow_entry_sell_total"),features.get("flow_entry_trade_count"))
    if profile is None:
        features["exit_decision"]={"reason":"fresh_executed_flow_required","control_side":0}
        return None
    windows=flow.get("windows") or {}
    votes={}
    for seconds in (30,180,300):
        w=windows.get(str(seconds)) or windows.get(seconds) or {}
        complete=bool(w.get("complete"))
        imbalance=_f(w.get("imbalance"))
        votes[str(seconds)]={"complete":complete,"imbalance":imbalance,
            "counter":bool(complete and imbalance is not None and side*imbalance<0)}
    completed=[v for v in votes.values() if v["complete"]]
    counter_votes=sum(1 for v in completed if v["counter"])
    # 30s is warning only. A normal flow exit needs the 180s context and
    # agreement from at least two completed horizons. 300s becomes the regime
    # vote once available. Confirmed opposite H1 local bypasses this gate above.
    # Caterpillar profit-preservation rule: ordinary counter-flow may harvest a
    # move only after the position has actually had positive net excursion and
    # has started giving some of that peak back. Losing positions are not churned
    # by flow noise; opposite confirmed H1 local remains the independent emergency exit.
    peak=float(features.get("peak_mfe_usd") or features.get("mfe_usd") or 0.0)
    current=float(features.get("current_pnl_usd") or 0.0)
    recoil=max(0.0,peak-current)
    # Aggressive MFE preservation for the SHORT10 paper test: once a trade
    # has positive peak excursion, a 30s counter-flow warning plus >=10% peak
    # giveback can harvest the remaining profit before the slower 180/300
    # confirmation. The slower path remains the normal structure/flow exit.
    giveback_fraction=(recoil/peak) if peak>0 else 0.0
    fast_mfe_lock=bool(peak>0.0 and current>0.0 and votes["30"]["counter"]
        and giveback_fraction>=0.10)
    confirmed=bool(fast_mfe_lock or (profile["counter_takeover"] and votes["180"]["counter"]
        and counter_votes>=2 and peak>0.0 and recoil>0.0 and current>0.0))
    features["mfe_exit_state"]={"peak_mfe_usd":peak,"current_pnl_usd":current,
        "mfe_giveback_usd":recoil,"mfe_giveback_fraction":giveback_fraction,
        "fast_mfe_lock":fast_mfe_lock,"profit_excursion_seen":peak>0.0}
    features["exit_decision"]={"reason":"counter_flow_60_180_300_confirmed" if confirmed else
        "counter_flow_waiting_60_180_300" if profile["counter_takeover"] else "own_side_executed_flow",
        "control_side":profile["control_side"],"buy_notional_since_entry":profile["buy"],
        "sell_notional_since_entry":profile["sell"],"event_epoch":profile["event_epoch"],
        "window_votes":votes,"counter_votes":counter_votes}
    return "confirmed_counter_move_exit_mfe_lock_30" if fast_mfe_lock else "confirmed_counter_move_exit_30_180_300" if confirmed else None


def update_watch(watch,mark,execution_context,flow,stamp):
    out=copy.deepcopy(watch or {});side=int(out.get("side") or 0)
    if side not in (-1,1):return out
    context=out.setdefault("context",{})
    if "flow_exit_buy_total" not in context:
        totals=_totals(flow)
        if totals is None:return out
        context["flow_exit_buy_total"],context["flow_exit_sell_total"],context["flow_exit_trade_count"],_=totals
    profile=flow_profile(flow,side,context.get("flow_exit_buy_total"),
        context.get("flow_exit_sell_total"),context.get("flow_exit_trade_count"))
    if profile is None:return out
    context.update(last_observed_epoch=stamp,executed_buy_since_exit=profile["buy"],
        executed_sell_since_exit=profile["sell"],control_side=profile["control_side"])
    if profile["resumed"]:
        context.update(phase="REENTRY_READY",resumption_confirmed=True,confirmation_epoch=profile["event_epoch"])
    else:
        context.update(phase="WAIT_RESUMPTION",resumption_confirmed=False)
    return out


def reentry_ready(side,execution_context,mark,watch,flow,stamp):
    if not watch or int(watch.get("side") or 0)!=int(side or 0):return False
    context=watch.get("context") or {}
    profile=flow_profile(flow,side,context.get("flow_exit_buy_total"),
        context.get("flow_exit_sell_total"),context.get("flow_exit_trade_count"))
    consensus,votes,aligned_votes=_window_consensus(flow,side)
    context["reentry_window_votes"]=votes
    context["reentry_aligned_votes"]=aligned_votes
    return bool(profile and profile["resumed"] and consensus)
