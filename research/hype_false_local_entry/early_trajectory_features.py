"""Label-blind HYPE M1 trajectories from observed prices and executed flow.

A row can only be acted on when its final minute has closed. A same-side
extension anywhere in that minute takes precedence over the older candidate.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import NamedTuple

import numpy as np

from research.hype_quant.feature_contract import INPUT_IDS, METADATA_IDS, TARGET_IDS

MINUTE = 60_000
HOUR = 60 * MINUTE
AGES_S = (60, 180, 300, 600, 900, 1800)
SIDES = ("LOW", "HIGH")
# Dependency allowlist. Tape row keys outside the allowlist never reach a feature.
SOURCE_IDS = {
    "start_ms": 4, "bar_end_ms": 4, "ts_ms": 4,
    "open": 4, "high": 4, "low": 4, "close": 4,
    "high_ts_ms": 77, "low_ts_ms": 77,
    "buy_notional": 17, "sell_notional": 18, "max_trade_notional": 16,
    "gap": 79, "flow_observed": 116,
}
assert set(SOURCE_IDS.values()) <= INPUT_IDS - (TARGET_IDS | METADATA_IDS)


class Tape(NamedTuple):
    start: np.ndarray
    end: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    high_ts: np.ndarray
    low_ts: np.ndarray
    buy: np.ndarray
    sell: np.ndarray
    max_trade: np.ndarray
    gap: np.ndarray


def tape_from_rows(rows: Iterable[dict]) -> Tape:
    """Require completed, ordered M1 bars and keep unobserved flow missing."""
    rows = [{key: row[key] for key in SOURCE_IDS if key in row} for row in rows]
    start = np.array([r["start_ms"] for r in rows], dtype=np.int64)
    end = np.array([r["bar_end_ms"] for r in rows], dtype=np.int64)
    observed = np.array([r["ts_ms"] for r in rows], dtype=np.int64)
    if np.any(start % MINUTE) or np.any(end - start != MINUTE) or np.any(observed != end):
        raise ValueError("expected UTC-aligned completed M1 with ts_ms == bar_end_ms")
    if np.any(start[1:] < end[:-1]):
        raise ValueError("overlapping or unsorted M1 bars")

    def prices(key):
        return np.array([r[key] for r in rows], dtype=float)

    low, high, close, op = map(prices, ("low", "high", "close", "open"))
    gap = np.array([r.get("gap", False) for r in rows], dtype=bool)
    bad_price = (
        ~np.isfinite(low) | ~np.isfinite(high) | ~np.isfinite(close) | ~np.isfinite(op)
        | (low <= 0) | (low > high) | (close < low) | (close > high)
        | (op < low) | (op > high)
    )
    if np.any(bad_price & ~gap):
        raise ValueError("invalid observed OHLC")

    def times(key):
        return np.array([r.get(key, -1) for r in rows], dtype=np.int64)

    low_ts, high_ts = map(times, ("low_ts_ms", "high_ts_ms"))
    for stamps in (low_ts, high_ts):
        if np.any(((stamps < start) | (stamps >= end)) & ~gap):
            raise ValueError("missing or invalid intraminute extreme time")

    def amounts(key):
        values = np.array(
            [r.get(key, np.nan) if r.get("flow_observed", True) else np.nan for r in rows],
            dtype=float,
        )
        values[(values < 0) | ~np.isfinite(values)] = np.nan
        return values

    return Tape(start, end, high, low, close, high_ts, low_ts,
                amounts("buy_notional"), amounts("sell_notional"),
                amounts("max_trade_notional"), gap)


def segments(tape: Tape) -> Iterator[tuple[int, int]]:
    valid = np.flatnonzero(~tape.gap)
    breaks = np.flatnonzero(np.diff(tape.start[valid]) != MINUTE) + 1
    for chunk in np.split(valid, breaks):
        if chunk.size:
            yield int(chunk[0]), int(chunk[-1]) + 1


def ready_at(start_ms: int) -> int:
    """Start of the first hour with six consecutive completed reference hours."""
    return ((int(start_ms) + HOUR - 1) // HOUR + 6) * HOUR


def side_candidates(oriented: np.ndarray, start: int, stop: int) -> np.ndarray:
    """Return new H1 running extrema beyond the six prior completed H1s."""
    previous_extreme = np.max(oriented[start - 360:start])
    path = oriented[start:stop]
    prior = np.maximum.accumulate(np.r_[previous_extreme, path])[:-1]
    return start + np.flatnonzero(path > prior)


def flow_stats(returns, new, old, largest):
    """Observed bps of movement per $100k of each side's executed notional."""
    new_total, old_total = float(np.sum(new)), float(np.sum(old))
    total = new_total + old_total
    if not np.isfinite(total) or total <= 0:
        return (np.nan,) * 4
    new_eff = float(np.maximum(returns, 0).sum()) * 100_000 / new_total if new_total else np.nan
    old_eff = float(np.maximum(-returns, 0).sum()) * 100_000 / old_total if old_total else np.nan
    share = float(np.max(largest)) / total
    return new_eff, old_eff, (new_total - old_total) / total, share


