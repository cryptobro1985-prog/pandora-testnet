"""Pure, restart-safe exit rules. ROE thresholds are gross margin fractions."""
import copy
import math

LOCK_TRIGGER_ROE = 0.10
LOCK_ROE = 0.075
TRAIL_ARM_ROE = 0.12
MIN_EXIT_ROE = 0.075


def better(side, old, candidate):
    if old is None:
        return candidate
    return max(old, candidate) if side > 0 else min(old, candidate)


def risk_state(position):
    keys = ("peak", "trail_armed", "trail_stop", "history", "last_price",
            "last_evaluated_at", "last_exit_check")
    return {key: position[key] for key in keys if key in position}


def evaluate_exit(position, price, evaluated_at):
    """Return updated position and exit reason, without external side effects.

    Stops execute at the first observed price, including after a gap. Never
    invent a historical fill at a stop or reconstruct profits retroactively.
    """
    if not math.isfinite(price) or price <= 0:
        raise ValueError("invalid market price")
    pos = copy.deepcopy(position)
    entry, side, lev = float(pos["entry"]), int(pos["side"]), float(pos["leverage"])
    if entry <= 0 or lev <= 0 or side not in (-1, 1):
        raise ValueError("invalid position")
    history = [float(p) for p in pos.get("history", [])[-120:]
               if math.isfinite(float(p)) and float(p) > 0]
    pos["peak"] = better(side, float(pos.get("peak", entry)), price)
    roe = (price / entry - 1) * side * lev
    peak_roe = (pos["peak"] / entry - 1) * side * lev
    # A restored historical peak is sufficient to restore protection too.
    if peak_roe >= LOCK_TRIGGER_ROE:
        pos["locked"] = True
        pos["stop"] = better(side, pos.get("stop"), entry * (1 + side * LOCK_ROE / lev))
    pos["trail_armed"] = bool(pos.get("trail_armed")) or peak_roe >= TRAIL_ARM_ROE
    tail = history[-21:]
    returns = [abs(b / a - 1) * lev for a, b in zip(tail, tail[1:])]
    noise = sum(returns) / len(returns) if returns else 0.01
    gap = max(0.025, min(0.08, noise * 3))
    if pos["trail_armed"]:
        floor = max(MIN_EXIT_ROE, peak_roe - gap)
        candidate = entry * (1 + side * floor / lev)
        # Volatility, restarts, and retraces may NEVER loosen an existing stop.
        pos["trail_stop"] = better(side, pos.get("trail_stop"), candidate)
    crossed = lambda stop: stop is not None and side * (price - float(stop)) <= 0
    reason = None
    if crossed(pos.get("stop")):
        reason = "profit_protection_stop"
    elif pos["trail_armed"] and crossed(pos.get("trail_stop")):
        reason = "trailing_stop"
    pos["last_price"] = price
    pos["last_evaluated_at"] = evaluated_at
    pos["last_exit_check"] = {"roe": roe, "peak_roe": peak_roe, "trail_gap": gap,
                              "stop": pos.get("stop"), "trail_stop": pos.get("trail_stop"),
                              "reason": reason}
    pos["history"] = (history + [price])[-120:]
    return pos, reason
