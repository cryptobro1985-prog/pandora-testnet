"""Strategy 1: H1 direction + live executed-flow Caterpillar.

H1 defines the only allowed direction. Execution is event-driven:
- entry only when an observed counter-move weakens and M1 executed-flow flips back to the H1 side;
- exit immediately when M1 executed-flow flips against the open H1-side position;
- re-entry when that counter-flow weakens and M1 flips back to the H1 side.
M3/M5 remain telemetry/context only and never delay an execution decision.
MFE is measured for profit-preservation audit; it never gates entry or exit.
"""
import copy
import math

POLICY = "Caterpillar H1-local M1 executed-flow weakening/resumption; M3/M5 telemetry; MFE audit"


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

    return {
        "active": True,
        "event_epoch": _event_epoch(flow),
        "coverage_seconds": coverage,
        "m1": m1,
        "m3": m3,
        "m5": m5,
        "price5": price5,
        "m3_ready": bool(coverage >= 180 and m3 is not None),
        "m5_ready": bool(coverage >= 300 and m5 is not None and price5 is not None),
        "aligned_now": bool(m1 > 0),
        "counter_now": bool(m1 < 0),
        "neutral_now": bool(m1 == 0),
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


def _candidate(symbol, analysis, execution_context, flow):
    side = int((analysis or {}).get("entry_side") or 0)
    h1 = bool(
        (analysis or {}).get("ready")
        and (analysis or {}).get("h1_direction_anchor")
        and not (analysis or {}).get("entry_blocked")
        and side in (-1, 1)
    )
    profile = flow_profile(flow, side)
    resumed = bool(isinstance(execution_context, dict) and execution_context.get("resumption_observed"))
    eligible = bool(h1 and profile and profile["aligned_now"] and resumed)

    if eligible:
        reason = "h1_side_resumed_after_counterflow"
    elif not h1:
        reason = "waiting_for_h1_local"
    elif profile is None:
        reason = "waiting_for_fresh_executed_flow"
    elif profile["counter_now"]:
        reason = "counterflow_active_waiting_for_exhaustion"
    elif profile["aligned_now"] and not resumed:
        reason = "waiting_for_pullback_then_h1_side_resumption"
    else:
        reason = "waiting_for_executed_flow_resumption"

    return dict(
        symbol=symbol,
        side=side,
        eligible=eligible,
        reason=reason,
        policy=POLICY,
        dominant_side=dominance(flow),
        aligned_flow_60s=profile["m1"] if profile else None,
        aligned_flow_180s=profile["m3"] if profile else None,
        aligned_flow_300s=profile["m5"] if profile else None,
        aligned_price_return_300s=profile["price5"] if profile else None,
        m3_ready=profile["m3_ready"] if profile else False,
        m5_ready=profile["m5_ready"] if profile else False,
        event_epoch=profile["event_epoch"] if profile else None,
        resumption_observed=resumed,
    )


def initial_entry_candidate(symbol, analysis, execution_context, flow, stamp):
    return _candidate(symbol, analysis, execution_context, flow)


def entry_candidate(symbol, analysis, execution_context, flow, stamp):
    return _candidate(symbol, analysis, execution_context, flow)


def pressure_exit(position, m15, mark, flow):
    """Close as soon as the opposite executed side takes M1 control.

    There is deliberately no giveback threshold, M3/M5 confirmation, price
    threshold, or extra indicator. MFE only labels whether an earned excursion
    existed before the control flip.
    """
    side = int((position or {}).get("side") or 0)
    entry = _f((position or {}).get("entry"))
    mark = _f(mark)
    profile = flow_profile(flow, side)
    if side not in (-1, 1) or entry is None or entry <= 0 or mark is None or profile is None:
        return None
    if not profile["counter_now"]:
        return None

    features = (position or {}).get("features") or {}
    mfe = max(0.0, _f(features.get("mfe_price_move")) or 0.0)
    return "m1_mfe_preservation_exit" if mfe > 0 else "m1_counterflow_exit"


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
            flow_m1=profile["m1"],
            flow_m3=profile["m3"],
            flow_m5=profile["m5"],
            price_m5=profile["price5"],
            m3_ready=profile["m3_ready"],
            m5_ready=profile["m5_ready"],
        )
        if profile["counter_now"]:
            ctx["counter_pressure_seen"] = True
            ctx["phase"] = "WAIT_RESUMPTION"
            ctx["last_opposite_trade_epoch"] = profile["event_epoch"]
        elif not ctx.get("counter_pressure_seen"):
            ctx["phase"] = "WAIT_COUNTER_CONTROL"
    return out


def reentry_ready(side, m15, mark, watch, flow, stamp):
    """Re-enter the same H1 direction on the first live M1 resumption."""
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
        profile
        and profile["aligned_now"]
        and event_epoch is not None
        and opposite_epoch is not None
        and event_epoch > opposite_epoch
    )
