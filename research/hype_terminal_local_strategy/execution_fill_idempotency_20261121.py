"""Research-only idempotent execution risk journal. No live orders."""
from dataclasses import dataclass, field
from math import isfinite

@dataclass
class Position:
    pending: float
    open_risk: float = 0.0

@dataclass
class FillRiskJournal:
    equity: float
    cap_fraction: float = .01
    positions: dict = field(default_factory=dict)
    seen: dict = field(default_factory=dict)
    blocked: bool = False

    def committed(self):
        return sum(p.pending + p.open_risk for p in self.positions.values())

    def accept(self, order_id, risk):
        if self.blocked or not order_id or order_id in self.positions or not isfinite(risk) or risk <= 0:
            return False
        if self.committed() + risk > self.equity*self.cap_fraction + 1e-10:
            return False
        self.positions[order_id] = Position(risk)
        return True

    def fill(self, execution_id, order_id, kind, risk_delta, utc, price):
        if not execution_id or not order_id or kind not in ('open', 'close') or not utc or not isfinite(price) or price <= 0 or not isfinite(risk_delta) or risk_delta <= 0:
            self.blocked = True
            raise ValueError('invalid execution')
        fingerprint = (order_id, kind, risk_delta, utc, price)
        if execution_id in self.seen:
            if self.seen[execution_id] != fingerprint:
                self.blocked = True
                raise ValueError('conflicting execution ID')
            return False
        p = self.positions.get(order_id)
        if p is None:
            self.blocked = True
            raise ValueError('unknown order')
        if kind == 'open':
            if risk_delta > p.pending + 1e-10:
                self.blocked = True
                raise ValueError('overfill')
            p.pending = max(0., p.pending-risk_delta)
            p.open_risk += risk_delta
        else:
            if risk_delta > p.open_risk + 1e-10:
                self.blocked = True
                raise ValueError('overclose')
            p.open_risk = max(0., p.open_risk-risk_delta)
        self.seen[execution_id] = fingerprint
        if p.pending < 1e-10 and p.open_risk < 1e-10:
            del self.positions[order_id]
        return True

    def cancel_pending(self, order_id):
        p = self.positions[order_id]
        p.pending = 0.
        if p.open_risk < 1e-10:
            del self.positions[order_id]

    def mark_equity(self, equity):
        if not isfinite(equity) or equity <= 0:
            self.blocked = True
            raise ValueError('invalid equity')
        self.equity = equity
