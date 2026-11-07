"""Immutable, delayed labels for the historical strict H1 L6/K2 target.

OHLC cannot establish ordering when an hour is both a high and a low pivot.
Such targets are censored. A surviving same-side swing is finalized only after
an opposite mature pivot; the final unfinished swing remains pending.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

H = 3_600_000


@dataclass
class Pending:
    candidate_id: str
    side: str
    stage: int
    extreme_price: float
    extreme_ts_ms: int
    x: dict[str, float]
    mature_ms: int
    prediction_ts_ms: int = 0
    event_key: str = ""
    champion_probability: float = 0.5
    challenger_probability: float = 0.5
    champion_threshold: float = 0.5
    challenger_threshold: float = 0.5
    challenger_id: str = ""
    evidence: dict = field(default_factory=dict)

    @property
    def label_id(self):
        return f"label:{self.candidate_id}:{self.stage}"


def completed_h1(state, ts_ms):
    if hasattr(state, "available_candles"):
        values = state.available_candles("60", int(ts_ms), complete_only=True)
        values = values.values() if isinstance(values, dict) else values
    else:
        values = state.candles.get("60", {}).values()
    out = []
    for bar in values:
        try:
            start = int(bar["start_ms"])
            if start + H > ts_ms:
                continue
            # Legacy bars without receive provenance cannot establish a causal
            # teacher and must be reacquired. No fabricated timestamp fallback.
            received = int(bar.get("received_ts_ms") or 0)
            if received < start + H or received > ts_ms:
                continue
            if "confirm" in bar and not bar["confirm"]:
                continue
            vals = {name: float(bar[name]) for name in ("open", "high", "low", "close")}
            if not all(math.isfinite(v) and v > 0 for v in vals.values()):
                continue
            if not vals["low"] <= min(vals["open"], vals["close"]) <= max(vals["open"], vals["close"]) <= vals["high"]:
                continue
            out.append({"start_ms": start, "received_ts_ms": received, **vals})
        except (ValueError, TypeError, KeyError):
            continue
    return sorted(out, key=lambda bar: bar["start_ms"])


def pivot_catalog(state, ts_ms):
    rows = completed_h1(state, ts_ms)
    raw, collapsed, ambiguous = {}, [], set()
    for i in range(6, len(rows) - 2):
        window = rows[i - 6:i + 3]
        if any(b["start_ms"] != a["start_ms"] + H for a, b in zip(window, window[1:])):
            continue
        row, past, future = rows[i], rows[i - 6:i], rows[i + 1:i + 3]
        high = row["high"] > max(bar["high"] for bar in past) and row["high"] >= max(bar["high"] for bar in future)
        low = row["low"] < min(bar["low"] for bar in past) and row["low"] <= min(bar["low"] for bar in future)
        if high and low:
            ambiguous.add(row["start_ms"])
            continue
        if not high and not low:
            continue
        side = "HIGH" if high else "LOW"
        item = {"side": side, "price": row["high"] if high else row["low"],
                "hour_ms": row["start_ms"],
                "available_ms": max(row["start_ms"] + 3 * H, max(bar["received_ts_ms"] for bar in window))}
        raw[row["start_ms"]] = item
        if collapsed and collapsed[-1]["side"] == side:
            better = item["price"] > collapsed[-1]["price"] if high else item["price"] < collapsed[-1]["price"]
            if better:
                collapsed[-1] = item
        else:
            collapsed.append(item)
    for i, item in enumerate(collapsed):
        item["reference_finalized"] = i + 1 < len(collapsed)
        item["reference_finalized_ms"] = max(item["available_ms"], collapsed[i + 1]["available_ms"]) if i + 1 < len(collapsed) else None
    return rows, raw, collapsed, ambiguous


def strict_pivots(state, ts_ms):
    return pivot_catalog(state, ts_ms)[2]


def teacher_verdict(state, pending: Pending, ts_ms: int, catalog=None):
    """Return None while unknown, otherwise an auditable label/censor record."""
    if ts_ms < pending.mature_ms:
        return None
    rows, raw, collapsed, ambiguous = catalog or pivot_catalog(state, ts_ms)
    hour = pending.extreme_ts_ms // H * H
    index = {bar["start_ms"]: bar for bar in rows}
    required = [hour + step * H for step in range(-6, 3)]
    if any(start not in index for start in required):
        if ts_ms > pending.mature_ms + 7 * 24 * H:
            return {"label": None, "reason": "MISSING_H1_AFTER_7D", "hour_ms": hour}
        return None
    if hour in ambiguous:
        return {"label": None, "reason": "AMBIGUOUS_HIGH_LOW_ORDER", "hour_ms": hour}
    pivot = raw.get(hour)
    if not pivot or pivot["side"] != pending.side:
        return {"label": False, "reason": "NOT_STRICT_SIDE_PIVOT", "hour_ms": hour,
                "label_available_ms": max(hour + 3 * H, max(index[start]["received_ts_ms"] for start in required))}
    surviving = next((item for item in collapsed if item["hour_ms"] == hour), None)
    if surviving is None:
        return {"label": False, "reason": "SUPERSEDED_SAME_SIDE_SWING", "hour_ms": hour,
                "label_available_ms": ts_ms}
    if not surviving["reference_finalized"]:
        # Do not invent a negative for a terminal unfinished structural swing.
        return None
    instrument = getattr(state, "instrument", {}) or {}
    try:
        tick = float((instrument.get("priceFilter") or {}).get("tickSize", 0))
    except (ValueError, TypeError):
        tick = 0.0
    tolerance = max(abs(pivot["price"]) * 1e-9, tick * 0.5 if math.isfinite(tick) else 0.0)
    matches = abs(pending.extreme_price - pivot["price"]) <= tolerance
    return {"label": bool(matches), "reason": "FINALIZED_EXACT_EXTREME" if matches else "NOT_H1_EXTREME_PRICE",
            "hour_ms": hour, "true_extreme_price": pivot["price"],
            "label_available_ms": surviving["reference_finalized_ms"]}


def strict_label(state, pending, ts_ms):
    """Compatibility API: unknown/censored returns None, never false negatives."""
    verdict = teacher_verdict(state, pending, ts_ms)
    return None if verdict is None else verdict["label"]
