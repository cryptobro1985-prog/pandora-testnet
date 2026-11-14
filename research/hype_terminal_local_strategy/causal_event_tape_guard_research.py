"""Research-only event tape sequencing. Synthetic unit tests, NOT historical fills."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Event:
    ts_ms: int
    kind: str
    price: float | None = None

def replay(side, signal_available_ms, fill_ms, entry, stop, events):
    """Strict causal sequencing; events must be timestamp-ordered.
    A stop trade is only a trigger, never proof of executable stop fill.
    Equal-time stop/opposite is ambiguous without exchange sequence IDs.
    """
    if side not in ("LONG", "SHORT"):
        raise ValueError("invalid side")
    if fill_ms < signal_available_ms:
        return "INVALID_LOOKAHEAD_FILL"
    if entry <= 0 or stop <= 0 or (side == "LONG" and stop >= entry) or (side == "SHORT" and stop <= entry):
        raise ValueError("invalid entry/stop")
    if any(a.ts_ms > b.ts_ms for a, b in zip(events, events[1:])):
        raise ValueError("unsorted events")
    # Same-millisecond market events cannot be ordered against the actual fill.
    # Fail closed rather than assuming the position existed before the print.
    if any(e.ts_ms == fill_ms for e in events):
        return "UNRESOLVED_FILL_TIMESTAMP_ORDER"
    active = [e for e in events if e.ts_ms > fill_ms]
    for i, event in enumerate(active):
        if event.kind not in ("TRADE", "OPPOSITE_AVAILABLE"):
            raise ValueError("invalid event type")
        if event.kind == "TRADE" and (event.price is None or event.price <= 0):
            raise ValueError("invalid trade price")
        hit = event.kind == "TRADE" and ((side == "LONG" and event.price <= stop) or (side == "SHORT" and event.price >= stop))
        opposite = event.kind == "OPPOSITE_AVAILABLE"
        if hit or opposite:
            if any(other.ts_ms == event.ts_ms and (
                (other.kind == "OPPOSITE_AVAILABLE" and hit) or
                (other.kind == "TRADE" and opposite and other.price is not None and
                 ((side == "LONG" and other.price <= stop) or (side == "SHORT" and other.price >= stop)))
            ) for other in active[i+1:]):
                return "UNRESOLVED_SAME_TIMESTAMP_ORDER"
            return "STOP_TRIGGER_FILL_UNVERIFIED" if hit else "OPPOSITE_SIGNAL_FILL_UNVERIFIED"
    return "HOLD"

def self_test():
    E = Event
    assert replay("LONG", 10, 20, 100, 99, [E(15,"TRADE",98),E(25,"TRADE",100)]) == "HOLD"
    assert replay("SHORT",10,20,100,101,[E(15,"TRADE",102),E(25,"TRADE",100)]) == "HOLD"
    assert replay("LONG",10,20,100,99,[E(21,"TRADE",98),E(22,"OPPOSITE_AVAILABLE")]) == "STOP_TRIGGER_FILL_UNVERIFIED"
    assert replay("SHORT",10,20,100,101,[E(21,"OPPOSITE_AVAILABLE"),E(22,"TRADE",102)]) == "OPPOSITE_SIGNAL_FILL_UNVERIFIED"
    assert replay("LONG",10,20,100,99,[E(21,"TRADE",98),E(21,"OPPOSITE_AVAILABLE")]) == "UNRESOLVED_SAME_TIMESTAMP_ORDER"
    assert replay("SHORT",10,20,100,101,[E(21,"OPPOSITE_AVAILABLE"),E(21,"TRADE",102)]) == "UNRESOLVED_SAME_TIMESTAMP_ORDER"
    assert replay("LONG",20,10,100,99,[]) == "INVALID_LOOKAHEAD_FILL"
    try:
        replay("LONG",10,20,100,99,[E(30,"TRADE",100),E(25,"TRADE",98)])
        raise AssertionError("unsorted tape accepted")
    except ValueError:
        pass
    assert replay("LONG",10,20,100,99,[E(20,"TRADE",98),E(21,"TRADE",100)]) == "UNRESOLVED_FILL_TIMESTAMP_ORDER"
    assert replay("SHORT",10,20,100,101,[E(20,"TRADE",102),E(21,"TRADE",100)]) == "UNRESOLVED_FILL_TIMESTAMP_ORDER"
    assert replay("LONG",10,20,100,99,[E(19,"TRADE",98),E(21,"TRADE",100)]) == "HOLD"
    assert replay("LONG",10,20,100,99,[E(21,"TRADE",98)]) == "STOP_TRIGGER_FILL_UNVERIFIED"
    return 12

if __name__ == "__main__":
    print("PASS", self_test(), "synthetic event-order tests")
