"""Research-only integrity gate. Does not execute orders."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Tick:
    exchange_ms: int
    received_ms: int
    sequence: int
    price: float

def validate_ticks(ticks, entry_ms, max_gap_ms=60000):
    if not ticks:
        return {"eligible": False, "reason": "NO_TICKS"}
    if ticks[0].exchange_ms > entry_ms:
        return {"eligible": False, "reason": "ENTRY_COVERAGE_MISSING"}
    previous = None
    for tick in ticks:
        if tick.price <= 0 or tick.received_ms < tick.exchange_ms:
            return {"eligible": False, "reason": "INVALID_TICK"}
        if previous is not None:
            if (tick.exchange_ms, tick.sequence) <= (previous.exchange_ms, previous.sequence):
                return {"eligible": False, "reason": "NON_MONOTONIC"}
            if tick.exchange_ms - previous.exchange_ms > max_gap_ms:
                return {"eligible": False, "reason": "DATA_GAP"}
        previous = tick
    return {"eligible": True, "reason": "ORDERED_COVERAGE_ONLY", "fills_verified": False}

def max_notional(equity, risk_fraction, stop_fraction, fee_fraction, gap_fraction, funding_fraction=0):
    if equity <= 0 or not 0 < risk_fraction <= .01 or min(stop_fraction, fee_fraction, gap_fraction, funding_fraction) < 0:
        raise ValueError("invalid risk parameters")
    return equity * risk_fraction / (stop_fraction + fee_fraction + gap_fraction + funding_fraction)

def self_test():
    t = lambda a,b,s,p: Tick(a,b,s,p)
    assert validate_ticks([t(100,101,1,100),t(101,102,1,99)],100)["eligible"]
    assert validate_ticks([t(101,102,1,100)],100)["reason"] == "ENTRY_COVERAGE_MISSING"
    assert validate_ticks([t(100,101,1,100),t(61001,61002,1,99)],100)["reason"] == "DATA_GAP"
    assert validate_ticks([t(100,101,1,100),t(100,102,1,99)],100)["reason"] == "NON_MONOTONIC"
    assert validate_ticks([t(100,99,1,100)],100)["reason"] == "INVALID_TICK"
    assert round(max_notional(100,.005,.01,.0015,.01),2) == 23.26
    return "6 synthetic checks passed; not a Bybit execution replay"

if __name__ == "__main__":
    print(self_test())
