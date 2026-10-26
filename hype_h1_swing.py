"""HYPE H1 local-extreme PAPER strategy.

Pure signal logic only. No exchange orders, credentials, networking or persistence.
Signals use completed 1h candles only, so local extrema are confirmed without future data.
"""

import math

POLICY = "hype_h1_local_swing_v2_causal_execution"
SYMBOL = "HYPE"
INTERVAL = "1h"
STARTING_EQUITY = 100.0
MARGIN_FRACTION = 0.10
LEVERAGE = 25.0
PIVOT_LOOKBACK = 4
MIN_FAVORABLE_MOVE_FOR_WEAKENING = 0.004
PROFIT_LOCK_ARM_MOVE = 0.004
PROFIT_LOCK_BUFFER_MOVE = 0.0012
LIQUIDATION_PROXY_ROE = -0.95


def _f(value):
    try:
        x = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return x if math.isfinite(x) else None


def completed_candles(rows, now_ms):
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        t = _f(row.get("t"))
        T = _f(row.get("T"))
        o, h, l, c = (_f(row.get(k)) for k in ("o", "h", "l", "c"))
        v = _f(row.get("v"))
        if None in (t, T, o, h, l, c) or min(o, h, l, c) <= 0:
            continue
        if not (3_599_000 <= T-t <= 3_600_000 and l <= min(o,c) <= max(o,c) <= h):
            continue
        if v is not None and v < 0:
            continue
        # A tiny grace prevents a boundary race at the exact hourly close.
        if T > float(now_ms) - 1000:
            continue
        out.append({"t": int(t), "T": int(T), "o": o, "h": h, "l": l, "c": c,
                    "v": 0.0 if v is None else v})
    out.sort(key=lambda x: x["t"])
    dedup = {x["t"]: x for x in out}
    return [dedup[k] for k in sorted(dedup)]


def _ret(a, b):
    return (b / a - 1.0) if a and b else 0.0


def analyze(rows, now_ms):
    candles = completed_candles(rows, now_ms)
    if len(candles) < PIVOT_LOOKBACK + 2:
        return {"ready": False, "reason": "insufficient_closed_h1_candles",
                "closed_candles": len(candles), "policy": POLICY}
    if float(now_ms) - candles[-1]["T"] > 3_600_000 + 90_000:
        return {"ready": False, "reason": "stale_h1_history", "policy": POLICY}
    recent = candles[-(PIVOT_LOOKBACK+2):]
    if any(abs(b["t"]-a["t"]-3_600_000)>1000 for a,b in zip(recent,recent[1:])):
        return {"ready": False, "reason": "gapped_h1_history", "policy": POLICY}

    x = candles[-1]       # latest completed H1 candle: confirmation candle
    p = candles[-2]       # candidate local extreme
    prior = candles[-2-PIVOT_LOOKBACK:-2]
    prior_lows = [z["l"] for z in prior]
    prior_highs = [z["h"] for z in prior]

    local_low = (
        p["l"] <= min(prior_lows)
        and x["l"] > p["l"]
        and x["c"] > p["c"]
        and x["c"] > x["o"]
    )
    local_high = (
        p["h"] >= max(prior_highs)
        and x["h"] < p["h"]
        and x["c"] < p["c"]
        and x["c"] < x["o"]
    )

    closes = [z["c"] for z in candles]
    last_ret = _ret(closes[-2], closes[-1])
    prev_ret = _ret(closes[-3], closes[-2])
    mom3 = _ret(closes[-4], closes[-1])
    prev_mom3 = _ret(closes[-5], closes[-2])
    body = abs(x["c"] - x["o"])
    rng = max(x["h"] - x["l"], 1e-12)
    body_fraction = body / rng

    long_weak_score = 0
    short_weak_score = 0
    if last_ret <= 0:
        long_weak_score += 1
    if last_ret >= 0:
        short_weak_score += 1
    if prev_mom3 > 0 and mom3 < prev_mom3 * 0.55:
        long_weak_score += 1
    if prev_mom3 < 0 and mom3 > prev_mom3 * 0.55:
        short_weak_score += 1
    if x["c"] < x["o"] and body_fraction >= 0.35:
        long_weak_score += 1
    if x["c"] > x["o"] and body_fraction >= 0.35:
        short_weak_score += 1
    if prev_ret > 0 and last_ret < prev_ret * 0.25:
        long_weak_score += 1
    if prev_ret < 0 and last_ret > prev_ret * 0.25:
        short_weak_score += 1

    entry_side = 1 if local_low and not local_high else (-1 if local_high and not local_low else 0)
    pivot_type = "LOCAL_LOW" if entry_side == 1 else ("LOCAL_HIGH" if entry_side == -1 else None)
    pivot_price = p["l"] if entry_side == 1 else (p["h"] if entry_side == -1 else None)

    return {
        "ready": True,
        "policy": POLICY,
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "signal_candle_time": x["t"],
        "signal_candle_close_time": x["T"],
        "pivot_candle_time": p["t"],
        "pivot_type": pivot_type,
        "pivot_price": pivot_price,
        "entry_side": entry_side,
        "local_low": local_low,
        "local_high": local_high,
        "long_weakening": long_weak_score >= 2,
        "short_weakening": short_weak_score >= 2,
        "long_weak_score": long_weak_score,
        "short_weak_score": short_weak_score,
        "last_h1_return": last_ret,
        "previous_h1_return": prev_ret,
        "momentum_3h": mom3,
        "previous_momentum_3h": prev_mom3,
        "confirmation_close": x["c"],
        "closed_candles": len(candles),
    }


