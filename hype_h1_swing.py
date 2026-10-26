"""M15 local-swing PAPER strategy with H1 context.

Pure signal logic only. No exchange orders, credentials, networking or persistence.
Completed M15 pivots define long/short swing entries and reversals in both trend and
counter-trend corrections. H1 is informational context only and never blocks an M15 trade.
A mature partial M15 candle plus live flow can protect earned profit before the next pivot.
"""

import math

POLICY = "local_swing_m15_h1_context_v4"
SYMBOL = "HYPE"  # backwards-compatible primary symbol
SYMBOLS = ("HYPE", "NEAR")
INTERVAL = "15m"
M15_INTERVAL = "15m"
H1_CONTEXT_INTERVAL = "1h"
STARTING_EQUITY = 100.0
MARGIN_FRACTION = 0.25
LEVERAGE = 25.0
PIVOT_LOOKBACK = 4
MIN_FAVORABLE_MOVE_FOR_WEAKENING = 0.0015
PROFIT_LOCK_ARM_MOVE = 0.0025
PROFIT_LOCK_BUFFER_MOVE = 0.0012
M15_PROFIT_EXIT_MIN_MOVE = 0.0012
M15_PRESSURE_MIN_SCORE = 3
M15_RECOVERY_MIN_SCORE = 3
M15_PARTIAL_MIN_AGE_MS = 3 * 60 * 1000
REENTRY_WATCH_SECONDS = 2 * 3600
REENTRY_MAX_PER_SWING = 4
LIQUIDATION_PROXY_ROE = -0.95


def _f(value):
    try:
        x = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return x if math.isfinite(x) else None


def _completed(rows, now_ms, interval_ms):
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
        if not (interval_ms - 1000 <= T-t <= interval_ms and l <= min(o,c) <= max(o,c) <= h):
            continue
        if v is not None and v < 0:
            continue
        if T > float(now_ms) - 1000:
            continue
        out.append({"t": int(t), "T": int(T), "o": o, "h": h, "l": l, "c": c,
                    "v": 0.0 if v is None else v})
    out.sort(key=lambda x: x["t"])
    dedup = {x["t"]: x for x in out}
    return [dedup[k] for k in sorted(dedup)]


def completed_candles(rows, now_ms):
    return _completed(rows, now_ms, 900_000)


def completed_m15_candles(rows, now_ms):
    return _completed(rows, now_ms, 900_000)


def _ret(a, b):
    return (b / a - 1.0) if a and b else 0.0


def analyze(rows, now_ms, symbol=SYMBOL):
    candles = completed_candles(rows, now_ms)
    if len(candles) < PIVOT_LOOKBACK + 2:
        return {"ready": False, "reason": "insufficient_closed_m15_candles",
                "closed_candles": len(candles), "policy": POLICY, "symbol": symbol}
    if float(now_ms) - candles[-1]["T"] > 900_000 + 45_000:
        return {"ready": False, "reason": "stale_m15_history", "policy": POLICY, "symbol": symbol}
    recent = candles[-(PIVOT_LOOKBACK+2):]
    if any(abs(b["t"]-a["t"]-900_000)>1000 for a,b in zip(recent,recent[1:])):
        return {"ready": False, "reason": "gapped_m15_history", "policy": POLICY, "symbol": symbol}

    x = candles[-1]
    p = candles[-2]
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
        "symbol": symbol,
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
        "last_m15_return": last_ret,
        "previous_m15_return": prev_ret,
        "momentum_45m": mom3,
        "previous_momentum_45m": prev_mom3,
        "confirmation_close": x["c"],
        "closed_candles": len(candles),
    }


def analyze_h1_context(rows, now_ms, symbol=SYMBOL):
    candles = _completed(rows, now_ms, 3_600_000)
    if len(candles) < 5:
        return {"ready": False, "reason": "insufficient_h1_context", "symbol": symbol}
    if float(now_ms) - candles[-1]["T"] > 3_600_000 + 120_000:
        return {"ready": False, "reason": "stale_h1_context", "symbol": symbol}
    closes=[x["c"] for x in candles]
    r1=_ret(closes[-2],closes[-1])
    r4=_ret(closes[-5],closes[-1])
    trend_side=1 if r4>0 else (-1 if r4<0 else 0)
    return {"ready": True, "symbol": symbol, "interval": H1_CONTEXT_INTERVAL,
            "trend_side": trend_side, "return_1h": r1, "return_4h": r4,
            "context_only": True, "blocks_m15_entries": False,
            "last_candle_time": candles[-1]["t"]}


