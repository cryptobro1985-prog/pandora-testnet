"""Causal M15 pressure/recoil execution inside a persistent H1 direction.

No exchange calls or writes. The caller persists the returned watch context.
A previous exit price is a pullback reference, never a required re-entry hurdle.
"""
import copy
import datetime
import math

POLICY = "local_h1_multihorizon_flow_caterpillar_v15_pullback_first"
FLOW_THRESHOLD = .12
SELECTION_POLICY = "h1_multihorizon_flow_ranked_execution_v2"


def _f(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _epoch(value):
    value_number = _f(value)
    if value_number is not None:
        return value_number
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def _flow(context):
    if not isinstance(context, dict) or not context.get("trade_data_fresh"):
        return None
    age = _f(context.get("latest_trade_age_seconds"))
    if age is not None and not -1 <= age <= 15:
        return None
    value = _f(context.get("flow_imbalance"))
    return value if value is not None and -1 <= value <= 1 else None

def _flow_profile(context, side):
    """Return aligned executed-flow pressure across multiple horizons.

    Positive values mean executed flow supports the H1 trade direction.
    The short horizon detects weakening/resumption before the 60s aggregate
    fully flips, while 60s/300s prevent a single burst from forcing a re-entry.
    """
    if side not in (-1, 1) or not isinstance(context, dict) or not context.get("trade_data_fresh"):
        return None
    age = _f(context.get("latest_trade_age_seconds"))
    if age is not None and not -1 <= age <= 15:
        return None
    vals = {}
    for key, fallback in (("15s","flow_imbalance_15s"),("30s","flow_imbalance_30s"),
                          ("60s","flow_imbalance"),("300s","flow_imbalance_300s")):
        v = _f(context.get(fallback))
        vals[key] = side * v if v is not None and -1 <= v <= 1 else None
    if vals["60s"] is None:
        return None
    # Backward-compatible fallback while the live stream warms the new windows.
    if vals["15s"] is None: vals["15s"] = vals["60s"]
    if vals["30s"] is None: vals["30s"] = vals["60s"]
    if vals["300s"] is None: vals["300s"] = vals["60s"]
    vals["weakening"] = (vals["15s"] < .02 and vals["30s"] < .06 and
                         vals["15s"] <= vals["60s"] - .08)
    vals["counter_control"] = vals["15s"] <= -.12 and vals["30s"] <= -.08
    vals["resumed"] = (vals["15s"] >= .16 and vals["30s"] >= .12 and
                       vals["60s"] >= .08 and vals["15s"] >= vals["60s"] - .02)
    vals["strong_resumed"] = (vals["15s"] >= .20 and vals["30s"] >= .15 and
                              vals["60s"] >= .10)
    return vals


def _threshold(m15, fraction=.15):
    typical = _f((m15 or {}).get("median_range_move"))
    return max(.0006, min(.0015, (typical or .008) * fraction))


def entry_candidate(symbol, analysis, m15, flow, now_epoch):
    """Validate observable entry evidence; ranking is not a profit prediction.

    Compare M15 recovery first, then aligned executed flow and observed liquidity.
    Missing observations must not silently pass a minimum-liquidity check.
    """
    result = dict(symbol=symbol, eligible=False, policy=SELECTION_POLICY)
    side = (analysis or {}).get("entry_side")
    reason = None
    stamp = _f(now_epoch)
    observed = _f((m15 or {}).get("observed_at_ms"))
    profile = _flow_profile(flow, side)
    imbalance = _flow(flow)
    count = _f((flow or {}).get("trade_count_60s"))
    notional = _f((flow or {}).get("observed_notional_60s"))
    coverage = _f((flow or {}).get("trade_coverage_seconds"))
    age = _f((flow or {}).get("latest_trade_age_seconds"))
    score = _f((m15 or {}).get("recovery_score"))
    adverse = _f((m15 or {}).get("adverse_score"))
    if not analysis or not analysis.get("ready") or not analysis.get("h1_direction_anchor") or side not in (-1, 1):
        reason = "h1_direction_unavailable"
    elif analysis.get("entry_blocked"):
        reason = "opposite_h1_confirmation_pending"
    elif not m15 or not m15.get("ready") or m15.get("side") != side:
        reason = "m15_direction_unavailable"
    elif stamp is None or observed is None or not 0 <= stamp * 1000 - observed <= 10000:
        reason = "stale_m15_observation"
    elif imbalance is None or age is None or coverage is None or coverage < 60:
        reason = "fresh_executed_flow_unavailable"
    elif count is None or notional is None or count < 5 or notional < 100:
        reason = "insufficient_executed_liquidity"
    elif not m15.get("pullback_observed"):
        reason = "m15_pullback_not_observed"
    elif not m15.get("pullback_exhausted"):
        reason = "m15_pullback_not_exhausted"
    elif profile is None or not profile.get("strong_resumed"):
        reason = "flow_not_resumed_after_pullback"
    elif not m15.get("recovery_confirmed") or score is None or score < 3 or adverse is None or adverse > 1 or m15.get("strong_adverse_pressure"):
        reason = "m15_recovery_unconfirmed"
    if reason:
        result["reason"] = reason
        return result
    result.update(eligible=True, reason="confirmed_h1_m15_flow", side=side,
                  recovery_score=score, adverse_score=adverse,
                  aligned_flow=profile["60s"], aligned_flow_15s=profile["15s"],
                  aligned_flow_30s=profile["30s"], observed_notional_60s=notional,
                  trade_count_60s=count, observed_at_ms=observed,
                  rank_key=[score, -adverse, profile["15s"], profile["30s"], notional])
    return result


def rank_candidates(candidates):
    """Deterministic order independent of the configured symbol enumeration."""
    return sorted((c for c in candidates if c.get("eligible")),
                  key=lambda c: tuple(-v for v in c["rank_key"]) + (c["symbol"],))


def pressure_exit(position, m15, mark, fresh_flow_context):
    """Exit when directional participation genuinely weakens.

    A profitable trend is allowed to run while short/medium executed flow still
    supports the H1 side. Exit is triggered by a real loss of control plus M15
    recoil, before waiting for a full 60-second flow reversal. Losing positions
    require stronger counter-control unless the emergency stop handles them.
    """
    if not position or not m15 or not m15.get("ready"):
        return None
    side = int(position.get("side") or 0)
    entry, mark = _f(position.get("entry")), _f(mark)
    profile = _flow_profile(fresh_flow_context, side)
    if side not in (-1, 1) or not entry or not mark or profile is None:
        return None
    features = position.get("features") or {}
    move = side * (mark / entry - 1)
    cost_floor = max(.0002, _f(features.get("estimated_round_trip_cost_move")) or 0.0)
    count = _f((fresh_flow_context or {}).get("trade_count_60s"))
    notional = _f((fresh_flow_context or {}).get("observed_notional_60s"))
    if (count is not None and count < 5) or (notional is not None and notional < 100):
        return None

    adverse = int(m15.get("adverse_score") or 0)
    r15 = _f(m15.get("return_15m"))
    candle_reversal = (int(m15.get("candle_direction") or 0) == -side and
                       (_f(m15.get("body_fraction")) or 0.) >= .42)
    price_confirmation = candle_reversal or (r15 is not None and side * r15 < 0) or adverse >= 2
    peak = max(0., _f(features.get("mfe_price_move")) or 0., move)
    recoil = peak - move
    if recoil < _threshold(m15):
        return None

    if move > cost_floor and profile["weakening"] and price_confirmation:
        return "m15_flow_weakening_profit_exit"
    if profile["counter_control"] and (adverse >= 3 or candle_reversal):
        return "m15_flow_counter_control"
    return None

def update_watch(watch, mark, m15, flow, now_epoch):
    """Observe the bounce after exit and arm re-entry only after real counter-flow."""
    out = copy.deepcopy(watch or {})
    side = int(out.get("side") or 0)
    exit_price, mark, stamp = _f(out.get("exit_price")), _f(mark), _f(now_epoch)
    exit_epoch = _epoch(out.get("exit_at"))
    if side not in (-1, 1) or not exit_price or not mark or stamp is None or exit_epoch is None or stamp <= exit_epoch:
        return out
    context = out.setdefault("context", {})
    context.setdefault("phase", "WAIT_PULLBACK")
    extreme = _f(context.get("pullback_extreme")) or exit_price
    extreme = min(extreme, mark) if side > 0 else max(extreme, mark)
    pullback = max(0., -side * (extreme / exit_price - 1))
    context.update(pullback_extreme=extreme, pullback_move=pullback,
                   pullback_threshold=_threshold(m15),
                   resumption_threshold=_threshold(m15, .10),
                   last_observed_epoch=stamp,last_observed_mark=mark,caterpillar_policy=POLICY)
    profile = _flow_profile(flow, side)
    if profile is not None:
        context["flow_15s"] = profile["15s"]
        context["flow_30s"] = profile["30s"]
        context["flow_60s"] = profile["60s"]
        if profile["counter_control"] or (profile["15s"] < -.08 and profile["30s"] < -.05):
            context["counter_pressure_seen"] = True
            context["last_opposite_flow_epoch"] = stamp
    if (context["phase"] == "WAIT_PULLBACK" and pullback >= context["pullback_threshold"] and
            context.get("counter_pressure_seen")):
        context["phase"] = "WAIT_RESUMPTION"
        context["pullback_confirmed_epoch"] = stamp
    return out

def reentry_ready(side, m15, mark, watch, flow, now_epoch):
    """Universal re-entry after a completed bounce and renewed executed control."""
    side = int(side or 0)
    if side not in (-1, 1) or not watch or int(watch.get("side") or 0) != side:
        return False
    if not m15 or not m15.get("ready") or not m15.get("recovery_confirmed"):
        return False
    if int(m15.get("recovery_score") or 0) < 3 or int(m15.get("adverse_score") or 0) > 1:
        return False
    if m15.get("side") is not None and int(m15["side"]) != side:
        return False
    context = watch.get("context") or {}
    if context.get("phase") != "WAIT_RESUMPTION" or not context.get("counter_pressure_seen"):
        return False
    profile = _flow_profile(flow, side)
    mark, extreme, stamp = _f(mark), _f(context.get("pullback_extreme")), _f(now_epoch)
    confirmed = _f(context.get("pullback_confirmed_epoch"))
    if profile is None or not profile.get("strong_resumed") or not mark or not extreme or stamp is None or confirmed is None or stamp <= confirmed:
        return False
    observed = _f(context.get("last_observed_epoch"))
    if observed is None or not 0 <= stamp - observed <= 15:
        return False
    rebound = side * (mark / extreme - 1)
    if rebound < (_f(context.get("resumption_threshold")) or _threshold(m15, .10)):
        return False
    close_location = _f(m15.get("close_location"))
    if close_location is not None:
        if side > 0 and close_location < .60:return False
        if side < 0 and close_location > .40:return False
    return True

def protective_breakeven(position, mark):
    """Cost-aware profit floor derived from the saved HYPE/NEAR paper history.

    Arm after a 0.20% favorable underlying move. Once armed, if price gives back
    to +0.16% gross move, close at the *observed* mark only while still above the
    stored round-trip cost floor. This does not invent a stop fill and therefore
    cannot guarantee positive execution through gaps.
    """
    if not position:
        return None
    side = int(position.get("side") or 0)
    entry, mark = _f(position.get("entry")), _f(mark)
    if side not in (-1, 1) or not entry or not mark:
        return None
    features = position.setdefault("features", {})
    move = side * (mark / entry - 1.0)
    peak = max(0.0, _f(features.get("mfe_price_move")) or 0.0, move)
    arm_move = .0020
    lock_move = .0016
    cost_floor = max(.0002, _f(features.get("estimated_round_trip_cost_move")) or 0.0)
    armed = bool(features.get("profit_lock_armed")) or peak >= arm_move
    features["profit_lock_armed"] = armed
    features["profit_lock_arm_move"] = arm_move
    features["profit_lock_buffer_move"] = lock_move
    features["profit_lock_arm_move_pct"] = arm_move * 100.0
    features["profit_lock_buffer_move_pct"] = lock_move * 100.0
    features["profit_lock_mode"] = "historical_v10_cost_aware_profit_floor"
    if not armed:
        return None
    # Do not manufacture a theoretical stop fill. Only close on the live mark,
    # and only if it still leaves more than the modeled round-trip cost.
    if move <= lock_move and move > cost_floor:
        return mark
    return None
