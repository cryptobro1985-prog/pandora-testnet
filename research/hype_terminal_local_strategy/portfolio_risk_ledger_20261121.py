"""Research-only portfolio reservation gate for post-local paper trades.
No orders, detector training, or claims of historical execution.
Run: python -m unittest research/hype_terminal_local_strategy/test_portfolio_risk_ledger_20261121.py
"""
from dataclasses import dataclass, field
from math import isfinite

@dataclass
class Ledger:
    equity: float
    max_risk_fraction: float = 0.01
    reserved: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        if not isfinite(self.equity) or self.equity <= 0:
            raise ValueError("equity must be positive")
        if not 0 < self.max_risk_fraction <= 1:
            raise ValueError("invalid aggregate risk")

    @property
    def capacity(self):
        return self.equity * self.max_risk_fraction

    @property
    def committed(self):
        return sum(self.reserved.values())

    def reserve(self, order_id: str, loss_budget: float):
        """Reserve at order acceptance; pending orders consume budget too."""
        if not order_id or order_id in self.reserved:
            raise ValueError("missing/duplicate order id")
        if not isfinite(loss_budget) or loss_budget <= 0:
            raise ValueError("invalid risk")
        if self.committed + loss_budget > self.capacity + 1e-10:
            return False
        self.reserved[order_id] = loss_budget
        return True

    def update_equity(self, conservative_mark_to_market_equity: float):
        if not isfinite(conservative_mark_to_market_equity) or conservative_mark_to_market_equity <= 0:
            raise ValueError("invalid MTM equity")
        self.equity = conservative_mark_to_market_equity
        # Existing reservations remain; no new orders while over budget.

    def confirm_exit(self, order_id: str):
        """Only call after confirmed terminal fill/cancel, never at signal time."""
        if order_id not in self.reserved:
            raise KeyError(order_id)
        return self.reserved.pop(order_id)

    def state(self):
        return dict(equity=self.equity, committed=self.committed,
                    capacity=self.capacity, free=max(0.0, self.capacity-self.committed),
                    over_limit=self.committed > self.capacity + 1e-10)

if __name__ == "__main__":
    l=Ledger(100)
    assert l.reserve("long-low",.5)
    assert l.reserve("short-high",.5)
    assert not l.reserve("third",.5)
    assert l.committed == 1.
    l.update_equity(90)
    assert l.state()["over_limit"]
    assert not l.reserve("fourth",.01)
    l.confirm_exit("long-low")
    assert l.reserve("fourth",.01)
    assert l.committed <= l.capacity
    print("PASS: third rejected, MTM contraction blocks entry, confirmed release restores capacity")
