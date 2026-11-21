"""Research-only execution-aware risk reservations; no orders or detector changes.
Run: python -m unittest research.hype_terminal_local_strategy.test_execution_risk_reservation_20261121
"""
from dataclasses import dataclass, field
from math import isfinite

@dataclass
class Reservation:
    budget: float
    pending: float
    open_risk: float = 0.0

@dataclass
class ExecutionRiskBook:
    equity: float
    cap_fraction: float = .01
    orders: dict = field(default_factory=dict)

    def __post_init__(self):
        if not isfinite(self.equity) or self.equity <= 0 or not 0 < self.cap_fraction <= 1:
            raise ValueError("invalid equity/cap")

    def committed(self):
        return sum(o.pending + o.open_risk for o in self.orders.values())

    def accept(self, order_id, budget):
        if not order_id or order_id in self.orders or not isfinite(budget) or budget <= 0:
            raise ValueError("invalid or duplicate order")
        if self.committed() + budget > self.equity * self.cap_fraction + 1e-10:
            return False
        self.orders[order_id] = Reservation(budget, budget)
        return True

    def partial_fill(self, order_id, fraction_of_original):
        """Conservatively transfer reservation, never release risk on fill."""
        o = self.orders[order_id]
        if not isfinite(fraction_of_original) or fraction_of_original <= 0:
            raise ValueError("invalid fraction")
        delta = o.budget * fraction_of_original
        if delta > o.pending + 1e-10:
            raise ValueError("fill exceeds pending")
        o.pending = max(0., o.pending - delta)
        o.open_risk += delta

    def cancel_unfilled(self, order_id):
        """Cancellation only releases the unfilled portion."""
        o = self.orders[order_id]
        o.pending = 0.
        if o.open_risk == 0:
            del self.orders[order_id]

    def close_confirmed(self, order_id, fraction_of_open=1.):
        """Call only after actual close fill; never on close signal."""
        o = self.orders[order_id]
        if not isfinite(fraction_of_open) or not 0 < fraction_of_open <= 1:
            raise ValueError("invalid close fraction")
        o.open_risk *= 1 - fraction_of_open
        if o.open_risk < 1e-10:
            o.open_risk = 0.
        if o.pending == 0 and o.open_risk == 0:
            del self.orders[order_id]

    def mark_equity(self, equity):
        if not isfinite(equity) or equity <= 0:
            raise ValueError("invalid equity")
        self.equity = equity

    def state(self):
        return {"equity": self.equity, "committed": self.committed(),
                "capacity": self.equity*self.cap_fraction,
                "over_limit": self.committed() > self.equity*self.cap_fraction + 1e-10}

if __name__ == "__main__":
    b=ExecutionRiskBook(100)
    assert b.accept("A",.5)
    b.partial_fill("A",.4)
    b.cancel_unfilled("A")
    assert abs(b.committed()-.2)<1e-10
    assert b.accept("B",.5)
    b.mark_equity(60)
    assert b.state()["over_limit"]
    assert not b.accept("C",.01)
    b.close_confirmed("A")
    assert abs(b.committed()-.5)<1e-10
    print("PASS: partial-fill cancel retains open risk; MTM contraction blocks new entries")
