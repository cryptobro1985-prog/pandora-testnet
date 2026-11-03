"""Causal executed-trade pressure/recoil execution inside a persistent H1 direction.

No exchange calls or writes. The caller persists the returned watch context.
A previous exit price is a pullback reference, never a required re-entry hurdle.
"""
import copy
import datetime
import math

POLICY = "local_h1_m1_m3_m5_executed_flow_v17_no_m15"
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


def _threshold(execution_context=None, fraction=.15):
    """Price recoil threshold independent of 15-minute candles."""
    return max(.0006, min(.0015, .008 * fraction))

def initial_h1_entry_candidate(symbol, analysis, execution_context, flow, now_epoch):
    """H1 confirmed direction plus fresh actual trades; no candle execution gate."""
    result = dict(symbol=symbol, eligible=False, policy="h1_executed_flow_initial_v17")
    side = (analysis or {}).get("entry_side")
    profile = _flow_profile(flow, side)
    count = _f((flow or {}).get("trade_count_60s"))
    notional = _f((flow or {}).get("observed_notional_60s"))
    coverage = _f((flow or {}).get("trade_coverage_seconds"))
    age = _f((flow or {}).get("latest_trade_age_seconds"))
    stamp = _f(now_epoch)
    if not analysis or not analysis.get("ready") or not analysis.get("anchor_confirmed") or not analysis.get("h1_direction_anchor") or side not in (-1, 1):
        result["reason"] = "confirmed_h1_local_unavailable"; return result
    if analysis.get("entry_blocked"):
        result["reason"] = "opposite_h1_confirmation_pending"; return result
    if stamp is None or profile is None or age is None or age > 15 or coverage is None or coverage < 60 or count is None or count < 5 or notional is None or notional < 100:
        result["reason"] = "fresh_executed_flow_unavailable"; return result
    if not profile["resumed"]:
        result["reason"] = "executed_flow_not_aligned"; return result
    result.update(eligible=True, reason="h1_m1_m3_m5_flow_initial", side=side,
                  recovery_score=0, adverse_score=0,
                  aligned_flow=profile["60s"], aligned_flow_15s=profile["15s"],
                  aligned_flow_30s=profile["30s"], observed_notional_60s=notional,
                  trade_count_60s=count, observed_at_ms=int(stamp * 1000),
                  rank_key=[1, profile["15s"], profile["30s"], notional])
    return result

def entry_candidate(symbol, analysis, execution_context, flow, now_epoch):
    """Rank same-direction re-entry on independent executed-flow resumption."""
    result = dict(symbol=symbol, eligible=False, policy=SELECTION_POLICY)
    side = (analysis or {}).get("entry_side")
    profile = _flow_profile(flow, side)
    count = _f((flow or {}).get("trade_count_60s"))
    notional = _f((flow or {}).get("observed_notional_60s"))
    coverage = _f((flow or {}).get("trade_coverage_seconds"))
    stamp = _f(now_epoch)
    if not analysis or not analysis.get("ready") or not analysis.get("anchor_confirmed") or not analysis.get("h1_direction_anchor") or side not in (-1, 1):
        result["reason"] = "h1_direction_unavailable"; return result
    if analysis.get("entry_blocked"):
        result["reason"] = "opposite_h1_confirmation_pending"; return result
    if stamp is None or profile is None or coverage is None or coverage < 60:
        result["reason"] = "fresh_executed_flow_unavailable"; return result
    if count is None or notional is None or count < 5 or notional < 100:
        result["reason"] = "insufficient_executed_liquidity"; return result
    if not profile["strong_resumed"]:
        result["reason"] = "flow_not_resumed_after_pullback"; return result
    result.update(eligible=True, reason="confirmed_h1_executed_flow", side=side,
                  recovery_score=0, adverse_score=0,
                  aligned_flow=profile["60s"], aligned_flow_15s=profile["15s"],
                  aligned_flow_30s=profile["30s"], observed_notional_60s=notional,
                  trade_count_60s=count, observed_at_ms=int(stamp * 1000),
                  rank_key=[profile["15s"], profile["30s"], profile["60s"], notional])
    return result

def rank_candidates(candidates):
    """Deterministic order independent of the configured symbol enumeration."""
    return sorted((c for c in candidates if c.get("eligible")),
                  key=lambda c: tuple(-v for v in c["rank_key"]) + (c["symbol"],))


def pressure_exit(position, execution_context, mark, fresh_flow_context):
    """Exit on causal flow control transfer and observed giveback from MFE."""
    if not position:
        return None
    side = int(position.get("side") or 0)
    entry, mark = _f(position.get("entry")), _f(mark)
    profile = _flow_profile(fresh_flow_context, side)
    if side not in (-1, 1) or not entry or not mark or profile is None:
        return None
    features = position.get("features") or {}
    move = side * (mark / entry - 1)
    cost_floor = max(.0002, _f(features.get("estimated_round_trip_cost_move")) or 0.)
    count = _f((fresh_flow_context or {}).get("trade_count_60s"))
    notional = _f((fresh_flow_context or {}).get("observed_notional_60s"))
    if count is None or count < 5 or notional is None or notional < 100:
        return None
    peak = max(0., _f(features.get("mfe_price_move")) or 0., move)
    recoil = peak - move
    if recoil < _threshold():
        return None
    if profile["counter_control"]:
        return "executed_flow_counter_control_exit"
    if move > cost_floor and profile["weakening"] and profile["15s"] < 0:
        return "executed_flow_weakening_profit_exit"
    return None

def update_watch(watch, mark, execution_context, flow, now_epoch):
    """Record genuine buyer/seller control change; no price-distance gate."""
    out = copy.deepcopy(watch or {})
    side = int(out.get("side") or 0)
    stamp = _f(now_epoch)
    exit_epoch = _epoch(out.get("exit_at"))
    if side not in (-1, 1) or stamp is None or exit_epoch is None or stamp <= exit_epoch:
        return out
    context = out.setdefault("context", {})
    context.setdefault("phase", "WAIT_COUNTER_FLOW")
    profile = _flow_profile(flow, side)
    if profile is None:
        return out
    context.update(last_observed_epoch=stamp, last_observed_mark=_f(mark),
                   flow_15s=profile["15s"], flow_30s=profile["30s"],
                   flow_60s=profile["60s"], caterpillar_policy=POLICY)
    if profile["counter_control"] or (profile["15s"] < -.08 and profile["30s"] < -.05):
        context["counter_pressure_seen"] = True
        context["last_opposite_flow_epoch"] = stamp
        context["phase"] = "WAIT_DIRECTIONAL_RESUMPTION"
    return out

def reentry_ready(side, execution_context, mark, watch, flow, now_epoch):
    """Re-enter when fresh sellers/buyers regain control after opposite flow."""
    side = int(side or 0)
    if side not in (-1, 1) or not watch or int(watch.get("side") or 0) != side:
        return False
    context = watch.get("context") or {}
    if context.get("phase") != "WAIT_DIRECTIONAL_RESUMPTION" or not context.get("counter_pressure_seen"):
        return False
    stamp = _f(now_epoch)
    opposite_epoch = _f(context.get("last_opposite_flow_epoch"))
    profile = _flow_profile(flow, side)
    if stamp is None or opposite_epoch is None or stamp <= opposite_epoch or profile is None:
        return False
    if not profile["strong_resumed"]:
        return False
    # Require a subsequent observation, not the same trade window that recorded
    # counter-control. Neither price retracement nor candle recovery is a gate.
    observed = _f(context.get("last_observed_epoch"))
    return observed is not None and 0 <= stamp - observed <= 15

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
