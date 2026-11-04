"""Causal feature state for completed bars and timestamped forward observations.

Efficiencies are price-response proxies, not an attribution of price impact to
an aggressor. Book add/cancel deltas cannot identify executions or replenishment
by themselves. A replenishment ratio is returned only with explicit consumed
notional, never by relabelling cancellations as executed consumption.
"""
from __future__ import annotations

from collections import deque
import math

from .data import DataError, canonical_bar, number, timestamp_ms

HOUR = 3_600_000


class FeatureBuilder:
    def __init__(self, *, oi_max_age_ms=10_000, oi_horizon_tolerance_ms=10_000):
        self.bars = deque()
        self.h1 = deque(maxlen=168)
        self.oi = deque()
        self.oi_max_age_ms = oi_max_age_ms
        self.oi_horizon_tolerance_ms = oi_horizon_tolerance_ms
        self.previous = None
        self.partial = None
        self.completed_h1_count = 0
        self.oi_sampling_interval_ms = 0
        self.oi_publication_lag_ms = 0
        self.oi_availability_assumed = False

    def _hour(self, row):
        start, end = row["start_ms"], row["bar_end_ms"]
        hour = start // HOUR * HOUR
        # Coarse bars crossing an H1 boundary cannot establish individual H1 OHLC.
        if row["interval_ms"] > HOUR or end > hour + HOUR:
            self.partial = None
            return
        if self.partial is None or self.partial["start_ms"] != hour:
            self.partial = dict(start_ms=hour, next_ms=start, valid=start == hour,
                                open=row["open"], high=row["high"], low=row["low"], close=row["close"])
        p = self.partial
        p["valid"] = p["valid"] and p["next_ms"] == start
        p["high"] = max(p["high"], row["high"])
        p["low"] = min(p["low"], row["low"])
        p["close"] = row["close"]
        p["next_ms"] = end
        if end == hour + HOUR:
            if p["valid"]:
                previous_close = self.h1[-1]["close"] if self.h1 else p["open"]
                p["true_range"] = max(p["high"]-p["low"], abs(p["high"]-previous_close), abs(p["low"]-previous_close))
                p["ts_ms"] = row["ts_ms"]
                self.h1.append(dict(p))
                self.completed_h1_count += 1
            self.partial = None

    def _window(self, duration_ms, current):
        """Require exact, contiguous, fully observed bar coverage of the window."""
        end = current["bar_end_ms"]
        begin = end - duration_ms
        rows = [b for b in self.bars if b["bar_end_ms"] > begin and b["bar_end_ms"] <= end]
        if not rows or rows[0]["start_ms"] != begin or rows[-1]["bar_end_ms"] != end:
            return None
        if any(b["start_ms"] != a["bar_end_ms"] for a, b in zip(rows, rows[1:])):
            return None
        if any(not b["flow_observed"] for b in rows):
            return None
        return rows

    def _observe_oi(self, row):
        value = row.get("open_interest")
        source_ts = row.get("oi_ts_ms", row.get("open_interest_ts_ms"))
        if value is None or source_ts is None:
            return
        value = number(value, "open_interest", nonnegative=True)
        source_ts = timestamp_ms(source_ts)
        available = timestamp_ms(row.get("oi_available_at_ms", source_ts))
        if source_ts > available or available > row["ts_ms"]:
            raise DataError("future open-interest observation")
        if self.oi and source_ts < self.oi[-1][0]:
            raise DataError("reordered open-interest samples")
        if self.oi and source_ts == self.oi[-1][0]:
            if value != self.oi[-1][1]:
                raise DataError("conflicting same-time OI observation")
            return
        self.oi_sampling_interval_ms = timestamp_ms(row.get("oi_sampling_interval_ms", 0))
        self.oi_publication_lag_ms = timestamp_ms(row.get("oi_publication_lag_ms", 0))
        self.oi_availability_assumed = bool(row.get("oi_availability_assumed", False))
        self.oi.append((source_ts, value))

    def _oi_features(self, t):
        out = {f"oi_delta_{s}s": None for s in (30, 60, 180, 300, 900)}
        out.update(open_interest=None, oi_age_ms=None, oi_impulse=None,
                   oi_acceleration=None, oi_zscore=None, oi_effective_end_ms=None,
                   oi_sampling_interval_ms=self.oi_sampling_interval_ms,
                   oi_availability_assumed=self.oi_availability_assumed)
        if not self.oi:
            return out
        current_t, current = self.oi[-1]
        age = t-current_t
        out["oi_age_ms"] = age
        allowed_age = max(self.oi_max_age_ms, self.oi_sampling_interval_ms+self.oi_publication_lag_ms)
        if age > allowed_age or current <= 0:
            return out
        out["open_interest"] = current
        out["oi_effective_end_ms"] = current_t
        for sec in (30, 60, 180, 300, 900):
            if sec*1000 < self.oi_sampling_interval_ms:
                continue
            target = current_t-sec*1000
            previous = next(((st, v) for st, v in reversed(self.oi) if st <= target), None)
            if previous and target-previous[0] <= self.oi_horizon_tolerance_ms and previous[1] > 0:
                out[f"oi_delta_{sec}s"] = current/previous[1]-1
        # Impulse/acceleration only use distinct observed OI samples.
        if len(self.oi) >= 2:
            before = self.oi[-2]
            dt = (current_t-before[0])/1000
            if dt > 0:
                impulse = (current-before[1])/dt
                out["oi_impulse"] = impulse
                if len(self.oi) >= 3:
                    older = self.oi[-3]
                    dt0 = (before[0]-older[0])/1000
                    if dt0 > 0:
                        out["oi_acceleration"] = (impulse-(before[1]-older[1])/dt0)/dt
        changes = []
        history = list(self.oi)
        recent = history[-61:]
        for a, b in zip(recent, recent[1:]):
            if b[0] > a[0]:
                changes.append((b[1]-a[1])/((b[0]-a[0])/1000))
        # Baseline excludes newest impulse; no z-score from one/two observations.
        baseline = changes[:-1]
        if len(baseline) >= 20 and out["oi_impulse"] is not None:
            mean = sum(baseline)/len(baseline)
            sd = math.sqrt(sum((x-mean)**2 for x in baseline)/len(baseline))
            if sd > 0:
                out["oi_zscore"] = (out["oi_impulse"]-mean)/sd
        return out

    def update(self, row: dict) -> dict:
        row = canonical_bar(row, row.get("interval_ms", 60_000))
        if self.previous is not None:
            if row["ts_ms"] <= self.previous["ts_ms"] or row["start_ms"] < self.previous["bar_end_ms"]:
                raise DataError("features require ordered nonoverlapping bars")
            row["gap_before"] = row["start_ms"] > self.previous["bar_end_ms"]
        else:
            row["gap_before"] = bool(row.get("gap_before", False))
        self.previous = row
        self.bars.append(row)
        while self.bars and self.bars[0]["bar_end_ms"] <= row["bar_end_ms"]-300_000:
            self.bars.popleft()
        self._hour(row)
        self._observe_oi(row)
        while self.oi and self.oi[0][0] < row["ts_ms"]-2*HOUR:
            self.oi.popleft()
        h1 = list(self.h1)
        out = dict(ts_ms=row["ts_ms"], completed_h1_count=self.completed_h1_count,
                   atr_h1=sum(x["true_range"] for x in h1[-14:])/len(h1[-14:]) if h1 else None,
                   directional_move_3h=None, directional_move_6h=None,
                   h1_range=h1[-1]["high"]-h1[-1]["low"] if h1 else None,
                   flow_coverage_seconds=0, flow_imbalance=None,
                   gap_before=row["gap_before"])
        for hours in (3, 6):
            subset = h1[-hours:]
            if len(subset) == hours and all(b["start_ms"]-a["start_ms"] == HOUR for a, b in zip(subset, subset[1:])):
                out[f"directional_move_{hours}h"] = subset[-1]["close"]/subset[0]["open"]-1
        # Actual contiguous observed duration, capped to retained five minutes.
        duration = 0
        cursor = row["bar_end_ms"]
        for b in reversed(self.bars):
            if b["bar_end_ms"] != cursor or not b["flow_observed"]:
                break
            duration += b["interval_ms"]
            cursor = b["start_ms"]
        out["flow_coverage_seconds"] = duration/1000
        for seconds in (60, 300):
            keys = ("buy_notional", "sell_notional", "flow_imbalance", "buy_efficiency", "sell_efficiency", "price_displacement")
            out.update({f"{key}_{seconds}s": None for key in keys})
            window = self._window(seconds*1000, row)
            if window:
                buy = sum(b["buy_notional"] for b in window)
                sell = sum(b["sell_notional"] for b in window)
                displacement = window[-1]["close"]-window[0]["open"]
                out.update({f"buy_notional_{seconds}s": buy, f"sell_notional_{seconds}s": sell,
                            f"flow_imbalance_{seconds}s": (buy-sell)/(buy+sell) if buy+sell > 0 else None,
                            f"buy_efficiency_{seconds}s": max(displacement, 0)/buy if buy > 0 else None,
                            f"sell_efficiency_{seconds}s": max(-displacement, 0)/sell if sell > 0 else None,
                            f"price_displacement_{seconds}s": displacement})
        out["flow_imbalance"] = out["flow_imbalance_60s"]
        out.update(self._oi_features(row["ts_ms"]))
        for sec in (5, 15, 60):
            for side in ("long", "short"):
                key = f"{side}_liq_notional_{sec}s"
                out[key] = number(row.get(key), key, optional=True, nonnegative=True)
        for side in ("bid", "ask"):
            # Inputs must correspond to an explicit 60-second measurement window.
            add = row.get(f"{side}_restored_notional_60s")
            consumed = row.get(f"{side}_consumed_notional_60s")
            out[f"{side}_replenishment_ratio_60s"] = None
            if add is not None and consumed is not None:
                add = number(add, "restored notional", nonnegative=True)
                consumed = number(consumed, "consumed notional", nonnegative=True)
                if consumed > 0:
                    out[f"{side}_replenishment_ratio_60s"] = add/consumed
            proxy = row.get(f"{side}_replenishment_proxy_ratio_60s")
            if proxy is not None and row.get("book_ratio_is_proxy") is True:
                out[f"{side}_replenishment_ratio_60s"] = number(proxy, "replenishment proxy", nonnegative=True)
        out["book_ratio_is_proxy"] = row.get("book_ratio_is_proxy", False)
        out["price_oi_quadrant"] = None
        delta = out["oi_delta_60s"]
        price = out["price_displacement_60s"]
        if delta is not None and price is not None:
            out["price_oi_quadrant"] = ("UP" if price > 0 else "DOWN" if price < 0 else "FLAT") + "/" + ("OI_UP" if delta > 0 else "OI_DOWN" if delta < 0 else "OI_FLAT")
        return out
