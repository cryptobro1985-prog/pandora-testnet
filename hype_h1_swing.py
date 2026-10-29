"""H1 local-extreme direction with M15 execution and recovery re-entry.

Pure signal logic only. No exchange orders, credentials, networking or persistence.
Confirmed H1 extrema define the direction until the opposite H1 extreme.
M15 pressure manages protective exits and same-direction recovery entries.
A mature partial M15 candle plus live flow can protect earned profit before the next pivot.
"""

import math
import statistics

POLICY = "local_swing_h1_durable_4x4_m5_execution_v13"
SYMBOL = "HYPE"  # backwards-compatible primary symbol
SYMBOLS = ("HYPE", "NEAR")
INTERVAL = "1h"
M15_INTERVAL = "15m"
H1_CONTEXT_INTERVAL = "1h"
STARTING_EQUITY = 100.0
MARGIN_FRACTION = 0.25
LEVERAGE = 25.0
PIVOT_LOOKBACK = 4
PIVOT_CONFIRM_RIGHT = 4  # require a durable H1 extreme; prefer missing a turn to a false local
MIN_FAVORABLE_MOVE_FOR_WEAKENING = 0.0015
PROFIT_LOCK_ARM_MOVE = 0.0025
PROFIT_LOCK_BUFFER_MOVE = 0.0012
M15_PROFIT_EXIT_MIN_MOVE = 0.0012
M15_PRESSURE_MIN_SCORE = 3
M15_RECOVERY_MIN_SCORE = 3
M15_PARTIAL_MIN_AGE_MS = 3 * 60 * 1000
REENTRY_WATCH_SECONDS = 0  # H1 anchor remains active until opposite pivot
REENTRY_MAX_PER_SWING = 0  # no arbitrary count limit within an H1 swing
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
    return _completed(rows, now_ms, 3_600_000)


def completed_m15_candles(rows, now_ms):
    return _completed(rows, now_ms, 900_000)


def _ret(a, b):
    return (b / a - 1.0) if a and b else 0.0


