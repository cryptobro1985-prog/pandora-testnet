"""Research-only OHLC boundary guard. No orders; does not assert fills."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Bar:
    start_ms: int
    end_ms: int
    high: float
    low: float

@dataclass(frozen=True)
class Decision:
    side: str
    signal_available_ms: int
    fill_ms: int
    entry: float
    stop: float

def classify_bar(bar: Bar, trade: Decision, opposite_confirmed_ms=None):
    if trade.side not in ("LONG", "SHORT"):
        raise ValueError("bad side")
    if not (bar.start_ms < bar.end_ms and bar.low <= bar.high):
        raise ValueError("invalid bar")
    if trade.fill_ms < trade.signal_available_ms:
        return "INVALID_LOOKAHEAD_FILL"
    if trade.side == "LONG" and trade.stop >= trade.entry:
        raise ValueError("long stop must be below entry")
    if trade.side == "SHORT" and trade.stop <= trade.entry:
        raise ValueError("short stop must be above entry")
    if bar.end_ms <= trade.fill_ms:
        return "PRE_ENTRY_IGNORE"
    if bar.start_ms < trade.fill_ms < bar.end_ms:
        return "UNRESOLVED_PARTIAL_BAR_NEED_TICKS"
    stop_hit = bar.low <= trade.stop if trade.side == "LONG" else bar.high >= trade.stop
    opposite = opposite_confirmed_ms is not None and bar.start_ms <= opposite_confirmed_ms < bar.end_ms
    if stop_hit and opposite:
        return "UNRESOLVED_EVENT_ORDER_NEED_TICKS"
    if stop_hit:
        return "STOP_TOUCHED_FILL_UNVERIFIED"
    if opposite:
        return "OPPOSITE_CONFIRMED_FILL_UNVERIFIED"
    return "HOLD"

def self_test():
    b = Bar(0, 60000, 102, 98)
    assert classify_bar(b, Decision("LONG", 10000, 30000, 100, 99)) == "UNRESOLVED_PARTIAL_BAR_NEED_TICKS"
    assert classify_bar(b, Decision("SHORT", 10000, 30000, 100, 101)) == "UNRESOLVED_PARTIAL_BAR_NEED_TICKS"
    assert classify_bar(b, Decision("LONG", 61000, 62000, 100, 99)) == "PRE_ENTRY_IGNORE"
    assert classify_bar(b, Decision("LONG", 30000, 20000, 100, 99)) == "INVALID_LOOKAHEAD_FILL"
    assert classify_bar(b, Decision("LONG", 0, 0, 100, 99), 20000) == "UNRESOLVED_EVENT_ORDER_NEED_TICKS"
    assert classify_bar(b, Decision("SHORT", 0, 0, 100, 101), 20000) == "UNRESOLVED_EVENT_ORDER_NEED_TICKS"
    assert classify_bar(Bar(0, 60000, 101, 99.5), Decision("LONG", 0, 0, 100, 99)) == "HOLD"
    return 7

if __name__ == "__main__":
    print("PASS", self_test(), "boundary tests")
