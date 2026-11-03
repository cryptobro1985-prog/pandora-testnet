"""Causal UTC H1 structure. Tick-flow blocks never confirm a local."""
from collections import deque
from dataclasses import dataclass
import math

from .model import Local

HOUR = 3600


@dataclass
class H1Bar:
    start: float
    end: float
    available_ts: float
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    high_ts: float | None = None
    low_ts: float | None = None

    @classmethod
    def from_candle(cls, candle, as_of):
        if candle.get('interval_minutes', 60) != 60 or candle.get('timeframe', '1h') != '1h':
            raise ValueError('Only UTC H1 candles are supported')
        start = float(candle['open_ts'])
        available = float(candle['available_ts'])
        values = [float(candle[k]) for k in ('open', 'high', 'low', 'close')]
        volume = float(candle.get('volume', 0))
        if (not all(math.isfinite(x) for x in (start, available, as_of, volume, *values))
                or start < 0 or start % HOUR != 0 or available < start+HOUR
                or available > as_of or min(values) <= 0 or volume < 0
                or not values[2] <= min(values[0], values[3]) <= max(values[0], values[3]) <= values[1]):
            raise ValueError('Invalid, unclosed or future H1 candle')
        # REST OHLCV does not identify the exact tick time of its high/low.
        return cls(start, start+HOUR, available, *values, volume)


class H1Tracker:
    def __init__(self, lookback=4, next_ident=0):
        self.lookback = lookback
        self.history = deque(maxlen=max(128, lookback+2))
        self.pending = {}
        self.current = None
        self.current_complete = False
        self.next_ident = next_ident
        self.latest_available_ts = None
        self.discontinuity = False

    def _local(self, kind, bar):
        self.next_ident += 1
        return Local(self.next_ident, kind, bar.low if kind == 'LOW' else bar.high,
                     bar.low_ts if kind == 'LOW' else bar.high_ts, bar.available_ts,
                     timeframe='1h', candle_open_ts=bar.start, candle_close_ts=bar.end)

    def _prior(self, start):
        prior = list(self.history)[-self.lookback:]
        if len(prior) != self.lookback:
            return None
        expected = start-self.lookback*HOUR
        for bar in prior:
            if bar.start != expected or bar.end > start:
                return None
            expected += HOUR
        return prior

    def mark_gap(self):
        # Verified closed candles survive a tape gap. The open hour can no
        # longer be called complete and cannot become confirmation evidence.
        self.current_complete = False
        self.discontinuity = True

    def closed(self, bar):
        events = []
        if self.history and bar.start <= self.history[-1].start:
            old = next((x for x in self.history if x.start == bar.start), None)
            if old and (old.open, old.high, old.low, old.close) == (bar.open, bar.high, bar.low, bar.close):
                return events, False
            raise ValueError('Out-of-order or conflicting closed H1 candle')
        if self.latest_available_ts is not None and bar.available_ts < self.latest_available_ts:
            raise ValueError('H1 observation availability cannot move backward')
        contiguous = not self.history or self.history[-1].end == bar.start
        if not contiguous:
            for local in self.pending.values():
                local.status, local.invalidated = 'INVALIDATED', True
                events.append((local, 'INVALIDATED', 'MISSING_H1_INTERVAL'))
            self.pending.clear()
        # Process existing candidates first. A new extreme updates the H1
        # candidate; only a later closed hour with a strict retreat confirms it.
        for kind, local in list(self.pending.items()):
            price = bar.low if kind == 'LOW' else bar.high
            extends = price < local.price if kind == 'LOW' else price > local.price
            retreats = price > local.price if kind == 'LOW' else price < local.price
            if extends:
                local.price = price
                local.extreme_ts = bar.low_ts if kind == 'LOW' else bar.high_ts
                local.candle_open_ts, local.candle_close_ts = bar.start, bar.end
                local.status, local.evidence = 'UPDATED', 0
                events.append((local, 'UPDATED', 'NEW_H1_EXTREME'))
            elif retreats and bar.start >= local.candle_close_ts:
                local.status, local.confirmed_ts, local.evidence = 'CONFIRMED', bar.available_ts, 1
                events.append((local, 'CONFIRMED', 'SUBSEQUENT_CLOSED_H1_RETREAT'))
                del self.pending[kind]
        prior = self._prior(bar.start)
        if prior:
            for kind in ('LOW', 'HIGH'):
                extreme = (bar.low < min(x.low for x in prior)) if kind == 'LOW' else (bar.high > max(x.high for x in prior))
                if extreme and kind not in self.pending:
                    local = self._local(kind, bar)
                    self.pending[kind] = local
                    events.append((local, 'FORMING', 'EXCEEDS_PRECEDING_CLOSED_H1'))
        self.history.append(bar)
        self.latest_available_ts = bar.available_ts
        return events, True

    def seed(self, candle, as_of):
        bar = H1Bar.from_candle(candle, as_of)
        return self.closed(bar)

    def tick(self, trade):
        start = math.floor(trade.ts/HOUR)*HOUR
        events = []
        if self.current is not None and start < self.current.start:
            raise ValueError('Trade precedes open H1 interval')
        if self.current is None or start > self.current.start:
            previous = self.current
            if previous is not None and self.current_complete:
                # The first next-hour observation makes closure observable;
                # do not backdate an event to an unobserved clock boundary.
                previous.available_ts = trade.ts
                closed_events, _ = self.closed(previous)
                events.extend(closed_events)
            if previous is None:
                complete = trade.ts == start
            else:
                # If multiple full hours were missed, the first observed hour
                # is partial too, even if the prior hour happened to be complete.
                complete = start == previous.end and not self.discontinuity
                if self.discontinuity:
                    complete = trade.ts == start
            self.current = H1Bar(start, start+HOUR, start+HOUR, trade.price, trade.price,
                                 trade.price, trade.price, trade.quantity, trade.ts, trade.ts)
            self.current_complete = complete
        else:
            bar = self.current
            bar.close = trade.price
            bar.volume += trade.quantity
            if trade.price > bar.high:
                bar.high, bar.high_ts = trade.price, trade.ts
            if trade.price < bar.low:
                bar.low, bar.low_ts = trade.price, trade.ts
        self.discontinuity = False
        return events
