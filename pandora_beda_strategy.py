"""Executed-trade state machine for the ``pandora_flow_v2`` PAPER experiment.

Only accepted, independent executions advance proofs. Exchange timestamps select
measurement samples; receive/poll timestamps never confirm a direction. Three
executions are the named minimum for persistence (the old two-print minimum
cannot distinguish an initial print from an independently maintained response).
Execution acknowledgements, rather than recommendations, change position state.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
from bisect import bisect_left
from collections import deque
from decimal import Decimal
import math

from pandora_flow import MIN_CONTROL_IMBALANCE, WINDOWS
from pandora_risk import RiskPolicy

EXPERIMENT_ID = 'pandora_beda'


@dataclass(frozen=True)
class FlowConfig:
    min_control_events: int = 3
    minimum_control_imbalance: float = MIN_CONTROL_IMBALANCE
    # Existing measurement horizons, without a completed-window requirement.
    fast_seconds: int = 5
    sustained_seconds: int = 15
    confirmation_seconds: int = 30
    context_seconds: int = 60
    history_seconds: int = 600
    # Bound persisted tape and per-event work on very busy symbols. All proofs
    # also retain their own acknowledgement/structure boundaries.
    max_history_events: int = 4096
    freshness_limit_seconds: float = 60.

    def __post_init__(self):
        if self.min_control_events < 3:
            raise ValueError('control requires at least three independent events')
        if self.max_history_events < self.min_control_events:
            raise ValueError('history must retain enough independent executions')
        if not 0 < self.minimum_control_imbalance < 1:
            raise ValueError('invalid control imbalance')
        if min(self.fast_seconds, self.sustained_seconds, self.confirmation_seconds,
               self.context_seconds, self.history_seconds, self.freshness_limit_seconds) <= 0:
            raise ValueError('measurement horizons must be positive')


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _side(value):
    if value in (1, 'B', 'BUY', 'Buy', 'buy', 'LONG', 'long'):
        return 1
    if value in (-1, 'A', 'SELL', 'Sell', 'sell', 'SHORT', 'short'):
        return -1
    return 0


def _position_side(position):
    return _side((position or {}).get('side'))


def _name(side):
    return 'LONG' if side == 1 else 'SHORT' if side == -1 else 'FLAT'


def _measure(sample, epoch, seconds, previous=()):
    """Same executed-volume/causal-response definitions as pandora_flow.

    Computing the metrics here avoids that legacy summarizer's completed-window
    directional gates and its reconstruction of time-based dominance duration.
    """
    buy = sell = buy_quantity = sell_quantity = 0.
    buy_count = sell_count = 0
    buy_response = sell_response = 0.
    buy_response_count = sell_response_count = 0
    recent_buy = recent_sell = old_buy = old_sell = 0.
    high = low = previous_price = None
    midpoint = epoch-seconds/2
    for row in sample:
        price, volume, side = row['price'], row['notional'], row['side']
        change = price/previous_price-1 if previous_price is not None else 0.
        if side == 1:
            buy += volume
            buy_quantity += volume/price
            buy_count += 1
            buy_response += change
            buy_response_count += change > 0
            if row['exchange_epoch'] >= midpoint:
                recent_buy += volume
            else:
                old_buy += volume
        else:
            sell += volume
            sell_quantity += volume/price
            sell_count += 1
            sell_response -= change
            sell_response_count += change < 0
            if row['exchange_epoch'] >= midpoint:
                recent_sell += volume
            else:
                old_sell += volume
        high = price if high is None else max(high, price)
        low = price if low is None else min(low, price)
        previous_price = price
    count = len(sample)
    total = buy+sell
    elapsed = max(.001, min(seconds, epoch-sample[0]['exchange_epoch'])) if sample else .001
    move = sample[-1]['price']/sample[0]['price']-1 if count>1 else 0.
    recent_volume, old_volume = recent_buy+recent_sell, old_buy+old_sell
    recent_imbalance = (recent_buy-recent_sell)/recent_volume if recent_volume else 0.
    old_imbalance = (old_buy-old_sell)/old_volume if old_volume else 0.
    return dict(buy_volume=buy, sell_volume=sell, buy_notional=buy,
                sell_notional=sell, buy_quantity=buy_quantity, sell_quantity=sell_quantity,
                buy_trade_count=buy_count, sell_trade_count=sell_count,
                trade_count=count, imbalance=(buy-sell)/total if total else 0.,
                buy_sell_ratio=buy/sell if sell else None,
                volume_velocity=total/elapsed, trade_velocity=count/elapsed,
                volume_change=total-sum(r['notional'] for r in previous),
                volume_acceleration=(recent_volume-old_volume)/(seconds/2),
                imbalance_change=recent_imbalance-old_imbalance,
                price_return=move, price_high=high, price_low=low,
                price_range_fraction=(high-low)/sample[-1]['price'] if count else 0.,
                buy_price_response=buy_response, sell_price_response=sell_response,
                buy_response_event_count=buy_response_count,
                sell_response_event_count=sell_response_count,
                buy_absorbed=buy>sell and (move<=0 or buy_response<=0),
                sell_absorbed=sell>buy and (move>=0 or sell_response<=0),
                observed_seconds=min(seconds, max(0., epoch-sample[0]['exchange_epoch'])) if sample else 0.)


class _MeasurementCache:
    """Transient prefix sums and extrema, rebuilt from durable tape on restore.

    Decimal prefix arithmetic avoids cancellation changing a 60/40 boundary
    after a restart. Converting each independently computed response once also
    keeps restore and uninterrupted sums equal. No cache is decision evidence.
    """
    def __init__(self, events, horizons):
        self.rows, self.epochs = [], []
        self.sums = [(Decimal(0),)*10]
        self.responses = []
        self.extrema = {seconds: (deque(), deque()) for seconds in horizons}
        for event in events:
            self.append(event)

    def append(self, event):
        index = len(self.rows)
        price, volume, side = event['price'], event['notional'], event['side']
        change = price/self.rows[-1]['price']-1 if self.rows else 0.
        volume, quantity, change = Decimal(str(volume)), Decimal(str(volume/price)), Decimal(str(change))
        zero, one = Decimal(0), Decimal(1)
        values = ((volume,zero,quantity,zero,one,zero,change,zero,one if change>0 else zero,zero)
                  if side == 1 else