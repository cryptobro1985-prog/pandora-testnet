"""Shared causal minute history encoder; no offline teacher is imported here.

Only completed bars whose availability is at/before prediction time enter this
encoder. Missing intervals invalidate the affected window. Price path summaries
provide a small, reproducible temporal model suitable for the 76 mature events.
"""
from __future__ import annotations

import bisect
import math
import statistics

MINUTE = 60_000
HOUR = 60 * MINUTE
TEMPORAL_KEYS = ("m1__retrace_bps", "m1__rev_ret_3m_bps",
                 "m1__rev_ret_5m_bps", "m1__volatility_60m_bps",
                 "m1__position_60m", "m1__range_5m_bps")


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def causal_completed_minute_features(side, age_s, extreme_price, rows, ts_ms):
    """Encode sorted or unsorted OHLC mappings, requiring full one-minute bars.

    Rows require start_ms/open/high/low/close. Optional bar_end_ms/ts_ms and
    received_ts_ms/source_ts_ms are checked when supplied. No volume/order-flow
    field is fitted: exchange candles and trade archive flow are different feeds.
    """
    ts_ms = int(ts_ms)
    rev = 1.0 if side == "LOW" else -1.0
    good = {}
    for row in rows:
        start = int(row.get("start_ms", -1))
        end = int(row.get("bar_end_ms", start + MINUTE))
        available = max(end, int(row.get("ts_ms", end) or end),
                        int(row.get("available_at_ms", end) or end),
                        int(row.get("received_ts_ms", end) or end),
                        int(row.get("source_timestamp_ms", end) or end),
                        int(row.get("source_ts_ms", end) or end))
        if start < 0 or start % MINUTE or end != start + MINUTE or available > ts_ms:
            continue
        if row.get("gap") or row.get("confirm") is False:
            continue
        if not all(_finite(row.get(k)) for k in ("open", "high", "low", "close")):
            continue
        if min(row[k] for k in ("open", "high", "low", "close")) <= 0:
            continue
        if row["low"] > min(row["open"], row["close"]) or row["high"] < max(row["open"], row["close"]):
            continue
        good[start] = row
    bars = [good[k] for k in sorted(good)]
    out = {"m1__side": rev, "m1__age_s": max(0.0, float(age_s))}
    if not bars:
        return out
    last = bars[-1]
    end = int(last["start_ms"]) + MINUTE
    out["m1__bar_age_s"] = (ts_ms - end) / 1000.0
    if ts_ms - end > 90_000:
        return out
    close = float(last["close"])
    if _finite(extreme_price) and extreme_price > 0:
        out["m1__retrace_bps"] = rev * (close / extreme_price - 1.0) * 10000
    rng = max(float(last["high"]) - float(last["low"]), 1e-12)
    out.update({"m1__body_rev_bps": rev * (close / last["open"] - 1.0) * 10000,
                "m1__close_position": (close - last["low"]) / rng,
                "m1__upper_wick": (last["high"] - max(last["open"], close)) / rng,
                "m1__lower_wick": (min(last["open"], close) - last["low"]) / rng})
    for n in (1, 3, 5, 15, 60, 180, 360, 1440):
        part = bars[-n:]
        if len(part) != n or any(int(b["start_ms"]) - int(a["start_ms"]) != MINUTE
                                 for a, b in zip(part, part[1:])):
            continue
        lo = min(float(b["low"]) for b in part)
        hi = max(float(b["high"]) for b in part)
        label = f"{n}m"
        out[f"m1__rev_ret_{label}_bps"] = rev * (close / part[0]["open"] - 1) * 10000
        out[f"m1__range_{label}_bps"] = (hi / lo - 1) * 10000
        out[f"m1__position_{label}"] = (close - lo) / max(hi - lo, 1e-12)
        out[f"m1__distance_low_{label}_bps"] = (close / lo - 1) * 10000
        out[f"m1__distance_high_{label}_bps"] = (hi / close - 1) * 10000
        if n >= 3:
            returns = [(b["close"] / a["close"] - 1) * 10000 for a, b in zip(part, part[1:])]
            out[f"m1__volatility_{label}_bps"] = math.sqrt(statistics.mean(v*v for v in returns))
            path = sum(abs(b["close"] - a["close"]) for a, b in zip(part, part[1:]))
            out[f"m1__efficiency_{label}"] = rev * (close - part[0]["close"]) / max(path, 1e-12)
            signs = [1 if v > 0 else -1 for v in returns if v != 0]
            out[f"m1__reversals_{label}"] = float(sum(a != b for a, b in zip(signs, signs[1:])))
    if "m1__rev_ret_3m_bps" in out and "m1__rev_ret_15m_bps" in out:
        out["m1__acceleration_3_15m_bps"] = out["m1__rev_ret_3m_bps"] - out["m1__rev_ret_15m_bps"] / 5
    if "m1__rev_ret_5m_bps" in out and "m1__rev_ret_60m_bps" in out:
        out["m1__acceleration_5_60m_bps"] = out["m1__rev_ret_5m_bps"] - out["m1__rev_ret_60m_bps"] / 12
    return {k: float(v) for k, v in out.items() if _finite(v)}


def candidate_temporal_features(current, previous_snapshots):
    """Pure same-candidate stage deltas; only snapshots older than current age."""
    out = dict(current)
    age = float(current.get("m1__age_s", current.get("age_s", 0)))
    previous = [(int(stage), values) for stage, values in previous_snapshots.items()
                if int(stage) < age and int(stage) in (60, 180, 300)]
    if not previous:
        return out
    stage, values = max(previous, key=lambda item: item[0])
    elapsed = max(1.0, age - stage)
    out["seq__elapsed_s"] = elapsed
    for key in TEMPORAL_KEYS:
        if _finite(current.get(key)) and _finite(values.get(key)):
            out["seq__delta_" + key.removeprefix("m1__")] = float(current[key]) - float(values[key])
    return out


class MinuteFeatureIndex:
    """Bounded lookup used by the offline replay with the same live encoder."""
    def __init__(self, rows):
        self.rows = sorted(rows, key=lambda r: int(r["start_ms"]))
        self.ends = [int(r["start_ms"]) + MINUTE for r in self.rows]

    def features(self, side, age_s, extreme_price, ts_ms):
        stop = bisect.bisect_right(self.ends, int(ts_ms))
        return causal_completed_minute_features(side, age_s, extreme_price,
                                               self.rows[max(0, stop-1440):stop], ts_ms)