def trajectories(tape: Tape) -> Iterator[dict]:
    for start, stop in segments(tape):
        yield from segment_trajectories(tape, start, stop)


def segment_trajectories(tape: Tape, start: int, stop: int) -> Iterator[dict]:
    first = int(np.searchsorted(tape.start, ready_at(tape.start[start])))
    if first >= stop:
        return
    log_close = np.log(tape.close[start:stop])
    returns = np.r_[np.nan, np.diff(log_close)] * 10_000
    for side in SIDES:
        sign = 1 if side == "LOW" else -1
        extreme, stamps = (tape.low, tape.low_ts) if side == "LOW" else (tape.high, tape.high_ts)
        new, old = (tape.buy, tape.sell) if side == "LOW" else (tape.sell, tape.buy)
        oriented = -sign * extreme
        signed_returns = sign * returns

        def stats(a, b):
            return flow_stats(signed_returns[a - start:b - start], new[a:b], old[a:b],
                              tape.max_trade[a:b])

        for hour in range(first, stop, 60):
            for i in side_candidates(oriented, hour, min(stop, hour + 60)):
                ts, price = int(stamps[i]), float(extreme[i])
                search_stop = min(stop, i + AGES_S[-1] // 60 + 2)
                extension = np.flatnonzero(oriented[i + 1:search_stop] > oriented[i])
                limit = i + 1 + int(extension[0]) if extension.size else search_stop
                pre_hi = float(tape.high[i - 60:i].max())
                pre_lo = float(tape.low[i - 60:i].min())
                pre_range = 10_000 * np.log(pre_hi / pre_lo)
                pre_rv = float(np.linalg.norm(returns[i - 60 - start:i - start]))
                pre_move = 10_000 * (np.log(pre_hi / price) if sign == 1 else np.log(price / pre_lo))
                _, pre_old_eff, _, _ = stats(i - 5, i)
                ends = tape.end[i:limit]
                for age in AGES_S:
                    k = i + int(np.searchsorted(ends, ts + age * 1000))
                    if k >= limit:
                        break
                    stamp = int(tape.end[k])
                    elapsed_min = (stamp - ts) / MINUTE
                    path = 10_000 * sign * (log_close[i - start:k + 1 - start] - np.log(price))
                    post = signed_returns[i + 1 - start:k + 1 - start]
                    retrace = float(path[-1])
                    row = {
                        "side": side, "candidate_id": f"{side}-{ts}", "age_s": age,
                        "candidate_ts_ms": ts, "signal_ts_ms": stamp, "price": price,
                        "signal_price": float(tape.close[k]),
                        "retrace_bps": 10_000 * sign * (float(tape.close[k]) / price - 1),
                        "retrace_range60": retrace / pre_range if pre_range > 0 else np.nan,
                        "retrace_rv60": retrace / pre_rv if pre_rv > 0 else np.nan,
                        "pre_move_rv60": pre_move / pre_rv if pre_rv > 0 else np.nan,
                        "return_slope_bps_min": retrace / elapsed_min,
                        "positive_bar_share": float(np.mean(post > 0)) if post.size else np.nan,
                        "retained_close_retrace": retrace / float(path.max()) if path.max() > 0 else 0.0,
                        "pre_old_eff": pre_old_eff,
                    }
                    if k - i >= 2:
                        mid = i + (k - i) // 2
                        early = float(path[mid - i] - path[0])
                        late = float(path[-1] - path[mid - i])
                        early_min = (mid - i)
                        late_min = (k - mid)
                        early_new, _, early_flow, early_share = stats(i + 1, mid + 1)
                        late_new, late_old, _, late_share = stats(mid + 1, k + 1)
                        row.update({
                            "late_slope_bps_min": late / late_min,
                            "return_accel_bps_min2": (late / late_min - early / early_min)
                            / ((early_min + late_min) / 2),
                            "old_side_failed_extension": early_flow < 0 and early >= 0,
                            "late_old_eff": late_old,
                            "late_new_eff": late_new,
                            "efficiency_slope": (late_new - early_new) / ((early_min + late_min) / 2),
                            "new_old_eff_ratio": late_new / late_old if late_old > 0 else np.nan,
                            "trade_concentration_delta": late_share - early_share,
                        })
                    yield row
