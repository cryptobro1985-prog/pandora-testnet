"""Bounded observations for PAPER signal research, using real exchange trades.

``dayNtlVlm`` is a rolling 24-hour total, not a cumulative trade counter. Its
differences must not be used as interval volume. This accumulator instead sums
the USD notional of timestamped Hyperliquid ``trades`` websocket messages.

The caller owns the websocket and must report connection/subscription changes
and received server heartbeats. Reconnects invalidate volume coverage. A live
socket and an old snapshot alone cannot establish fresh market participation.
No network, trading, position sizing, or exit policy lives in this module.
"""
from collections import deque
import math
import threading
import time


def _number(value):
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) else None


class RollingMarketData:
    """Thread-safe five-second volume buckets and genuine ~60-second OI changes.

    ``context`` compares the three most recent *completed* five-second buckets
    with preceding observed buckets. The recent window excludes the forming
    bucket, so its rate does not jump because a partial bucket was extrapolated.
    ``volume_rate_z`` is an empirical deviation from preceding bucket rates,
    with a noise floor, rather than a calibrated probability of a profitable
    trade. It is available after twelve prior buckets. Burst ratio becomes
    available after at least sixty seconds of continuous subscription coverage.
    """

    def __init__(self, bucket_seconds=5, retention_seconds=600, max_symbols=512,
                 max_trade_lag_seconds=10, freshness_seconds=15,
                 max_seen_per_symbol=8192):
        if (int(bucket_seconds) < 1 or retention_seconds < 90 or max_symbols < 1 or
                max_trade_lag_seconds <= 0 or freshness_seconds <= 0 or
                max_seen_per_symbol < 1):
            raise ValueError("invalid market observation bounds")
        self.bucket_seconds = int(bucket_seconds)
        self.retention_seconds = int(retention_seconds)
        self.max_symbols = int(max_symbols)
        self.max_trade_lag_seconds = float(max_trade_lag_seconds)
        self.freshness_seconds = float(freshness_seconds)
        self.max_seen_per_symbol = int(max_seen_per_symbol)
        self._lock = threading.RLock()
        self._connected = False
        self._connected_at = None
        self._heartbeat_at = None
        self._symbols = {}
        self._oi = {}
        self._counters = {"accepted": 0, "duplicates": 0, "invalid": 0,
                          "stale": 0, "outside_subscription": 0}

    @staticmethod
    def _new_symbol(epoch):
        return {"since": epoch, "buckets": {}, "seen": set(),
                "seen_queue": deque(), "latest_trade": None,
                "dedup_overflow_until": None}

    def mark_connected(self, epoch=None, symbols=None):
        """Start new coverage; previous trade buckets cannot bridge a reconnect."""
        epoch = time.time() if epoch is None else float(epoch)
        with self._lock:
            selected = list(self._symbols) if symbols is None else list(symbols)
            self._connected = True
            self._connected_at = epoch
            self._heartbeat_at = epoch
            self._symbols = {str(s): self._new_symbol(epoch)
                             for s in selected[:self.max_symbols]}

    def mark_disconnected(self, epoch=None):
        with self._lock:
            self._connected = False
            self._heartbeat_at = None

    def set_subscriptions(self, symbols, epoch=None):
        """Call after subscribing; newly added symbols receive their own clock."""
        epoch = time.time() if epoch is None else float(epoch)
        selected = dict.fromkeys(str(s) for s in symbols)
        selected = list(selected)[:self.max_symbols]
        with self._lock:
            self._symbols = {s: self._symbols.get(s) or self._new_symbol(epoch)
                             for s in selected}

    def heartbeat(self, epoch=None):
        """Report a *received* server message/pong, not an outgoing client ping.

        A silent transport gap invalidates coverage even if a broken connection
        wasn't reported explicitly by the websocket client.
        """
        epoch = time.time() if epoch is None else float(epoch)
        with self._lock:
            if not self._connected:
                return
            if (self._heartbeat_at is not None and
                    epoch - self._heartbeat_at > self.freshness_seconds):
                self._symbols = {s: self._new_symbol(epoch) for s in self._symbols}
                self._connected_at = epoch
            self._heartbeat_at = max(epoch, self._heartbeat_at or epoch)

    def _prune(self, state, epoch):
        floor = int((epoch - self.retention_seconds) // self.bucket_seconds)
        for index in list(state["buckets"]):
            if index < floor:
                del state["buckets"][index]
        # A deduplication key need live only as long as a timestamp is accepted.
        # Queue order uses receipt time so out-of-order event timestamps are safe.
        cutoff = epoch - self.max_trade_lag_seconds - 2
        queue, seen = state["seen_queue"], state["seen"]
        while queue and queue[0][0] < cutoff:
            _, key = queue.popleft()
            seen.discard(key)

    def ingest_trades(self, rows, received_at=None):
        """Accept documented ``WsTrade[]``; return accepted row count.

        The exchange id is (event time, coin, tid). Stale replay, malformed
        numbers, invalid sides, and future timestamps do not create volume.
        Subscribe/mark_connected before calling; unsubscribed symbols are not
        silently added because their observation start time would be unknown.
        """
        received = time.time() if received_at is None else float(received_at)
        if not isinstance(rows, (list, tuple)):
            return 0
        with self._lock:
            if not self._connected:
                return 0
            self.heartbeat(received)
            accepted = 0
            touched = set()
            for row in rows:
                if not isinstance(row, dict):
                    self._counters["invalid"] += 1
                    continue
                symbol = str(row.get("coin", ""))
                state = self._symbols.get(symbol)
                if state is None:
                    self._counters["outside_subscription"] += 1
                    continue
                if symbol not in touched:
                    self._prune(state, received)
                    touched.add(symbol)
                if state["dedup_overflow_until"] is not None:
                    if received <= state["dedup_overflow_until"]:
                        continue
                    # Overflow must fail closed rather than evict recent ids
                    # and let a retransmission inflate a supposedly real burst.
                    state = self._new_symbol(received)
                    self._symbols[symbol] = state
                price, size, millis = (_number(row.get(key)) for key in ("px", "sz", "time"))
                tid, side = row.get("tid"), row.get("side")
                if (price is None or size is None or millis is None or price <= 0 or
                        size <= 0 or millis <= 0 or side not in ("B", "A") or
                        tid is None or isinstance(tid, (dict, list, bool))):
                    self._counters["invalid"] += 1
                    continue
                stamp = millis / 1000.0
                age = received - stamp
                if age < -1.0 or age > self.max_trade_lag_seconds or stamp < state["since"]:
                    self._counters["stale"] += 1
                    continue
                notional = price * size
                if not math.isfinite(notional):
                    self._counters["invalid"] += 1
                    continue
                key = (millis, symbol, str(tid))
                if key in state["seen"]:
                    self._counters["duplicates"] += 1
                    continue
                if len(state["seen"]) >= self.max_seen_per_symbol:
                    state["dedup_overflow_until"] = received + self.max_trade_lag_seconds + 2
                    state["latest_trade"] = None
                    self._counters.setdefault("dedup_overflows", 0)
                    self._counters["dedup_overflows"] += 1
                    continue
                state["seen"].add(key)
                state["seen_queue"].append((received, key))
                index = int(stamp // self.bucket_seconds)
                bucket = state["buckets"].setdefault(index, [0.0, 0.0, 0, None, None, None, None])
                bucket[0 if side == "B" else 1] += notional
                bucket[2] += 1
                if bucket[3] is None or stamp < bucket[3]:
                    bucket[3], bucket[4] = stamp, price
                if bucket[5] is None or stamp > bucket[5]:
                    bucket[5], bucket[6] = stamp, price
                state["latest_trade"] = max(stamp, state["latest_trade"] or stamp)
                accepted += 1
            for symbol in touched:
                self._prune(self._symbols[symbol], received)
            self._counters["accepted"] += accepted
            return accepted

    def add_open_interest(self, symbol, epoch, oi):
        """Record one observed OI level; never annualize/extrapolate its delta."""
        epoch, oi = _number(epoch), _number(oi)
        if epoch is None or oi is None or oi <= 0:
            return False
        symbol = str(symbol)
        with self._lock:
            if symbol not in self._oi and len(self._oi) >= self.max_symbols:
                return False
            rows = self._oi.setdefault(symbol, deque(maxlen=128))
            if rows and epoch < rows[-1][0]:
                return False
            if rows and epoch == rows[-1][0]:
                rows[-1] = (epoch, oi)
            else:
                rows.append((epoch, oi))
            while rows and rows[0][0] < epoch - 180:
                rows.popleft()
            return True

    def _oi_context(self, symbol, epoch):
        out = {"oi_delta_60s": None, "oi_window_seconds": None,
               "oi_data_fresh": False, "oi_age_seconds": None}
        rows = self._oi.get(symbol)
        if not rows:
            return out
        latest_epoch, latest_oi = rows[-1]
        age = epoch - latest_epoch
        out["oi_age_seconds"] = age
        if age < -1 or age > self.freshness_seconds:
            return out
        out["oi_data_fresh"] = True
        eligible = [r for r in rows if abs(r[0] - (latest_epoch - 60)) <= 7]
        if eligible:
            anchor_epoch, anchor_oi = min(eligible, key=lambda r: abs(latest_epoch - r[0] - 60))
            out["oi_delta_60s"] = latest_oi / anchor_oi - 1.0
            out["oi_window_seconds"] = latest_epoch - anchor_epoch
        return out

    def context(self, symbol, epoch=None):
        epoch = time.time() if epoch is None else float(epoch)
        symbol = str(symbol)
        with self._lock:
            out = {"volume_burst_ratio": None, "volume_rate_z": None,
                   "volume_baseline_samples": 0, "volume_rate_usd_per_sec": None,
                   "buy_volume_60s": None, "sell_volume_60s": None,
                   "flow_imbalance": None, "cvd_1m": None,"trade_count_60s":None,"observed_notional_60s":None,
                   "volume_source": "hyperliquid_ws_trades",
                   "trade_coverage_seconds": 0.0, "trade_data_fresh": False,
                   "latest_trade_age_seconds": None,
                   "volume_window_end_epoch": None,
                   "volume_window_seconds": 3 * self.bucket_seconds}
            out.update(self._oi_context(symbol, epoch))
            state = self._symbols.get(symbol)
            if state is None or not self._connected or self._heartbeat_at is None:
                return out
            if state["dedup_overflow_until"] is not None:
                out["trade_data_error"] = "dedup_capacity_exceeded_rewarming_required"
                return out
            heartbeat_age = epoch - self._heartbeat_at
            if heartbeat_age < -1 or heartbeat_age > self.freshness_seconds:
                return out
            self._prune(state, epoch)
            coverage = max(0.0, epoch - state["since"])
            out["trade_coverage_seconds"] = min(coverage, self.retention_seconds)
            if state["latest_trade"] is not None:
                out["latest_trade_age_seconds"] = epoch - state["latest_trade"]
            # Quiet complete buckets are legitimate history only while the
            # transport was continuously observed. A current signal still needs
            # a recent real trade, not just a socket subscription acknowledgment.
            fresh_trade = (out["latest_trade_age_seconds"] is not None and
                           -1 <= out["latest_trade_age_seconds"] <= self.freshness_seconds)
            if coverage < 60 or not fresh_trade:
                return out
            end = int(epoch // self.bucket_seconds)
            first_full = int(math.ceil(state["since"] / self.bucket_seconds))
            first_full = max(first_full, end - self.retention_seconds // self.bucket_seconds)
            if end - first_full < 12:
                return out
            buckets = state["buckets"]
            totals = lambda i: sum(buckets.get(i, (0.0, 0.0, 0))[:2])
            recent = sum(totals(i) for i in range(end - 3, end))
            rate = recent / (3 * self.bucket_seconds)
            baseline = [totals(i) / self.bucket_seconds for i in range(first_full, end - 3)]
            mean = sum(baseline) / len(baseline) if baseline else 0.0
            # A finite noise floor handles a flat prior baseline without NaN,
            # infinity, or the old behaviour of never detecting any later burst.
            sigma = math.sqrt(sum((x - mean) ** 2 for x in baseline) / len(baseline)) if baseline else 0.0
            noise = max(sigma, mean * 0.10, 1.0)
            burst = rate / max(mean, 1.0)
            last_minute = range(end - 60 // self.bucket_seconds, end)
            buys = sum(buckets.get(i, (0.0, 0.0, 0))[0] for i in last_minute)
            sells = sum(buckets.get(i, (0.0, 0.0, 0))[1] for i in last_minute)
            out.update({"volume_burst_ratio": burst,
                        "volume_rate_z": (rate - mean) / noise if len(baseline) >= 12 else None,
                        "volume_baseline_samples": len(baseline),
                        "volume_rate_usd_per_sec": rate,
                        "buy_volume_60s": buys, "sell_volume_60s": sells,
                        "flow_imbalance": (buys - sells) / (buys + sells) if buys + sells else 0.0,
                        "cvd_1m": buys - sells,
                        "trade_count_60s":sum(buckets.get(i,(0.0,0.0,0))[2] for i in last_minute),
                        "observed_notional_60s":buys+sells,
                        "trade_data_fresh": True,
                        "volume_window_end_epoch": end * self.bucket_seconds})
            return out

    def flow_context(self, symbol, epoch=None):
        """Executed aggressive buy/sell notional, including the forming bucket.
        One-minute dominance is the trading input; five-minute flow is context.
        A full observed minute and a fresh trade are required for data validity.
        """
        epoch=time.time() if epoch is None else float(epoch)
        out={"trade_data_fresh":False,"flow_imbalance":None,"buy_volume_60s":None,
             "sell_volume_60s":None,"latest_trade_age_seconds":None,"window_seconds":60}
        with self._lock:
            state=self._symbols.get(str(symbol))
            if state is None or not self._connected or self._heartbeat_at is None:return out
            if state.get("dedup_overflow_until") is not None:return out
            if not -1<=epoch-self._heartbeat_at<=self.freshness_seconds:return out
            self._prune(state,epoch)
            coverage=max(0.,epoch-state["since"])
            out["trade_coverage_seconds"]=coverage
            age=epoch-state["latest_trade"] if state["latest_trade"] is not None else None
            out["latest_trade_age_seconds"]=age
            if coverage<60 or age is None or not -1<=age<=self.freshness_seconds:return out
            end=int(epoch//self.bucket_seconds)
            buckets=state["buckets"]
            def volumes(seconds):
                rows=[buckets.get(i,(0.,0.,0)) for i in range(end-seconds//self.bucket_seconds+1,end+1)]
                return sum(x[0] for x in rows),sum(x[1] for x in rows),sum(x[2] for x in rows)
            b15,s15,c15=volumes(15)
            b30,s30,c30=volumes(30)
            buy,sell,count=volumes(60)
            def imbalance(b,s):
                return (b-s)/(b+s) if b+s else 0.
            i15,i30,i60=imbalance(b15,s15),imbalance(b30,s30),imbalance(buy,sell)
            out.update(trade_data_fresh=True,
                       buy_volume_15s=b15,sell_volume_15s=s15,trade_count_15s=c15,
                       buy_volume_30s=b30,sell_volume_30s=s30,trade_count_30s=c30,
                       buy_volume_60s=buy,sell_volume_60s=sell,
                       flow_imbalance=i60,flow_imbalance_15s=i15,flow_imbalance_30s=i30,
                       flow_delta_15_60=i15-i60,flow_delta_30_60=i30-i60,
                       trade_count_60s=count,observed_notional_60s=buy+sell,
                       volume_window_end_epoch=epoch,volume_source="hyperliquid_ws_executed_trades")
            if coverage>=300:
                b5,s5,c5=volumes(300)
                i300=imbalance(b5,s5)
                start_i=end-300//self.bucket_seconds+1
                price_rows=[buckets.get(i) for i in range(start_i,end+1)]
                price_rows=[x for x in price_rows if x and len(x)>=7 and x[3] is not None and x[5] is not None]
                price_start=price_rows[0][4] if price_rows else None
                price_end=price_rows[-1][6] if price_rows else None
                price_return=((price_end/price_start)-1.0) if price_start and price_end else None
                out.update(buy_volume_300s=b5,sell_volume_300s=s5,trade_count_300s=c5,
                           flow_imbalance_300s=i300,flow_delta_60_300=i60-i300,
                           price_start_300s=price_start,price_end_300s=price_end,
                           price_return_300s=price_return)
            return out

    def stats(self):
        with self._lock:
            return {**self._counters, "connected": self._connected,
                    "subscribed_symbols": len(self._symbols),
                    "open_interest_symbols": len(self._oi),
                    "buckets": sum(len(s["buckets"]) for s in self._symbols.values()),
                    "dedup_entries": sum(len(s["seen"]) for s in self._symbols.values())}
