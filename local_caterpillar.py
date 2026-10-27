"""Causal M15 pressure/recoil execution inside a persistent H1 direction.

No exchange calls or writes. The caller persists the returned watch context.
A previous exit price is a pullback reference, never a required re-entry hurdle.
"""
import copy
import datetime
import math

POLICY = "local_h1_m15_caterpillar_v9_profit_only_weakening_exit"
FLOW_THRESHOLD = .12


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


def _threshold(m15, fraction=.15):
    typical = _f((m15 or {}).get("median_range_move"))
    return max(.0006, min(.0015, (typical or .008) * fraction))


def pressure_exit(position, m15, mark, fresh_flow_context):
    """Take a normal caterpillar exit only on confirmed weakening while net-profitable.

    A routine pullback never crystallizes a loss. Exit requires fresh executed
    counter-flow, strong M15 adverse pressure, a directional recoil from the MFE,
    and enough favorable move to remain above the position's estimated round-trip
    execution-cost floor. Catastrophic/thesis-invalidating exits are handled by
    the caller's separate H1/opposite-pivot and liquidation guards.
    """
    if not position or not m15 or not m15.get("ready"):
        return None
    side = int(position.get("side") or 0)
    entry, mark, flow = _f(position.get("entry")), _f(mark), _flow(fresh_flow_context)
    if side not in (-1, 1) or not entry or not mark or flow is None:
        return None
    features = position.get("features") or {}
    move = side * (mark / entry - 1)
    cost_floor = max(.0002, _f(features.get("estimated_round_trip_cost_move")) or 0.0)
    # Routine weakening exits must preserve at least the estimated trading costs.
    if move <= cost_floor:
        return None
    if side * flow > -FLOW_THRESHOLD:
        return None
    # Sparse prints are not enough to establish a real reversal.
    count = _f((fresh_flow_context or {}).get("trade_count_60s"))
    notional = _f((fresh_flow_context or {}).get("observed_notional_60s"))
    if (count is not None and count < 5) or (notional is not None and notional < 100):
        return None
    if not m15.get("strong_adverse_pressure") or int(m15.get("adverse_score") or 0) < 3:
        return None
    r15 = _f(m15.get("return_15m"))
    candle_reversal=(int(m15.get("candle_direction") or 0)==-side and (_f(m15.get("body_fraction")) or 0.)>=.50)
    if not candle_reversal and (r15 is None or side * r15 >= 0):
        return None
    peak = max(0., _f(features.get("mfe_price_move")) or 0., move)
    if peak - move < _threshold(m15):
        return None
    return "m15_pressure_reversal_profit_only"


def update_watch(watch, mark, m15, flow, now_epoch):
    """Record a real counter-direction pullback before allowing resumption."""
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
                   pullback_threshold=_threshold(m15), resumption_threshold=_threshold(m15, .10),
                   last_observed_epoch=stamp, last_observed_mark=mark, caterpillar_policy=POLICY)
    imbalance = _flow(flow)
    if imbalance is not None and side * imbalance <= -FLOW_THRESHOLD:
        context["counter_pressure_seen"] = True
        context["last_opposite_flow_epoch"] = stamp
    # An adverse price excursion is mandatory. Stale pre-exit recovery alone
    # cannot promote the watch or immediately reopen the position.
    if context["phase"] == "WAIT_PULLBACK" and pullback >= context["pullback_threshold"] and context.get("counter_pressure_seen"):
        context["phase"] = "WAIT_RESUMPTION"
        context["pullback_confirmed_epoch"] = stamp
    return out


def reentry_ready(side, m15, mark, watch, flow, now_epoch):
    """Re-enter on resumed H1-side pressure, even at a better than exit price."""
    side = int(side or 0)
    if side not in (-1, 1) or not watch or int(watch.get("side") or 0) != side:
        return False
    if not m15 or not m15.get("ready") or not m15.get("recovery_confirmed") or int(m15.get("recovery_score") or 0) < 3:
        return False
    if m15.get("side") is not None and int(m15["side"]) != side:
        return False
    context = watch.get("context") or {}
    if context.get("phase") != "WAIT_RESUMPTION" or not context.get("counter_pressure_seen"):
        return False
    imbalance = _flow(flow)
    mark, extreme, stamp = _f(mark), _f(context.get("pullback_extreme")), _f(now_epoch)
    confirmed = _f(context.get("pullback_confirmed_epoch"))
    if imbalance is None or side * imbalance < FLOW_THRESHOLD or not mark or not extreme or stamp is None or confirmed is None or stamp <= confirmed:
        return False
    observed = _f(context.get("last_observed_epoch"))
    if observed is None or not 0 <= stamp - observed <= 15:
        return False
    rebound = side * (mark / extreme - 1)
    return rebound >= (_f(context.get("resumption_threshold")) or _threshold(m15, .10))


def protective_breakeven(position, mark):
    """Legacy API. No fixed 0.4% arming threshold or percentage-based profit exit.

    Directional exits are driven by H1 reversal and M15 pressure; the separate
    emergency portfolio guard remains responsible for catastrophic risk.
    """
    return None
