"""Causal closed-H1 structure and observed MFE/MAE statistics."""
import math
import statistics
POLICY="closed_h1_adaptive_swing_v16"
SYMBOL="BTC"
INTERVAL="1h"
PIVOT_LOOKBACK=4
H1_PIVOT_MIN_RETRACE=0.004
H1_PIVOT_RANGE_MULTIPLIER=0.75
H1_PIVOT_MAX_RETRACE=0.035
H1_PIVOT_SEARCH_BARS=24
LEVERAGE=25.

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

def _analyze_h1_pivot(rows, now_ms, symbol=SYMBOL, require_fresh=True):
    """Adaptive causal H1 swing reconstruction using CLOSED candles only.

    An extreme can extend for many H1 bars. The newest surviving candidate in
    the rolling window owns the setup. It becomes a confirmed opposite swing
    only after a volatility-normalized CLOSED-H1 retracement; a newer extreme
    invalidates the older candidate instead of creating a premature flip.
    """
    candles = completed_candles(rows, now_ms)
    base = {"ready": False, "symbol": symbol, "policy": POLICY,
            "closed_candles": len(candles)}
    if len(candles) < PIVOT_LOOKBACK + 2:
        return {**base, "reason": "insufficient_closed_h1_candles"}
    if require_fresh and float(now_ms) - candles[-1]["T"] > 3_600_000 + 120_000:
        return {**base, "reason": "stale_h1_history"}
    if any(b["t"]-a["t"] != 3_600_000 for a,b in zip(candles,candles[1:])):
        return {**base, "reason": "gapped_h1_history"}

    chosen = None
    newest = len(candles)-2
    oldest = max(PIVOT_LOOKBACK, len(candles)-1-H1_PIVOT_SEARCH_BARS)
    for p_idx in range(newest, oldest-1, -1):
        p = candles[p_idx]
        prior = candles[p_idx-PIVOT_LOOKBACK:p_idx]
        after = candles[p_idx+1:]
        if len(prior) < PIVOT_LOOKBACK or not after:
            continue
        candidate_low = p["l"] <= min(z["l"] for z in prior)
        candidate_high = p["h"] >= max(z["h"] for z in prior)
        if not (candidate_low or candidate_high):
            continue

        hist = candles[max(0,p_idx-12):p_idx]
        ranges = [(z["h"]-z["l"])/max(z["c"],1e-12) for z in hist]
        typical = statistics.median(ranges) if ranges else H1_PIVOT_MIN_RETRACE
        threshold = max(H1_PIVOT_MIN_RETRACE,
                        min(H1_PIVOT_MAX_RETRACE, typical*H1_PIVOT_RANGE_MULTIPLIER))

        low_valid, high_valid = bool(candidate_low), bool(candidate_high)
        low_confirm = high_confirm = None
        low_retrace = high_retrace = 0.0
        for z in after:
            if low_valid:
                if z["l"] <= p["l"]:
                    low_valid = False
                else:
                    r = z["c"]/p["l"]-1.0
                    low_retrace = max(low_retrace,r)
                    if low_confirm is None and r >= threshold:
                        low_confirm = z
            if high_valid:
                if z["h"] >= p["h"]:
                    high_valid = False
                else:
                    r = 1.0-z["c"]/p["h"]
                    high_retrace = max(high_retrace,r)
                    if high_confirm is None and r >= threshold:
                        high_confirm = z

        options=[]
        if low_valid and low_confirm is not None: options.append((int(low_confirm["t"]),1,low_confirm,low_retrace))
        if high_valid and high_confirm is not None: options.append((int(high_confirm["t"]),-1,high_confirm,high_retrace))
        if not options:
            continue
        # If one candle would ambiguously confirm both directions, do not guess
        # intrabar ordering. Otherwise use the first causal confirmation.
        if len(options)==2 and options[0][0]==options[1][0]:
            continue
        _, side, confirm, retrace = min(options,key=lambda x:x[0])
        chosen={"p":p,"side":side,"confirm":confirm,"threshold":threshold,
                "retrace":retrace,
                "candidate_low":candidate_low,"candidate_high":candidate_high}
        break

    result={**base,"ready":True,"interval":INTERVAL,"entry_side":0,
            "pivot_type":None,"pivot_price":None,"long_weakening":False,
            "short_weakening":False}
    if chosen is None:
        return result
    p=chosen["p"]; side=chosen["side"]; confirm=chosen["confirm"]
    result.update({
        "entry_side":side,
        "pivot_type":"LOCAL_LOW" if side>0 else "LOCAL_HIGH",
        "pivot_price":p["l"] if side>0 else p["h"],
        "pivot_candle_time":p["t"],
        "signal_candle_time":confirm["t"],
        "signal_candle_close_time":confirm["T"],
        "confirmation_close":confirm["c"],
        "confirmation_bars":max(1,int((confirm["t"]-p["t"])//3_600_000)),
        "required_retrace":chosen["threshold"],
        "confirmation_retrace":chosen["retrace"],
        "pivot_confirmation_policy":"closed_h1_adaptive_retrace_after_extending_extreme",
        "confirmation_evidence":{"pivot_high":p["h"],"pivot_low":p["l"],
            "confirm_high":confirm["h"],"confirm_low":confirm["l"],
            "preceding_hours":PIVOT_LOOKBACK,"search_hours":H1_PIVOT_SEARCH_BARS,
            "typical_range_multiplier":H1_PIVOT_RANGE_MULTIPLIER},
        "local_low":side>0,"local_high":side<0,
    })
    return result

def analyze(rows, now_ms, symbol=SYMBOL):
    """Last causally confirmed H1 swing, held until an opposite confirmed swing.

    A fresh high/low is only a candidate. It may keep extending for many H1 bars.
    The regime changes only after a CLOSED H1 retracement large enough relative
    to recent volatility; extending extremes keep moving the candidate. Reconstructing the latest confirmed swing from history
    keeps the bias stable after restart and prevents in-the-moment flip-flops.
    """
    latest = _analyze_h1_pivot(rows, now_ms, symbol)
    if not latest.get("ready"):
        return latest
    candles = completed_candles(rows, now_ms)
    anchor = latest if latest.get("entry_side") in (-1, 1) else None
    result = dict(latest)
    result.update(last_candle_time=candles[-1]["t"], closed_candles=len(candles),
                  h1_direction_anchor=True, execution_interval="executed trade stream",
                  anchor_confirmed=bool(anchor))
    result.update(pending_extreme(rows, now_ms, result.get("entry_side", 0), result.get("pivot_price")))
    return result

def pending_extreme(rows, now_ms, side, anchor_pivot_price=None):
    """Diagnostic-only candidate extreme; never blocks lower-timeframe execution.

    The confirmed H1 local is a persistent DIRECTION VECTOR until an opposite
    H1 swing is fully confirmed. Price may extend beyond the active local while
    the executed-flow caterpillar keeps exiting/re-entering in that same vector.
    Pending highs/lows are therefore displayed for context only and MUST NOT
    pause entries, exits or re-entries.
    """
    result = {"entry_blocked": False, "pending_pivot_type": None,
              "pending_pivot_price": None, "entry_block_reason": None,
              "pending_is_diagnostic_only": True}
    candles = completed_candles(rows, now_ms)
    if side not in (-1, 1) or len(candles) < PIVOT_LOOKBACK + 1:
        return result
    p = candles[-1]
    prior = candles[-1-PIVOT_LOOKBACK:-1]

    # A historical forming candle contains its eventual high/low. Do not read it
    # even for diagnostic output during causal replay.
    x = None

    anchor = _f(anchor_pivot_price)
    if anchor is not None and anchor > 0:
        if side > 0:
            newest_low = min(p["l"], x["l"] if x else p["l"])
            if newest_low < anchor:
                result.update(pending_pivot_type="LOCAL_LOW",
                              pending_pivot_price=newest_low,
                              pending_pivot_candle_time=x["t"] if x and x["l"] <= p["l"] else p["t"],
                              entry_block_reason="same_side_h1_low_extension_diagnostic_only")
                return result
        else:
            newest_high = max(p["h"], x["h"] if x else p["h"])
            if newest_high > anchor:
                result.update(pending_pivot_type="LOCAL_HIGH",
                              pending_pivot_price=newest_high,
                              pending_pivot_candle_time=x["t"] if x and x["h"] >= p["h"] else p["t"],
                              entry_block_reason="same_side_h1_high_extension_diagnostic_only")
                return result

    high = side > 0 and p["h"] >= max(z["h"] for z in prior) and (x is None or x["h"] < p["h"])
    low = side < 0 and p["l"] <= min(z["l"] for z in prior) and (x is None or x["l"] > p["l"])
    if high or low:
        result.update(pending_pivot_type="LOCAL_HIGH" if high else "LOCAL_LOW",
                      pending_pivot_price=p["h"] if high else p["l"],
                      pending_pivot_candle_time=p["t"],
                      entry_block_reason="opposite_h1_candidate_diagnostic_only")
    return result

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
    features["last_mark"] = mark
    features["last_gross_roe_pct"] = roe * 100.0
    out["features"] = features
    return out, False
