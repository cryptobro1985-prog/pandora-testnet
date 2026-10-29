"""Strategy 1 execution from the live executed-trade tape.

H1 local supplies only the permitted side. Exit and re-entry are event driven:
the short/medium aggressor flow must actually change hands. Candle colour,
completed M15 bars, order-book quotes and elapsed-time delays are not gates.
"""
import copy
import math

POLICY = "Caterpillar 1.1 H1-local executed-flow control cycle"


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
    """Executed aggressor pressure aligned to the H1 side.

    Positive means H1-side aggression; negative means counter-side aggression.
    Multiple windows reject a one-print flip while still reacting before M15.
    """
    side = int(side or 0)
    if side not in (-1, 1) or not isinstance(flow, dict) or not flow.get("trade_data_fresh"):
        return None
    age = _f(flow.get("latest_trade_age_seconds"))
    if age is None or not -1 <= age <= 15:
        return None
    values = {}
    for horizon, key in (("15s", "flow_imbalance_15s"),
                         ("30s", "flow_imbalance_30s"),
                         ("60s", "flow_imbalance"),
                         ("300s", "flow_imbalance_300s")):
        raw = _f(flow.get(key))
        values[horizon] = side * raw if raw is not None and -1 <= raw <= 1 else None
    if any(values[h] is None for h in ("15s", "30s", "60s")):
        return None
    c15 = _f(flow.get("trade_count_15s"))
    c30 = _f(flow.get("trade_count_30s"))
    c60 = _f(flow.get("trade_count_60s"))
    b15, s15 = _f(flow.get("buy_volume_15s")), _f(flow.get("sell_volume_15s"))
    b30, s30 = _f(flow.get("buy_volume_30s")), _f(flow.get("sell_volume_30s"))
    active = (c15 is not None and c30 is not None and c60 is not None and
              c15 >= 2 and c30 >= 4 and c60 >= 5 and
              b15 is not None and s15 is not None and b15 + s15 > 0 and
              b30 is not None and s30 is not None and b30 + s30 > 0)
    short, medium, minute = values["15s"], values["30s"], values["60s"]
    values.update(
        active=active,
        event_epoch=_event_epoch(flow),
        counter_takeover=(active and short <= -.15 and medium <= -.10 and
                          (short <= minute - .08 or minute <= -.08)),
        resumed=(active and short >= .18 and medium >= .12 and
                 (short >= minute + .06 or minute >= .08)),
        aligned_control=(active and short >= .12 and medium >= .08),
    )
    return values


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
                aligned_flow_15s=profile["15s"] if profile else None,
                aligned_flow_30s=profile["30s"] if profile else None,
                aligned_flow=profile["60s"] if profile else None,
                event_epoch=profile["event_epoch"] if profile else None)


def initial_entry_candidate(symbol, analysis, m15, flow, stamp):
    """First entry follows a CONFIRMED H1 local, not the later pullback/flow cycle.

    Flow may still be missing or adverse at the turning point. It is used for
    exits and subsequent re-entries, never as a veto on this initial entry.
    The caller separately validates a current tradable mark and available margin.
    """
    data = analysis or {}
    side = int(data.get("entry_side") or 0)
    confirmed = bool(data.get("ready") and data.get("anchor_confirmed") and
                     data.get("h1_direction_anchor") and
                     not data.get("entry_blocked") and side in (-1, 1))
    return dict(symbol=symbol, side=side, eligible=confirmed,
                reason="confirmed_h1_local_initial" if confirmed else
                       "waiting_for_confirmed_h1_local",
                policy=POLICY, entry_trigger="H1_CONFIRMED_LOCAL",
                signal_candle_time=data.get("signal_candle_time"))


def entry_candidate(symbol, analysis, m15, flow, stamp):
    return _candidate(symbol, analysis, flow)


def pressure_exit(position, m15, mark, flow):
    """Exit immediately when executed aggression takes control against H1 side."""
    side = int((position or {}).get("side") or 0)
    profile = flow_profile(flow, side)
    if side not in (-1, 1) or profile is None or not profile["counter_takeover"]:
        return None
    entry, mark = _f((position or {}).get("entry")), _f(mark)
    favorable = side * (mark / entry - 1.0) if entry not in (None, 0) and mark is not None else 0.0
    cost = max(.0002, _f(((position or {}).get("features") or {}).get("estimated_round_trip_cost_move")) or 0.0)
    return "executed_flow_profit_flip_exit" if favorable > cost else "executed_flow_risk_flip_exit"


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
    if ctx.get("phase") != "WAIT_RESUMPTION" or not ctx.get("counter_pressure_seen"):
        return False
    profile = flow_profile(flow, side)
    opposite_epoch = _f(ctx.get("last_opposite_trade_epoch"))
    event_epoch = profile.get("event_epoch") if profile else None
    return bool(profile and profile["resumed"] and event_epoch is not None and
                opposite_epoch is not None and event_epoch > opposite_epoch)
