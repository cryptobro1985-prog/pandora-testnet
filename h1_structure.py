"""Causal closed-H1 structure and observed MFE/MAE statistics."""
import math
POLICY="closed_h1_causal_structure"
SYMBOL="BTC"
INTERVAL="1h"
PIVOT_LOOKBACK=4
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
    """Causal H1 swing structure; no future bars or percent retracement gate.

    An extreme exceeds the preceding four closed hours. A later closed bar
    confirms it only with a lower high (high), or higher low (low). An
    ambiguous simultaneous confirmation never chooses a direction. Ties
    extend the candidate. Confirmation records never move to an earlier time.
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
    high = low = anchor = None
    for i, bar in enumerate(candles):
        confirmations = []
        if high is not None:
            if bar["h"] >= high["h"]:
                high = None
            else:
                confirmations.append((-1, high))
                high = None
        if low is not None:
            if bar["l"] <= low["l"]:
                low = None
            else:
                confirmations.append((1, low))
                low = None
        # Never guess the ordering of two directions inside one hourly candle.
        if len(confirmations) == 1:
            side, pivot = confirmations[0]
            if anchor is None or pivot["t"] > anchor["pivot_candle_time"]:
                anchor = {
                    "entry_side": side, "pivot_type": "LOCAL_LOW" if side > 0 else "LOCAL_HIGH",
                    "pivot_price": pivot["l"] if side > 0 else pivot["h"],
                    "pivot_candle_time": pivot["t"], "signal_candle_time": bar["t"],
                    "signal_candle_close_time": bar["T"], "confirmation_close": bar["c"],
                    "confirmation_bars": (bar["t"]-pivot["t"])//3_600_000,
                    "pivot_confirmation_policy": "closed_h1_higher_low_after_extreme" if side > 0
                        else "closed_h1_lower_high_after_extreme",
                    "confirmation_evidence": {"pivot_high": pivot["h"], "pivot_low": pivot["l"],
                        "confirm_high": bar["h"], "confirm_low": bar["l"],
                        "preceding_hours": PIVOT_LOOKBACK},
                    "local_low": side > 0, "local_high": side < 0,
                }
        if i >= PIVOT_LOOKBACK:
            prior = candles[i-PIVOT_LOOKBACK:i]
            if bar["h"] >= max(x["h"] for x in prior):
                high = bar
            if bar["l"] <= min(x["l"] for x in prior):
                low = bar
    return {**base, "ready": True, "interval": INTERVAL,
            "entry_side": 0, "pivot_type": None, "pivot_price": None,
            "long_weakening": False, "short_weakening": False,
            **(anchor or {})}

def analyze(rows, now_ms, symbol=SYMBOL):
    """Last causally confirmed H1 swing, held until an opposite confirmed swing.

    A fresh high/low is only a candidate. It may keep extending for many H1 bars.
    The regime changes only after a CLOSED H1 retracement large enough relative
    to recent volatility. Reconstructing the latest confirmed swing from history
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
