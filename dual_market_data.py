"""Fan out one validated Bybit trade stream to current and exact legacy flow accumulators.

Trading transport stays shared. Strategy 1.2 reads primary flow_context().
Strategy 1.1 reads legacy.flow_context(). No strategy rules live here.
"""
from market_data import RollingMarketData as CurrentRollingMarketData
from market_data_legacy import RollingMarketData as LegacyRollingMarketData


class DualMarketData:
    def __init__(self, **primary_kwargs):
        self.primary = CurrentRollingMarketData(**primary_kwargs)
        # Exact historical accumulator parameters from the profitable runtime.
        self.legacy = LegacyRollingMarketData(
            bucket_seconds=5,
            retention_seconds=600,
            max_symbols=max(512, int(primary_kwargs.get("max_symbols", 64))),
            max_trade_lag_seconds=360,
            freshness_seconds=15,
            max_seen_per_symbol=8192,
        )

    def mark_connected(self, epoch=None, symbols=None, owner=None):
        self.primary.mark_connected(epoch, symbols, owner=owner)
        self.legacy.mark_connected(epoch, symbols, owner=owner)

    def mark_disconnected(self, epoch=None, owner=None):
        self.primary.mark_disconnected(epoch, owner=owner)
        self.legacy.mark_disconnected(epoch, owner=owner)

    def set_subscriptions(self, symbols, epoch=None, owner=None):
        self.primary.set_subscriptions(symbols, epoch, owner=owner)
        self.legacy.set_subscriptions(symbols, epoch, owner=owner)

    def heartbeat(self, epoch=None, owner=None):
        self.primary.heartbeat(epoch, owner=owner)
        # Historical accumulator used one transport heartbeat clock.
        self.legacy.heartbeat(epoch)

    def ingest_trades(self, rows, received_at=None, owner=None, accepted_rows=None):
        accepted = []
        count = self.primary.ingest_trades(
            rows, received_at, owner=owner, accepted_rows=accepted
        )
        if accepted:
            self.legacy.ingest_trades(accepted, received_at)
            if accepted_rows is not None:
                accepted_rows.extend(accepted)
        return count

    def flow_context(self, symbol, epoch=None):
        return self.primary.flow_context(symbol, epoch)

    def context(self, symbol, epoch=None):
        return self.primary.context(symbol, epoch)

    def stats(self):
        result = self.primary.stats()
        result["legacy"] = self.legacy.stats()
        return result
