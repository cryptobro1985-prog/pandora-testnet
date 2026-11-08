"""Label-blind causal minute candidate expansion for HYPE research.

Candidates are emitted from completed minute bars only.  A bar may satisfy
several trailing-extreme lookbacks, but it produces at most one candidate per
side; the satisfied lookbacks are attached as metadata.  No reference labels
or future bars enter generation.

Important timestamp contract:
- extreme_ts_ms is the recorded intrabar LOW/HIGH timestamp when available;
- signal_ts_ms is the time the completed bar became observable;
- on compact_1m data ts_ms == bar_end_ms, so no extra minute may be added.
"""
from __future__ import annotations

from collections import deque
from math import isfinite


def _completed_bar_signal_ts(bar, ts: int) -> int:
    """Return the first causal timestamp at which the whole bar is known."""
    if bar.get("bar_end_ms") is not None:
        return int(bar["bar_end_ms"])
    interval_ms = int(bar.get("interval_ms", 60000))
    return ts + interval_ms


def _extreme_ts(bar, side: str, fallback_ts: int) -> int:
    key = "low_ts_ms" if side == "LOW" else "high_ts_ms"
    value = bar.get(key)
    return int(value) if value is not None else fallback_ts


def generate_minute_candidates(rows, lookbacks=(5, 15, 60, 180, 360)):
    """Yield causal LOW/HIGH candidate events from sorted completed M1 bars.

    Each row requires ts_ms, low and high.  Lookback windows contain preceding
    completed bars only.  Multiple lookback hits on the same side/bar are
    deduplicated into a single event.

    For legacy/generic rows without bar_end_ms, ts_ms is treated as bar start
    and signal_ts_ms is ts_ms + interval_ms (default 60 seconds).  For the HYPE
    compact_1m artifact bar_end_ms is present and is used directly.
    """
    lookbacks = tuple(sorted({int(x) for x in lookbacks}))
    if not lookbacks or lookbacks[0] <= 0:
        raise ValueError("lookbacks must contain positive integers")

    history = deque(maxlen=max(lookbacks))
    previous_ts = None

    for bar in rows:
        ts = int(bar["ts_ms"])
        lo, hi = float(bar["low"]), float(bar["high"])

        if previous_ts is not None and ts <= previous_ts:
            raise ValueError("bars must have strictly increasing timestamps")
        if not (isfinite(lo) and isfinite(hi) and 0 < lo <= hi):
            raise ValueError("invalid OHLC extrema")

        prior_rows = list(history)
        low_hits = []
        high_hits = []

        for n in lookbacks:
            if len(prior_rows) < n:
                continue
            prior = prior_rows[-n:]
            if lo <= min(float(x["low"]) for x in prior):
                low_hits.append(n)
            if hi >= max(float(x["high"]) for x in prior):
                high_hits.append(n)

        signal_ts = _completed_bar_signal_ts(bar, ts)

        if low_hits:
            extreme_ts = _extreme_ts(bar, "LOW", ts)
            if extreme_ts > signal_ts:
                raise ValueError("LOW extreme timestamp cannot be after signal")
            yield {
                "side": "LOW",
                "extreme_ts_ms": extreme_ts,
                "signal_ts_ms": signal_ts,
                "extreme_price": lo,
                "lookback_m": max(low_hits),
                "lookbacks_m": low_hits,
                "source": "causal_completed_m1",
            }

        if high_hits:
            extreme_ts = _extreme_ts(bar, "HIGH", ts)
            if extreme_ts > signal_ts:
                raise ValueError("HIGH extreme timestamp cannot be after signal")
            yield {
                "side": "HIGH",
                "extreme_ts_ms": extreme_ts,
                "signal_ts_ms": signal_ts,
                "extreme_price": hi,
                "lookback_m": max(high_hits),
                "lookbacks_m": high_hits,
                "source": "causal_completed_m1",
            }

        history.append(bar)
        previous_ts = ts


def coverage(events, finalized_labels, tolerance_ms=60000):
    """Postfactum evaluation only; never feed this result to live generation."""
    events = list(events)
    matches = []
    for lab in finalized_labels:
        start = int(lab["extreme_interval_start_ms"])
        end = int(lab.get("extreme_interval_end_ms", start + 60000))
        same = [
            e
            for e in events
            if e["side"] == lab["side"]
            and start - tolerance_ms <= e["extreme_ts_ms"] <= end + tolerance_ms
        ]
        matches.append(
            {
                "label_id": lab["label_id"],
                "side": lab["side"],
                "covered": bool(same),
                "candidate_count": len(same),
            }
        )
    return {
        "finalized": len(matches),
        "covered": sum(x["covered"] for x in matches),
        "missing_ids": [x["label_id"] for x in matches if not x["covered"]],
        "matches": matches,
    }
