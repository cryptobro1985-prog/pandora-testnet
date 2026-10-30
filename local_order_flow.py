"""Strategy 1 execution from the live executed-trade tape.

H1 local supplies only the permitted side. Exit and re-entry are event driven:
the short/medium aggressor flow must actually change hands. Candle colour,
completed M15 bars, order-book quotes and elapsed-time delays are not gates.
"""
import copy
import math

POLICY = "Caterpillar 1.2 H1-local 15s/30s/60s executed-flow control cycle"


def _f(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _event_epoch(flow):
    """Epoch of the newest real trade, not merely the time we sampled the tape."""
    end = _f((flow or {}).get("volume_window_end_epoch"))
    age = _f((flow or {}).get("latest_trade_age_seconds"))
    return end - age if end is not None and age is not None else None


def flow_profile(flow, side):
    """Fast causal 15s/30s/60s executed-flow state.

    H1 owns direction. 15s detects transfer first, 30s confirms it and 60s
    supplies context. A very strong 15s transfer may exit immediately when
    there is enough real executed liquidity; M3/M5 never gate execution.
    """
    side = int(side or 0)
    if side not in (-1, 1) or not isinstance(flow, dict) or not flow.get("trade_data_fresh"):
        return None
    age = _f(flow.get("latest_trade_age_seconds"))
    if age is None or not -1 <= age <= 15:
        return None
    vals = {}
    for horizon, key in (("15s","flow_imbalance_15s"),("30s","flow_imbalance_30s"),("60s","flow_imbalance")):
        raw = _f(flow.get(key))
        vals[horizon] = side * raw if raw is not None and -1 <= raw <= 1 else None
    if vals["60s"] is None:
        return None
    if vals["15s"] is None: vals["15s"] = vals["60s"]
    if vals["30s"] is None: vals["30s"] = vals["60s"]
    c15=_f(flow.get("trade_count_15s")); c30=_f(flow.get("trade_count_30s")); c60=_f(flow.get("trade_count_60s"))
    notional=_f(flow.get("observed_notional_60s"))
    active=bool(c60 is not None and c60 >= 5 and notional is not None and notional >= 100)
    fast_counter=bool(active and c15 is not None and c15 >= 3 and vals["15s"] <= -.35)
    confirmed_counter=bool(active and vals["15s"] <= -.12 and vals["30s"] <= -.08)
    vals.update(
        active=active,event_epoch=_event_epoch(flow),
        counter_takeover=bool(fast_counter or confirmed_counter),
        weakening=bool(active and vals["15s"] < .02 and vals["30s"] < .06 and vals["15s"] <= vals["60s"]-.08),
        resumed=bool(active and vals["15s"] >= .16 and vals["30s"] >= .12 and vals["60s"] >= .08),
        aligned_control=bool(active and vals["15s"] >= .12 and vals["30s"] >= .08 and vals["60s"] >= .06),
        observed_notional_60s=notional,
    )
    return vals

def dominance(flow):
    """Current 60-second executed-volume majority; diagnostic compatibility."""
    if not isinstance(flow, dict) or not flow.get("trade_data_fresh"):
        return None
    value = _f(flow.get("flow_imbalance"))
    return None if value is None or not -1 <= value <= 1 else (1 if value > 0 else -1 if value < 0 else 0)


def m15_direction(m15):
    """Dashboard-only compatibility helper; never gates Strategy 1 execution."""
    if not isinstance(m15, dict) or not m15.get("ready"):
        return None
    ret = _f(m15.get("return_15m"))
    if ret is not None and ret != 0:
        return 1 if ret > 0 else -1
    candle = int(m15.get("candle_direction") or 0)
    return candle if candle in (-1, 1) else None


def _candidate(symbol, analysis, flow):
    side = int((analysis or {}).get("entry_side") or 0)
    h1 = bool((analysis or {}).get("ready") and
              (analysis or {}).get("h1_direction_anchor") and
              not (analysis or {}).get("entry_blocked") and side in (-1, 1))
    profile = flow_profile(flow, side)
    eligible = bool(h1 and profile and profile["aligned_control"])
    reason = ("h1_local_executed_flow_control" if eligible else
              "waiting_for_h1_local" if not h1 else
              "waiting_for_fresh_executed_flow" if profile is None or not profile["active"] else
              "waiting_for_h1_side_aggressor_control")
    return dict(symbol=symbol, side=side, eligible=eligible, reason=reason,
                policy=POLICY, dominant_side=dominance(flow),
                aligned_flow=profile["60s"] if profile else None,
                aligned_flow_15s=profile["15s"] if profile else None,
                aligned_flow_30s=profile["30s"] if profile else None,
                aligned_flow_60s=profile["60s"] if profile else None,
                event_epoch=profile["event_epoch"] if profile else None)


def initial_entry_candidate(symbol, analysis, m15, flow, stamp):
    """Initial entry requires confirmed H1 direction plus live-side resumption.

    A confirmed H1 local is directional context, not permission to enter blindly.
    M15 is observational only and never vetoes H1 plus fresh 15s/30s/60s
    executed flow aligned with the H1 side. This mirrors the caterpillar rule:
    wait through the pullback, then enter when the pullback weakens and control
    returns toward the active H1 regime.
    """
    data = analysis or {}
    side = int(data.get("entry_side") or 0)
    confirmed = bool(data.get("ready") and data.get("anchor_confirmed") and
                     data.get("h1_direction_anchor") and
                     not data.get("entry_blocked") and side in (-1, 1))
    if not confirmed:
        return dict(symbol=symbol, side=side, eligible=False,
                    reason="waiting_for_confirmed_h1_local", policy=POLICY,
                    entry_trigger="H1_CONFIRMED_LOCAL_PLUS_FLOW",
                    signal_candle_time=data.get("signal_candle_time"))
    candidate = _candidate(symbol, data, flow)
    candidate.update(entry_trigger="H1_CONFIRMED_LOCAL_PLUS_FLOW",
                     signal_candle_time=data.get("signal_candle_time"))
    return candidate


def entry_candidate(symbol, analysis, m15, flow, stamp):
    return _candidate(symbol, analysis, flow)


def pressure_exit(position, m15, mark, flow):
    """Exit immediately when fresh opposite executed flow takes control.

    PnL never vetoes a genuine takeover. For bankable MFE, weakening plus
    negative fast flow also protects the excursion before a full 60s flip.
    """
    side=int((position or {}).get("side") or 0)
    profile=flow_profile(flow,side)
    if side not in (-1,1) or profile is None or not profile["active"]:
        return None
    entry,mark=_f((position or {}).get("entry")),_f(mark)
    if entry in (None,0) or mark is None:return None
    favorable=side*(mark/entry-1.0)
    features=(position or {}).get("features") or {}
    peak=max(0.0,_f(features.get("mfe_price_move")) or 0.0,favorable)
    cost=max(.0002,_f(features.get("estimated_round_trip_cost_move")) or 0.0)
    bankable=peak>=max(cost*1.5,.0015)
    if profile["counter_takeover"]:
        return "executed_flow_15s30s_counter_control_exit"
    if bankable and profile["weakening"] and profile["15s"] < 0:
        return "executed_flow_15s30s_mfe_weakening_exit"
    return None

def update_watch(watch, mark, m15, flow, stamp):
    """Persist counter-control and wait for a later mirrored takeover."""
    out = copy.deepcopy(watch or {})
    side = int(out.get("side") or 0)
    mark = _f(mark)
    if side not in (-1, 1) or mark is None:
        return out
    ctx = out.setdefault("context", {})
    extreme = _f(ctx.get("pullback_extreme"))
    if extreme is None:
        extreme = _f(out.get("exit_price")) or mark
    extreme = min(extreme, mark) if side > 0 else max(extreme, mark)
    ctx.update(pullback_extreme=extreme, last_observed_epoch=_f(stamp), policy=POLICY)
    profile = flow_profile(flow, side)
    if profile:
        ctx.update(flow_15s=profile["15s"], flow_30s=profile["30s"], flow_60s=profile["60s"])
        if profile["counter_takeover"]:
            ctx["counter_pressure_seen"] = True
            ctx["phase"] = "WAIT_RESUMPTION"
            ctx["last_opposite_trade_epoch"] = profile["event_epoch"]
        elif not ctx.get("counter_pressure_seen"):
            ctx["phase"] = "WAIT_COUNTER_CONTROL"
    return out


def reentry_ready(side, m15, mark, watch, flow, stamp):
    """Re-enter only on a later executed-flow takeover back toward the H1 side."""
    side = int(side or 0)
    if side not in (-1, 1) or not watch or int(watch.get("side") or 0) != side:
        return False
    ctx = watch.get("context") or {}
    # Continuation is valid even when no counter-side takeover or pullback occurred.
    # The pullback branch below still requires its own confirmed control reversal.
    profile = flow_profile(flow, side)
    opposite_epoch = _f(ctx.get("last_opposite_trade_epoch"))
    event_epoch = profile.get("event_epoch") if profile else None
    # A price response from the observed pullback low/high is also required.
    # A brief buying burst while price is still falling is not a long re-entry.
    price = _f(mark)
    extreme = _f(ctx.get("pullback_extreme"))
    price_recovered = (price is not None and extreme is not None and extreme > 0
                       and side * (price / extreme - 1.0) >= .0005)
    recovered_after_pullback = bool(profile and profile["resumed"] and price_recovered and
                                    event_epoch is not None and opposite_epoch is not None and
                                    event_epoch > opposite_epoch)
    if ctx.get("phase") == "WAIT_RESUMPTION" and ctx.get("counter_pressure_seen") and recovered_after_pullback:
        return True
    # A profit-taking exit can be followed by uninterrupted directional strength.
    # Do not require counter-side takeover in that case; require a NEW executed
    # trade after the exit, multihorizon dominance and an actual price advance.
    exit_epoch = _f(watch.get("exit_epoch"))
    if exit_epoch is None:
        try:
            import datetime
            exit_epoch = datetime.datetime.fromisoformat(str(watch.get("exit_at")).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError, OverflowError):
            return False
    exit_price = _f(watch.get("exit_price"))
    continuation = bool(
        profile and profile["resumed"] and profile["aligned_control"]
        and event_epoch is not None and event_epoch > exit_epoch
        and price is not None and exit_price is not None and exit_price > 0
        and side * (price / exit_price - 1.0) >= .0005
        and _f(ctx.get("last_observed_epoch")) is not None
        and 0 <= stamp - _f(ctx["last_observed_epoch"]) <= 15
    )
    return continuation
