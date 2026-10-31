"""Bybit V5 public trade -> venue-neutral Strategy 1 events.

Research / PAPER adapter. It does not place orders, infer missing ticks,
or infer prices from another venue.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ExecutedTrade:
    venue: str
    symbol: str
    price: float
    size: float
    exchange_epoch_ms: int
    aggressor_side: str
    trade_id: str


def normalize_bybit_public_trade(row):
    """Normalize one row from V5 publicTrade.<symbol>, fail closed."""
    if not isinstance(row, dict):
        return None
    try:
        symbol = str(row["s"])
        price, size = float(row["p"]), float(row["v"])
        epoch_ms = int(row["T"])
        side = str(row["S"])
        trade_id = str(row["i"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not symbol.endswith("USDT") or not all(map(math.isfinite, (price, size))):
        return None
    if price <= 0 or size <= 0 or epoch_ms <= 0 or side not in ("Buy", "Sell") or not trade_id:
        return None
    return ExecutedTrade("bybit", symbol[:-4], price, size, epoch_ms,
                         "BUY" if side == "Buy" else "SELL", trade_id)


def validate_latency(trade, received_epoch_ms, max_age_ms=15000):
    """Positive lag is transport + exchange latency; do not trade on old tape."""
    if trade is None:
        return False, "invalid_trade"
    lag = int(received_epoch_ms) - trade.exchange_epoch_ms
    if lag < -1000:
        return False, "future_exchange_timestamp"
    if lag > max_age_ms:
        return False, "stale_executed_trade"
    return True, "fresh"


def to_legacy_observation(trade):
    """Adapt a validated trade to the existing RollingMarketData ingestion shape."""
    return {"coin": trade.symbol, "px": str(trade.price), "sz": str(trade.size),
            "time": trade.exchange_epoch_ms, "side": "B" if trade.aggressor_side == "BUY" else "A",
            "tid": f"{trade.venue}:{trade.trade_id}"}