def position_exit(position, analysis, mark):
    if not position or not analysis.get("ready"):
        return None
    side = int(position.get("side", 0))
    entry = _f(position.get("entry"))
    mark = _f(mark)
    if side not in (-1, 1) or entry is None or mark is None:
        return None
    # The candle that opened a position cannot also be a new H1 exit signal
    # on the next poll. Wait for a later completed candle.
    entry_candle = position.get("signal_candle_time")
    signal_candle = analysis.get("signal_candle_time")
    if entry_candle is not None and signal_candle is not None and signal_candle <= entry_candle:
        return None

    if side > 0 and analysis.get("local_high"):
        return "opposite_local_high"
    if side < 0 and analysis.get("local_low"):
        return "opposite_local_low"

    favorable = side * (mark / entry - 1.0)
    features = position.get("features") or {}
    peak_favorable = max(0.0, float(features.get("mfe_price_move", 0.0) or 0.0))
    enough_move = max(favorable, peak_favorable) >= MIN_FAVORABLE_MOVE_FOR_WEAKENING
    if enough_move:
        if side > 0 and analysis.get("long_weakening"):
            return "h1_momentum_weakening"
        if side < 0 and analysis.get("short_weakening"):
            return "h1_momentum_weakening"
    return None


def update_path(position, mark):
    out = dict(position or {})
    mark = _f(mark)
    entry = _f(out.get("entry"))
    side = int(out.get("side", 0) or 0)
    lev = _f(out.get("leverage")) or LEVERAGE
    features = dict(out.get("features") or {})
    if mark is None or entry is None or side not in (-1, 1):
        return out, False
    move = side * (mark / entry - 1.0)
    roe = move * lev
    prior_mfe = max(0.0, float(features.get("mfe_price_move", 0.0) or 0.0))
    peak_move = max(prior_mfe, move)
    features["mfe_price_move"] = peak_move
    features["mae_price_move"] = min(float(features.get("mae_price_move", 0.0) or 0.0), move)
    features["mfe_roe_pct"] = max(float(features.get("mfe_roe_pct", 0.0) or 0.0), roe * 100.0)
    features["mae_roe_pct"] = min(float(features.get("mae_roe_pct", 0.0) or 0.0), roe * 100.0)
    if bool(features.get("profit_lock_armed")) or peak_move >= PROFIT_LOCK_ARM_MOVE:
        features["profit_lock_armed"] = True
        features["profit_lock_stop"] = entry * (1.0 + side * PROFIT_LOCK_BUFFER_MOVE)
        features["profit_lock_arm_move_pct"] = PROFIT_LOCK_ARM_MOVE * 100.0
        features["profit_lock_buffer_move_pct"] = PROFIT_LOCK_BUFFER_MOVE * 100.0
    else:
        features["profit_lock_armed"] = False
    features["last_mark"] = mark
    features["last_gross_roe_pct"] = roe * 100.0
    out["features"] = features
    return out, roe <= LIQUIDATION_PROXY_ROE


def profit_lock_exit(position, mark):
    if not position:
        return None
    mark = _f(mark)
    entry = _f(position.get("entry"))
    side = int(position.get("side", 0) or 0)
    features = position.get("features") or {}
    stop = _f(features.get("profit_lock_stop"))
    if mark is None or entry is None or side not in (-1, 1):
        return None
    if not bool(features.get("profit_lock_armed")) or stop is None:
        return None
    if side > 0 and mark <= stop:
        return stop
    if side < 0 and mark >= stop:
        return stop
    return None


def shadow_triggers(side, analysis):
    if side > 0:
        return {
            "extreme": bool(analysis.get("local_high")),
            "weakening": bool(analysis.get("long_weakening")),
        }
    if side < 0:
        return {
            "extreme": bool(analysis.get("local_low")),
            "weakening": bool(analysis.get("short_weakening")),
        }
    return {"extreme": False, "weakening": False}