def _analyze_h1_pivot(rows, now_ms, symbol=SYMBOL):
    candles = completed_candles(rows, now_ms)
    need = PIVOT_LOOKBACK + PIVOT_CONFIRM_RIGHT + 1
    if len(candles) < need:
        return {"ready": False, "reason": "insufficient_closed_h1_candles",
                "closed_candles": len(candles), "policy": POLICY, "symbol": symbol}
    if float(now_ms) - candles[-1]["T"] > 3_600_000 + 120_000:
        return {"ready": False, "reason": "stale_h1_history", "policy": POLICY, "symbol": symbol}
    recent = candles[-need:]
    if any(abs(b["t"]-a["t"]-3_600_000)>1000 for a,b in zip(recent,recent[1:])):
        return {"ready": False, "reason": "gapped_h1_history", "policy": POLICY, "symbol": symbol}

    p_index = len(candles) - PIVOT_CONFIRM_RIGHT - 1
    p = candles[p_index]
    prior = candles[p_index-PIVOT_LOOKBACK:p_index]
    right = candles[p_index+1:p_index+1+PIVOT_CONFIRM_RIGHT]
    x = right[-1]
    prior_lows = [z["l"] for z in prior]
    prior_highs = [z["h"] for z in prior]

    # Symmetric durable pivot: four bars before establish the extreme and four
    # fully closed bars after it must preserve that extreme. A one-hour recoil
    # is only a candidate and must never flip Strategy 1 direction.
    local_low = (
        p["l"] <= min(prior_lows)
        and all(z["l"] > p["l"] for z in right)
    )
    local_high = (
        p["h"] >= max(prior_highs)
        and all(z["h"] < p["h"] for z in right)
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

    return {"ready": False, "reason": "insufficient_closed_h1_candles",
                "closed_candles": len(candles), "policy": POLICY, "symbol": symbol}
    if float(now_ms) - candles[-1]["T"] > 3_600_000 + 120_000:
        return {"ready": False, "reason": "stale_h1_history", "policy": POLICY, "symbol": symbol}
    recent = candles[-(PIVOT_LOOKBACK+2):]
    if any(abs(b["t"]-a["t"]-3_600_000)>1000 for a,b in zip(recent,recent[1:])):
        return {"ready": False, "reason": "gapped_h1_history", "policy": POLICY, "symbol": symbol}

    x = candles[-1]
    p = candles[-2]
    prior = candles[-2-PIVOT_LOOKBACK:-2]
    prior_lows = [z["l"] for z in prior]
    prior_highs = [z["h"] for z in prior]

    local_low = (
        p["l"] <= min(prior_lows)
        and x["l"] > p["l"]
    )
    local_high = (
        p["h"] >= max(prior_highs)
        and x["h"] < p["h"]
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
        "signal_candle_time": right[-1]["t"],
        "signal_candle_close_time": right[-1]["T"],
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
        "confirmation_close": right[-1]["c"],
        "closed_candles": len(candles),
    }


def analyze(rows, now_ms, symbol=SYMBOL):
    """Last causally confirmed H1 extreme, held across subsequent H1 candles.

    A pivot is known only after four following H1 candles have closed without breaching it. Reconstructing
    the latest pivot from closed history also keeps the bias stable after restart.
    """
    latest = _analyze_h1_pivot(rows, now_ms, symbol)
    if not latest.get("ready"):
        return latest
    candles = completed_candles(rows, now_ms)
    anchor = None
    for end in range(PIVOT_LOOKBACK + PIVOT_CONFIRM_RIGHT + 1, len(candles) + 1):
        sample = candles[:end]
        candidate = _analyze_h1_pivot(sample, sample[-1]["T"] + 1001, symbol)
        if candidate.get("ready") and candidate.get("entry_side") in (-1, 1):
            anchor = candidate
    result = dict(anchor or latest)
    result.update(last_candle_time=candles[-1]["t"], closed_candles=len(candles),
                  h1_direction_anchor=True, execution_interval=M15_INTERVAL,
                  anchor_confirmed=bool(anchor))

    # A confirmed H1 pivot is usable only while its own extreme remains intact.
    # If price later trades through a LOCAL_LOW/LOCAL_HIGH, that anchor was not
    # the durable swing extreme we require for Strategy 1. Go neutral instead
    # of carrying a stale directional bias until an opposite pivot appears.
    side = int(result.get("entry_side") or 0)
    pivot = _f(result.get("pivot_price"))
    signal_t = result.get("signal_candle_time")
    broken = False
    broken_at = None
    if side in (-1, 1) and pivot is not None and signal_t is not None:
        for z in candles:
            if z["t"] <= int(signal_t):
                continue
            if side > 0 and z["l"] < pivot:
                broken, broken_at = True, z["t"]
                break
            if side < 0 and z["h"] > pivot:
                broken, broken_at = True, z["t"]
                break

        # Also treat a live breach in the current H1 candle as invalidation.
        # We do not flip direction early; we simply block the stale side.
        current = _completed(rows, float(now_ms) + 3_600_001, 3_600_000)
        for z in current:
            if z["t"] <= candles[-1]["t"] or not (z["t"] <= now_ms < z["T"] + 1001):
                continue
            if side > 0 and z["l"] < pivot:
                broken, broken_at = True, z["t"]
            if side < 0 and z["h"] > pivot:
                broken, broken_at = True, z["t"]

    if broken:
        result.update(
            anchor_invalidated=True,
            anchor_invalidated_at=broken_at,
            anchor_invalidation_reason="pivot_extreme_breached",
            previous_entry_side=side,
            entry_side=0,
            entry_blocked=True,
            entry_block_reason="h1_pivot_extreme_breached_wait_new_confirmed_local",
        )
        return result

    result.update(anchor_invalidated=False)
    result.update(pending_extreme(rows, now_ms, result.get("entry_side", 0)))
    return result


def pending_extreme(rows, now_ms, side):
    """Pause old-side entries at a possible opposite H1 extreme, never flip early.

    The last closed H1 bar must set an extreme against its four predecessors.
    A live following bar must preserve that extreme and recoil by at least
    0.15%. Its final close is still required to confirm a new direction.
    """
    result = {"entry_blocked": False, "pending_pivot_type": None}
    candles = completed_candles(rows, now_ms)
    if side not in (-1, 1) or len(candles) < PIVOT_LOOKBACK + 1:
        return result
    p = candles[-1]
    prior = candles[-1-PIVOT_LOOKBACK:-1]
    current = _completed(rows, float(now_ms) + 3_600_001, 3_600_000)
    current = [x for x in current if x["t"] == p["t"] + 3_600_000 and x["t"] <= now_ms < x["T"] + 1001]
    if not current:
        return result
    x = current[-1]
    high = side > 0 and p["h"] >= max(z["h"] for z in prior) and x["h"] < p["h"] and (p["h"]-x["c"])/p["h"] >= .0015
    low = side < 0 and p["l"] <= min(z["l"] for z in prior) and x["l"] > p["l"] and (x["c"]-p["l"])/p["l"] >= .0015
    if high or low:
        result.update(entry_blocked=True, pending_pivot_type="LOCAL_HIGH" if high else "LOCAL_LOW",
                      pending_pivot_price=p["h"] if high else p["l"], pending_pivot_candle_time=p["t"],
                      entry_block_reason="opposite_h1_extreme_awaiting_closed_confirmation")
    return result


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
            "context_only": False, "blocks_m15_entries": True,
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
    if float(now_ms)-x["T"]>900000+120000:
        return {"ready":False,"reason":"stale_m15_history","side":side,"policy":POLICY}
    recent=candles[-5:]
    if any(abs(b["t"]-a["t"]-900000)>1000 for a,b in zip(recent,recent[1:])):
        return {"ready":False,"reason":"gapped_m15_history","side":side,"policy":POLICY}
    prev = candles[-2]
    r1 = _ret(prev["c"], x["c"])
    r2 = _ret(candles[-3]["c"], x["c"])
    rng = max(x["h"]-x["l"], 1e-12)
    body_fraction = abs(x["c"]-x["o"]) / rng
    candle_dir = 1 if x["c"] > x["o"] else (-1 if x["c"] < x["o"] else 0)
    close_location = (x["c"]-x["l"]) / rng
    prior_volumes = [z.get("v",0.0) for z in candles[-9:-1] if z.get("v",0.0) > 0]
    avg_v = sum(prior_volumes)/len(prior_volumes) if prior_volumes else 0.0
    raw_volume_ratio = (x.get("v",0.0)/avg_v) if avg_v > 0 else None
    # Compare rates when only part of the current candle has elapsed.
    # A three-minute candle must not be treated as a completed fifteen-minute volume.
    elapsed_fraction=min(1.,max(.001,float(x.get("age_ms",900000))/900000.))
    volume_ratio=raw_volume_ratio/elapsed_fraction if raw_volume_ratio is not None else None

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
        "observed_at_ms":int(now_ms),
        "partial": bool(x.get("partial")),
        "partial_age_seconds": round(float(x.get("age_ms",0))/1000.0,1) if x.get("partial") else None,
        "return_15m": r1,
        "return_30m": r2,
        "body_fraction": body_fraction,
        "candle_direction":candle_dir,
        "open_return":_ret(x["o"],x["c"]),
        "close_location": close_location,
        "volume_ratio": volume_ratio,
        "raw_volume_ratio":raw_volume_ratio,
        "median_range_move":statistics.median((z["h"]-z["l"])/z["c"] for z in candles[-9:-1]),
        "adverse_score": adverse_score,
        "recovery_score": recovery_score,
        "strong_adverse_pressure": adverse_score >= M15_PRESSURE_MIN_SCORE and (side*r1 < 0 or (candle_dir == -side and body_fraction >= .50)),
        "recovery_confirmed": recovery_score >= M15_RECOVERY_MIN_SCORE and (side*r1 > 0 or (candle_dir == side and body_fraction >= .42)),
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
    minimum=max(M15_PROFIT_EXIT_MIN_MOVE,_f((position.get("features") or {}).get("profit_lock_buffer_move")) or 0.)
    if favorable < minimum:
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
    # Candle scores must not override fresh executed flow strongly against entry.
    if fi is not None and int(side)*fi<=-0.10:
        return False
    return int(m15.get("recovery_score",0)) >= 4 or fi is None or int(side)*fi >= 0.06


def m15_reentry_after_exit(side, m15, mark, watch, flow_imbalance=None):
    if not m15_reentry_ready(side, m15, flow_imbalance):
        return False
    exit_price = _f((watch or {}).get("exit_price"))
    mark = _f(mark)
    return bool(exit_price and mark and int(side) * (mark / exit_price - 1.0) > 0)


def position_exit(position, analysis, mark):
    if not position or not analysis.get("ready"):
        return None
    side = int(position.get("side", 0))
    entry = _f(position.get("entry"))
    mark = _f(mark)
    if side not in (-1, 1) or entry is None or mark is None:
        return None
    if analysis.get("anchor_invalidated"):
        return "h1_pivot_extreme_breached"
    if analysis.get("h1_direction_anchor") and int(analysis.get("entry_side") or 0) == -side:
        return "opposite_local_high" if side > 0 else "opposite_local_low"
    entry_candle = position.get("signal_candle_time")
    signal_candle = analysis.get("signal_candle_time")
    if entry_candle is not None and signal_candle is not None and signal_candle <= entry_candle:
        return None

    if side > 0 and analysis.get("local_high"):
        return "opposite_local_high"
    if side < 0 and analysis.get("local_low"):
        return "opposite_local_low"

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
    arm=_f(features.get("profit_lock_arm_move")) or PROFIT_LOCK_ARM_MOVE
    buffer=_f(features.get("profit_lock_buffer_move")) or PROFIT_LOCK_BUFFER_MOVE
    if bool(features.get("profit_lock_armed")) or peak_move >= arm:
        features["profit_lock_armed"] = True
        lock_move=buffer if features.get("profit_lock_mode")=="fixed_cost_aware_breakeven" else max(buffer, peak_move * 0.50)
        candidate=entry * (1.0 + side * lock_move)
        old=_f(features.get("profit_lock_stop"))
        features["profit_lock_stop"]=max(old,candidate) if old is not None and side>0 else min(old,candidate) if old is not None else candidate
        features["profit_lock_arm_move_pct"] = arm * 100.0
        features["profit_lock_buffer_move_pct"] = buffer * 100.0
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
        return mark
    if side < 0 and mark >= stop:
        return mark
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
