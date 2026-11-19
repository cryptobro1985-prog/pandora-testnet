"""Research-only stop trigger provenance diagnostic; not an execution simulator."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Tick:
    ms: int
    bid: float
    ask: float
    last: float
    mark: float

def first_trigger(side, stop, source, ticks):
    if side not in ("LONG", "SHORT") or source not in ("last", "mark", "executable"):
        raise ValueError("invalid configuration")
    for t in ticks:
        px = (t.bid if side == "LONG" else t.ask) if source == "executable" else getattr(t, source)
        if px <= stop if side == "LONG" else px >= stop:
            return t.ms, t.bid if side == "LONG" else t.ask
    return None

def test():
    cases = [
        ("LONG", 99, [Tick(1,99.4,99.5,99.3,98.7),Tick(2,98.8,99,98.9,98.6)], (2,98.8),(1,99.4)),
        ("SHORT",101,[Tick(1,100.5,100.6,100.7,101.4),Tick(2,101.1,101.3,101.2,101.5)],(2,101.3),(1,100.6)),
    ]
    for side, stop, ticks, executable, mark in cases:
        assert first_trigger(side,stop,"executable",ticks) == executable
        assert first_trigger(side,stop,"mark",ticks) == mark
    print("PASS: 4 deterministic synthetic assertions; NOT historical replay")

if __name__ == "__main__":
    test()
