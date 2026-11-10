"""Label-blind dense M1 reachability layer for internal H1 turns.

This layer deliberately separates *candidate reachability* from *entry signals*.
Every completed minute contributes a LOW and HIGH observation, so a finalized
extreme recorded in compact_1m can be reached even if it is not a trailing
5/15/60-minute breakout. It must NOT be counted as a detected reversal.
The sequential state machine must still filter these observations causally.
"""
from __future__ import annotations

from bisect import bisect_left


def dense_completed_m1_candidates(rows):
    last_signal = None
    for bar in rows:
        interval = int(bar.get("interval_ms", 60000))
        explicit_end = bar.get("bar_end_ms")
        if bar.get("start_ms") is not None:
            start = int(bar["start_ms"])
        else:
            ts = int(bar["ts_ms"])
            # Canonical compact_1m stores ts_ms as the completed bar END.
            # Never add an extra minute when bar_end_ms is omitted.
            # Noncanonical start-stamped inputs must supply start_ms.
            start = int(explicit_end) - interval if explicit_end is not None else ts - interval
        end = int(explicit_end if explicit_end is not None else start + interval)
        if end <= start or (last_signal is not None and start < last_signal):
            raise ValueError("overlapping, incomplete, or nonmonotonic minute bars")
        last_signal = end
        low, high = float(bar["low"]), float(bar["high"])
        if not 0 < low <= high:
            raise ValueError("invalid minute extrema")
        for side, price, field in (("LOW", low, "low_ts_ms"), ("HIGH", high, "high_ts_ms")):
            extreme_ts = int(bar.get(field) or start)
            if not start <= extreme_ts < end:
                raise ValueError("intrabar extreme timestamp outside completed minute")
            yield dict(side=side, extreme_ts_ms=extreme_ts,
                       signal_ts_ms=end, interval_ms=interval, extreme_price=price,
                       source="dense_completed_m1", entry_signal=False)


def evaluate_reachability(events, finalized_labels, tolerance_ms=60000):
    """Offline-only matching. Labels must never enter live feature creation."""
    from collections import defaultdict
    index = defaultdict(list)
    for event in events:
        index[event["side"]].append(int(event["extreme_ts_ms"]))
    for side in index:
        index[side].sort()
    misses = []
    for label in finalized_labels:
        times = index[label["side"]]
        lo = int(label["extreme_interval_start_ms"]) - tolerance_ms
        hi = int(label.get("extreme_interval_end_ms", lo + tolerance_ms)) + tolerance_ms
        j = bisect_left(times, lo)
        if j == len(times) or times[j] > hi:
            misses.append(label["label_id"])
    return dict(finalized=len(finalized_labels),
                covered=len(finalized_labels)-len(misses),
                missing_ids=misses,
                note="Candidate reachability only; NOT detector recall or precision")
