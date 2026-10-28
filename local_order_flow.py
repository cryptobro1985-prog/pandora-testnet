"""Strategy 1: H1 local defines side; M15 manages exit, pullback and re-entry.
No candle scores, liquidity quotas, arbitrary flow thresholds or entry delays.
"""
import copy
import math

POLICY = "Caterpillar 1.0 H1-local M15-cycle user rules"

def _f(x):
    try:
        value = float(x)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None

def dominance(flow):
    """Sign of the actually observed executed-buy versus executed-sell volume."""
    if not isinstance(flow, dict) or not flow.get("trade_data_fresh"):
        return None
    age = _f(flow.get("latest_trade_age_seconds"))
    if age is None or not -1 <= age <= 15:
        return None
    buy, sell = _f(flow.get("buy_volume_60s")), _f(flow.get("sell_volume_60s"))
    if buy is not None and sell is not None and min(buy, sell) >= 0:
        return 1 if buy > sell else (-1 if sell > buy else 0)
    imbalance = _f(flow.get("flow_imbalance"))
    if imbalance is None or not -1 <= imbalance <= 1:
        return None
    return 1 if imbalance > 0 else (-1 if imbalance < 0 else 0)

def m15_direction(m15):
    """Use the observed M15 move, independent of the trade WebSocket."""
    if not isinstance(m15, dict) or not m15.get("ready"):
        return None
    ret = _f(m15.get("return_15m"))
    if ret is not None and ret != 0:
        return 1 if ret > 0 else -1
    candle = int(m15.get("candle_direction") or 0)
    return candle if candle in (-1, 1) else None

def entry_candidate(symbol, analysis, m15, flow, stamp):
    side = int((analysis or {}).get("entry_side") or 0)
    dom = dominance(flow)
    h1 = bool((analysis or {}).get("ready") and (analysis or {}).get("h1_direction_anchor")
              and not (analysis or {}).get("entry_blocked") and side in (-1, 1))
    m15_ready = bool((m15 or {}).get("ready"))
    eligible = h1 and m15_ready and m15_direction(m15) == side
    reason = ("h1_local_m15_direction" if eligible else
              "waiting_for_h1_local" if not h1 else
              "waiting_for_m15_data" if not m15_ready else
              "waiting_for_m15_direction")
    imbalance = _f((flow or {}).get("flow_imbalance"))
    return dict(symbol=symbol, side=side, eligible=eligible, reason=reason,
                policy=POLICY, dominant_side=dom,
                buy_volume_60s=(flow or {}).get("buy_volume_60s"),
                sell_volume_60s=(flow or {}).get("sell_volume_60s"),
                aligned_flow=side * imbalance if imbalance is not None else None)

def pressure_exit(position, m15, mark, flow):
    """Leave the H1-side position when sellers/buyers lose control on M15."""
    side = int((position or {}).get("side") or 0)
    if side not in (-1, 1) or not (m15 or {}).get("ready"):
        return None
    if m15_direction(m15) != -side:
        return None
    # Opposite executed-flow control accompanied by an M15 adverse turn.
    adverse_turn = (bool(m15.get("strong_adverse_pressure")) or
                    int(m15.get("adverse_score") or 0) > 0 or
                    int(m15.get("candle_direction") or 0) == -side or
                    ((lambda r: r is not None and side * r < 0)(_f(m15.get("return_15m")))))
    return "m15_opposite_control_exit" if adverse_turn else None

def update_watch(watch, mark, m15, flow, stamp):
    """Record actual counter-direction pullback after exit; no percentage hurdle."""
    out = copy.deepcopy(watch or {})
    side = int(out.get("side") or 0)
    mark = _f(mark)
    if side not in (-1, 1) or mark is None:
        return out
    ctx = out.setdefault("context", {})
    exit_price = _f(out.get("exit_price"))
    extreme = _f(ctx.get("pullback_extreme"))
    if extreme is None:
        extreme = exit_price if exit_price is not None else mark
    if m15_direction(m15) == -side:
        ctx["counter_pressure_seen"] = True
        ctx["phase"] = "WAIT_RESUMPTION"
        extreme = min(extreme, mark) if side > 0 else max(extreme, mark)
    elif ctx.get("counter_pressure_seen"):
        extreme = min(extreme, mark) if side > 0 else max(extreme, mark)
    else:
        ctx["phase"] = "WAIT_PULLBACK"
    ctx["pullback_extreme"] = extreme
    ctx["last_observed_epoch"] = stamp
    return out

def reentry_ready(side, m15, mark, watch, flow, stamp):
    """Re-enter H1 side as the observed pullback ends and original side returns."""
    side = int(side or 0)
    if side not in (-1, 1) or not watch or int(watch.get("side") or 0) != side:
        return False
    if not (m15 or {}).get("ready"):
        return False
    ctx = watch.get("context") or {}
    if not ctx.get("counter_pressure_seen") or m15_direction(m15) != side:
        return False
    mark = _f(mark)
    extreme = _f(ctx.get("pullback_extreme"))
    return bool(mark is not None and extreme is not None and side * (mark - extreme) > 0)