def _usable_m15(rows, now_ms):
    candles = completed_m15_candles(rows, now_ms)
    current = None
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        t, T = _f(row.get("t")), _f(row.get("T"))
        o, h, l, c = (_f(row.get(k)) for k in ("o", "h", "l", "c"))
        v = _f(row.get("v"))
        if None in (t, T, o, h, l, c) or min(o,h,l,c) <= 0:
            continue
        if not (899_000 <= T-t <= 900_000 and l <= min(o,c) <= max(o,c) <= h):
            continue
        if t <= float(now_ms) < T and float(now_ms)-t >= M15_PARTIAL_MIN_AGE_MS:
            current = {"t": int(t), "T": int(T), "o": o, "h": h, "l": l, "c": c,
                       "v": 0.0 if v is None else max(0.0, v), "partial": True,
                       "age_ms": int(float(now_ms)-t)}
    if current and (not candles or current["t"] > candles[-1]["t"]):
        return candles + [current]
    return candles


def analyze_m15(rows, now_ms, side):
    side = int(side or 0)
    candles = _usable_m15(rows, now_ms)
    if side not in (-1, 1) or len(candles) < 5:
        return {"ready": False, "reason": "insufficient_m15_data", "side": side,
                "closed_or_mature_candles": len(candles), "policy": POLICY}
    x = candles[-1]
    prev = candles[-2]
    r1 = _ret(prev["c"], x["c"])
    r2 = _ret(candles[-3]["c"], x["c"])
    rng = max(x["h"]-x["l"], 1e-12)
    body_fraction = abs(x["c"]-x["o"]) / rng
    candle_dir = 1 if x["c"] > x["o"] else (-1 if x["c"] < x["o"] else 0)
    close_location = (x["c"]-x["l"]) / rng
    prior_volumes = [z.get("v",0.0) for z in candles[-9:-1] if z.get("v",0.0) > 0]
    avg_v = sum(prior_volumes)/len(prior_volumes) if prior_volumes else 0.0
    volume_ratio = (x.get("v",0.0)/avg_v) if avg_v > 0 else None

    adverse_score = 0
    if side*r1 <= -0.0015:
        adverse_score += 1
    if side*r2 <= -0.0025:
        adverse_score += 1
    if candle_dir == -side and body_fraction >= 0.50:
        adverse_score += 1
    if (side > 0 and close_location <= 0.30) or (side < 0 and close_location >= 0.70):
        adverse_score += 1
    if volume_ratio is not None and volume_ratio >= 1.35:
        adverse_score += 1

    recovery_score = 0
    if side*r1 >= 0.0012:
        recovery_score += 1
    if side*r2 >= 0.0020:
        recovery_score += 1
    if candle_dir == side and body_fraction >= 0.42:
        recovery_score += 1
    if (side > 0 and close_location >= 0.65) or (side < 0 and close_location <= 0.35):
        recovery_score += 1
    if volume_ratio is not None and volume_ratio >= 0.90:
        recovery_score += 1

    return {
        "ready": True,
        "policy": POLICY,
        "interval": M15_INTERVAL,
        "side": side,
        "candle_time": x["t"],
        "candle_close_time": x["T"],
        "partial": bool(x.get("partial")),
        "partial_age_seconds": round(float(x.get("age_ms",0))/1000.0,1) if x.get("partial") else None,
        "return_15m": r1,
        "return_30m": r2,
        "body_fraction": body_fraction,
        "close_location": close_location,
        "volume_ratio": volume_ratio,
        "adverse_score": adverse_score,
        "recovery_score": recovery_score,
        "strong_adverse_pressure": adverse_score >= M15_PRESSURE_MIN_SCORE and side*r1 < 0,
        "recovery_confirmed": recovery_score >= M15_RECOVERY_MIN_SCORE and side*r1 > 0,
    }


def m15_profit_protection(position, m15, mark, flow_imbalance=None):
    if not position or not m15 or not m15.get("ready"):
        return False
    side = int(position.get("side",0) or 0)
    entry = _f(position.get("entry"))
    mark = _f(mark)
    if side not in (-1,1) or entry is None or mark is None:
        return False
    favorable = side*(mark/entry-1.0)
    if favorable < M15_PROFIT_EXIT_MIN_MOVE:
        return False
    adverse = bool(m15.get("strong_adverse_pressure"))
    flow_confirms = False
    fi = _f(flow_imbalance)
    if fi is not None:
        flow_confirms = side*fi <= -0.10
    return adverse and (int(m15.get("adverse_score",0)) >= 4 or flow_confirms)


def m15_reentry_ready(side, m15, flow_imbalance=None):
    if int(side or 0) not in (-1,1) or not m15 or not m15.get("ready"):
        return False
    if not bool(m15.get("recovery_confirmed")):
        return False
    fi = _f(flow_imbalance)
    return int(m15.get("recovery_score",0)) >= 4 or fi is None or int(side)*fi >= 0.06


def position_exit(position, analysis, mark):
    if not position or not analysis.get("ready"):
        return None
    side = int(position.get("side", 0))
    entry = _f(position.get("entry"))
    mark = _f(mark)
    if side not in (-1, 1) or entry is None or mark is None:
        return None
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
            return "m15_momentum_weakening"
        if side < 0 and analysis.get("short_weakening"):
            return "m15_momentum_weakening"
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
