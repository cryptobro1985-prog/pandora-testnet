"""Label-blind causal minute candidate expansion for HYPE research.

Candidates are emitted when a completed minute establishes a new trailing
same-side extreme. No reference labels or future bars enter generation.
The downstream state machine must deduplicate repeated extreme updates.
"""
from __future__ import annotations

from collections import deque
from math import isfinite


def generate_minute_candidates(rows, lookbacks=(5, 15, 60, 180, 360)):
    """Yield causal LOW/HIGH candidate events from chronologically sorted bars.

    Each row requires ts_ms, low, high.  Lookback windows contain only
    preceding completed bars. Emission time is the close of the current bar,
    represented by signal_ts_ms; this must not be treated as the extreme tick.
    """
    history = deque(maxlen=max(lookbacks))
    previous_ts = None
    for bar in rows:
        ts = int(bar["ts_ms"])
        lo, hi = float(bar["low"]), float(bar["high"])
        if previous_ts is not None and ts <= previous_ts:
            raise ValueError("bars must have strictly increasing timestamps")
        if not (isfinite(lo) and isfinite(hi) and 0 < lo <= hi):
            raise ValueError("invalid OHLC extrema")
        for n in lookbacks:
            if len(history) < n:
                continue
            prior = list(history)[-n:]
            if lo <= min(float(x["low"]) for x in prior):
                yield {"side": "LOW", "extreme_ts_ms": ts,
                       "signal_ts_ms": ts + 60000, "extreme_price": lo,
                       "lookback_m": n, "source": "causal_completed_m1"}
            if hi >= max(float(x["high"]) for x in prior):
                yield {"side": "HIGH", "extreme_ts_ms": ts,
                       "signal_ts_ms": ts + 60000, "extreme_price": hi,
                       "lookback_m": n, "source": "causal_completed_m1"}
        history.append(bar)
        previous_ts = ts


def coverage(events, finalized_labels, tolerance_ms=60000):
    """Postfactum evaluation only; never feed this result to live generation."""
    events = list(events)
    matches = []
    for lab in finalized_labels:
        start = int(lab["extreme_interval_start_ms"])
        end = int(lab.get("extreme_interval_end_ms", start + 60000))
        same = [e for e in events if e["side"] == lab["side"] and
                start - tolerance_ms <= e["extreme_ts_ms"] <= end + tolerance_ms]
        matches.append({"label_id": lab["label_id"], "side": lab["side"],
                        "covered": bool(same), "candidate_count": len(same)})
    return {"finalized": len(matches), "covered": sum(x["covered"] for x in matches),
            "missing_ids": [x["label_id"] for x in matches if not x["covered"]],
            "matches": matches}
