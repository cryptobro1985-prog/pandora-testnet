"""Conservative OHLC execution bounds, NOT observed fills. Stdlib only."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Bar:
    open: float
    high: float
    low: float
    close: float

def evaluate(side, bar, stop, target=None):
    assert side in ("LONG", "SHORT")
    assert bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
    assert stop > 0 and (target is None or target > 0)
    stop_hit = bar.low <= stop if side == "LONG" else bar.high >= stop
    target_hit = False if target is None else (bar.high >= target if side == "LONG" else bar.low <= target)
    gap = bar.open < stop if side == "LONG" else bar.open > stop
    if stop_hit and target_hit:
        return "AMBIGUOUS_STOP_FIRST", bar.open if gap else stop
    if stop_hit:
        return ("STOP_GAP" if gap else "STOP_TRIGGER"), bar.open if gap else stop
    if target_hit:
        return "TARGET_TRIGGER_UNVERIFIED_FILL", target
    return "HOLD", None

def max_notional(equity, risk_fraction, stop_distance, roundtrip_fee, slippage):
    assert equity > 0 and 0 < risk_fraction <= 1 and stop_distance >= 0 and roundtrip_fee >= 0 and slippage >= 0
    return equity * risk_fraction / (stop_distance + roundtrip_fee + slippage)

def tests():
    b = Bar(100, 102, 98, 101)
    assert evaluate("LONG", b, 99, 101)[0] == "AMBIGUOUS_STOP_FIRST"
    assert evaluate("SHORT", b, 101, 99)[0] == "AMBIGUOUS_STOP_FIRST"
    assert evaluate("LONG", Bar(97, 99, 96, 98), 99)[0] == "STOP_GAP"
    assert evaluate("SHORT", Bar(103, 104, 101, 102), 101)[0] == "STOP_GAP"
    assert evaluate("LONG", Bar(100, 100.5, 99.5, 100), 99)[0] == "HOLD"
    assert evaluate("SHORT", Bar(100, 100.5, 99.5, 100), 101)[0] == "HOLD"
    assert abs(max_notional(100, .005, .01, .0015, .01) - 23.2558139535) < 1e-7
    print("PASS 7 deterministic assertions")

if __name__ == "__main__":
    tests()
