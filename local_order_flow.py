"""Strategy 1 execution from live executed trades.

The confirmed H1 local defines the permitted direction. Entries, exits and
re-entries are driven by executed buyer/seller control on M1/M3/M5 windows.
MFE is not an entry signal; it is used only to preserve an already-earned move
when short-term control transfers against the position.
"""
import copy
import math

POLICY = "Caterpillar H1-local M1/M3/M5 executed-flow + MFE preservation"


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
    """Return executed-flow control aligned to the active H1 side.

    Positive aligned values mean the H1 side is the aggressor. Negative values
    mean the opposite side is the aggressor. A price move that remains aligned
    despite opposite aggression is treated as absorption, not as a reversal.
    """
    side = int(side or 0)
    if side not in (-1, 1) or not isinstance(flow, dict) or not flow.get("trade_data_fresh"):
        return None
    age = _f(flow.get("latest_trade_age_seconds"))
    if age is None or age < -1 or age > 15:
        return None

    raw60 = _f(flow.get("flow_imbalance"))
    raw180 = _f(flow.get("flow_imbalance_180s"))
    raw300 = _f(flow.get("flow_imbalance_300s"))
    price300 = _f(flow.get("price_return_300s"))
    coverage = _f(flow.get("trade_coverage_seconds")) or 0.0
    if raw60 is None or not -1 <= raw60 <= 1:
        return None

    m1 = side * raw60
    m3 = side * raw180 if raw180 is not None and -1 <= raw180 <= 1 else None
    m5 = side * raw300 if raw300 is not None and -1 <= raw300 <= 1 else None
    price5 = side * price300 if price300 is not None else None
    m3_ready = bool(coverage >= 180 and m3 is not None)
    m5_ready = bool(coverage >= 300 and m5 is not None and price5 is not None)

    direct_control = bool(m5_ready and m1 > 0 and m3 > 0 and m5 > 0 and price5 > 0)
    counter_takeover = bool(m5_ready and m1 < 0 and m3 < 0 and m5 < 0 and price5 < 0)
    absorbed_counter = bool(m5_ready and m1 < 0 and m3 < 0 and m5 < 0 and price5 > 0)
    fast_counter = bool(m3_ready and m1 < 0 and m3 < 0)
    fast_aligned = bool(m3_ready and m1 > 0 and m3 > 0)

    return {
        "active": True,
        "event_epoch": _event_epoch(flow),
        "coverage_seconds": coverage,
        "m1": m1, "m3": m3, "m5": m5, "price5": price5,
        "m3_ready": m3_ready, "m5_ready": m5_ready,
        "direct_control": direct_control,
        "aligned_control": direct_control,
        "counter_takeover": counter_takeover,
        "absorbed_counter": absorbed_counter,
        "fast_counter": fast_counter,
        "fast_aligned": fast_aligned,
        # Re-entry can resume either through direct H1-side aggression or by
        # absorbing the opposite aggressors while price moves with the H1 side.
        "resumed": bool(direct_control or absorbed_counter),
    }


def dominance(flow):
    if not isinstance(flow, dict) or not flow.get("trade_data_fresh"):
        return None
    value = _f(flow.get("flow_imbalance"))
    return None if value is None or not -1 <= value <= 1 else (1 if value > 0 else -1 if value < 0 else 0)


def m15_direction(m15):
    """Dashboard-only compatibility helper; never gates Strategy 1."""
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
    if eligible:
        reason = "h1_local_m1_m3_m5_executed_control"
    elif not h1:
        reason = "waiting_for_h1_local"
    elif profile is None:
        reason = "waiting_for_fresh_executed_flow"
    elif not profile["m5_ready"]:
        reason = "waiting_for_m1_m3_m5_coverage"
    elif profile["price5"] is not None and profile["price5"] <= 0:
        reason = "h1_side_flow_without_price_response"
    else:
        reason = "waiting_for_h1_side_m1_m3_m5_control"
    return dict(
        symbol=symbol, side=side, eligible=eligible, reason=reason, policy=POLICY,
        dominant_side=dominance(flow),
        aligned_flow_60s=profile["m1"] if profile else None,
        aligned_flow_180s=profile["m3"] if profile else None,
        aligned_flow_300s=profile["m5"] if profile else None,
        aligned_price_return_300s=profile["price5"] if profile else None,
        m3_ready=profile["m3_ready"] if profile else False,
        m5_ready=profile["m5_ready"] if profile else False,
        absorbed_counter=profile["absorbed_counter"] if profile else False,
        event_epoch=profile["event_epoch"] if profile else None,
    )


