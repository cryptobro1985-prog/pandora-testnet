"""Strategy 1: H1 direction + pure 5-minute executed buyer/seller control.

H1 local defines the only permitted side. Actual aggressive executed trades over
the rolling 5-minute window decide entry, exit and same-direction re-entry.
No EMA, MACD, M15 candle score, order-book or short-window hard gates are used.
15/30/60 second flow remains telemetry only.
"""
import copy
import math

POLICY = "Caterpillar 1.2 H1-local pure M5 executed-flow control"
CONTROL_DEADBAND = 0.03  # avoid treating an almost 50/50 tape as meaningful control


def _f(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _event_epoch(flow):
    end = _f((flow or {}).get("volume_window_end_epoch"))
    age = _f((flow or {}).get("latest_trade_age_seconds"))
    return end - age if end is not None and age is not None else None


def flow_profile(flow, side):
    """Five-minute executed aggressor pressure aligned to the H1 side.

    Positive = the H1-side aggressors are stronger.
    Negative = the counter-side aggressors are stronger.
    The only strategy input is rolling 300s executed buy/sell flow; shorter
    windows are exposed for diagnostics but never trigger a trade by themselves.
    """
    side = int(side or 0)
    if side not in (-1, 1) or not isinstance(flow, dict) or not flow.get("trade_data_fresh"):
        return None
    age = _f(flow.get("latest_trade_age_seconds"))
    coverage = _f(flow.get("trade_coverage_seconds"))
    raw300 = _f(flow.get("flow_imbalance_300s"))
    count300 = _f(flow.get("trade_count_300s"))
    buy300 = _f(flow.get("buy_volume_300s"))
    sell300 = _f(flow.get("sell_volume_300s"))
    if (age is None or not -1 <= age <= 15 or coverage is None or coverage < 300 or
            raw300 is None or not -1 <= raw300 <= 1 or count300 is None or count300 <= 0 or
            buy300 is None or sell300 is None or buy300 + sell300 <= 0):
        return None

    aligned300 = side * raw300
    price300 = _f(flow.get("price_return_300s"))
    aligned_price = side * price300 if price300 is not None else None
    values = {
        "300s": aligned300,
        "event_epoch": _event_epoch(flow),
        "active": True,
        "aligned_price_300s": aligned_price,
        "price_response_ready": aligned_price is not None,
        "aligned_control": aligned300 >= CONTROL_DEADBAND and aligned_price is not None and aligned_price > 0,
        "counter_takeover": aligned300 <= -CONTROL_DEADBAND and aligned_price is not None and aligned_price < 0,
        "failed_counterflow": aligned300 <= -CONTROL_DEADBAND and aligned_price is not None and aligned_price > 0,
        "resumed": aligned_price is not None and aligned_price > 0 and abs(aligned300) >= CONTROL_DEADBAND,
        "raw_300s": raw300,
        "buy_volume_300s": buy300,
        "sell_volume_300s": sell300,
        "trade_count_300s": count300,
    }
    for horizon, key in (("15s", "flow_imbalance_15s"),
                         ("30s", "flow_imbalance_30s"),
                         ("60s", "flow_imbalance")):
        raw = _f(flow.get(key))
        values[horizon] = side * raw if raw is not None and -1 <= raw <= 1 else None
    return values


def dominance(flow):
    """Current rolling five-minute executed-volume majority."""
    if not isinstance(flow, dict) or not flow.get("trade_data_fresh"):
        return None
    value = _f(flow.get("flow_imbalance_300s"))
    if value is None or not -1 <= value <= 1:
        return None
    return 1 if value > CONTROL_DEADBAND else -1 if value < -CONTROL_DEADBAND else 0


def m15_direction(m15):
    """Compatibility helper only; Strategy 1 never gates on M15."""
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
    reason = ("h1_local_m5_executed_flow_control" if eligible else
              "waiting_for_h1_local" if not h1 else
              "waiting_for_fresh_m5_executed_flow" if profile is None else
              "waiting_for_h1_side_m5_control")
    return dict(symbol=symbol, side=side, eligible=eligible, reason=reason,
                policy=POLICY, dominant_side=dominance(flow),
                aligned_flow_300s=profile["300s"] if profile else None,
                aligned_price_300s=profile["aligned_price_300s"] if profile else None,
                aligned_flow_60s=profile["60s"] if profile else None,
                event_epoch=profile["event_epoch"] if profile else None)


def initial_entry_candidate(symbol, analysis, m15, flow, stamp):
    return _candidate(symbol, analysis, flow)


def entry_candidate(symbol, analysis, m15, flow, stamp):
    return _candidate(symbol, analysis, flow)


def pressure_exit(position, m15, mark, flow):
    """Exit only when counter-side M5 flow is strong AND price actually responds against us."""
    side = int((position or {}).get("side") or 0)
    profile = flow_profile(flow, side)
    if side not in (-1, 1) or profile is None or not profile["counter_takeover"]:
        return None
    entry, mark = _f((position or {}).get("entry")), _f(mark)
    favorable = side * (mark / entry - 1.0) if entry not in (None, 0) and mark is not None else 0.0
    return "m5_flow_profit_flip_exit" if favorable > 0 else "m5_flow_risk_flip_exit"


def update_watch(watch, mark, m15, flow, stamp):
    """After exit, wait for the same M5 flow to flip back toward the H1 side."""
    out = copy.deepcopy(watch or {})
    side = int(out.get("side") or 0)
    mark = _f(mark)
    if side not in (-1, 1) or mark is None:
        return out
    ctx = out.setdefault("context", {})
    ctx.update(last_observed_epoch=_f(stamp), policy=POLICY)
    profile = flow_profile(flow, side)
    if profile:
        ctx.update(flow_300s=profile["300s"], flow_60s=profile["60s"],\n                   aligned_price_300s=profile["aligned_price_300s"],\n                   failed_counterflow=profile["failed_counterflow"])
        if profile["counter_takeover"]:
            ctx["counter_pressure_seen"] = True
            ctx["phase"] = "WAIT_RESUMPTION"
            ctx["last_opposite_trade_epoch"] = profile["event_epoch"]
        elif not ctx.get("counter_pressure_seen"):
            ctx["phase"] = "WAIT_COUNTER_CONTROL"
    return out


def reentry_ready(side, m15, mark, watch, flow, stamp):
    """Re-enter when price resumes the H1 direction and M5 flow confirms or fails against it."""
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