def initial_entry_candidate(symbol, analysis, m15, flow, stamp):
    return _candidate(symbol, analysis, flow)


def entry_candidate(symbol, analysis, m15, flow, stamp):
    return _candidate(symbol, analysis, flow)


def pressure_exit(position, m15, mark, flow):
    """Exit only on meaningful control transfer; protect banked MFE earlier.

    Before meaningful MFE exists, require a full M1/M3/M5 opposite takeover and
    adverse M5 price response. Once a strong favorable excursion exists, M1+M3
    opposite control plus a real giveback from the peak is enough to preserve
    the move without waiting for lagging M5 confirmation.
    """
    side = int((position or {}).get("side") or 0)
    entry = _f((position or {}).get("entry"))
    mark = _f(mark)
    profile = flow_profile(flow, side)
    if side not in (-1, 1) or entry is None or entry <= 0 or mark is None or profile is None:
        return None

    features = (position or {}).get("features") or {}
    current_move = side * (mark / entry - 1.0)
    mfe = max(0.0, _f(features.get("mfe_price_move")) or 0.0)
    cost = max(0.0005, _f(features.get("estimated_round_trip_cost_move")) or 0.0)
    giveback = max(0.0, mfe - current_move)

    # Preserve a bankable excursion. The threshold scales with the achieved MFE,
    # but never reacts to sub-cost noise. M1+M3 must both have actually flipped.
    mfe_bankable = bool(mfe >= max(0.0020, cost * 1.5))
    giveback_trigger = max(cost, mfe * 0.12)
    if mfe_bankable and profile["fast_counter"] and giveback >= giveback_trigger:
        return "m1_m3_m5_mfe_preservation_exit"

    # For a position that has not yet earned enough MFE, avoid twitch exits:
    # require the opposite side to own M1/M3/M5 AND make price respond.
    if profile["counter_takeover"]:
        return "m1_m3_m5_risk_exit"
    return None


def update_watch(watch, mark, m15, flow, stamp):
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
        ctx.update(
            flow_m1=profile["m1"], flow_m3=profile["m3"], flow_m5=profile["m5"],
            price_m5=profile["price5"], m3_ready=profile["m3_ready"], m5_ready=profile["m5_ready"],
            absorbed_counter=profile["absorbed_counter"],
        )
        if profile["fast_counter"]:
            ctx["counter_pressure_seen"] = True
            ctx["phase"] = "WAIT_RESUMPTION"
            ctx["last_opposite_trade_epoch"] = profile["event_epoch"]
        elif not ctx.get("counter_pressure_seen"):
            ctx["phase"] = "WAIT_COUNTER_CONTROL"
    return out


def reentry_ready(side, m15, mark, watch, flow, stamp):
    """Unlimited same-H1 re-entry after real opposite pressure and renewed control."""
    side = int(side or 0)
    if side not in (-1, 1) or not watch or int(watch.get("side") or 0) != side:
        return False
    ctx = watch.get("context") or {}
    if ctx.get("phase") != "WAIT_RESUMPTION" or not ctx.get("counter_pressure_seen"):
        return False
    profile = flow_profile(flow, side)
    opposite_epoch = _f(ctx.get("last_opposite_trade_epoch"))
    event_epoch = profile.get("event_epoch") if profile else None
    return bool(
        profile and profile["m5_ready"] and profile["resumed"] and
        event_epoch is not None and opposite_epoch is not None and event_epoch > opposite_epoch
    )
