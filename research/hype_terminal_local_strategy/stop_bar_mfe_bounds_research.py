"""Research-only conservative MFE bounds when stop and bar extreme coexist."""
from dataclasses import dataclass

@dataclass(frozen=True)
class StopBar:
    side: str
    entry: float
    stop: float
    open: float
    high: float
    low: float
    close: float
    prior_best: float

def mfe_bounds_at_stop(b: StopBar):
    """(stop_hit, minimum_known_MFE, maximum_possible_MFE, ambiguous).
    OHLC cannot establish whether favorable high/low occurred before stop.
    Never use upper bound as realized MFE without tick-level event ordering.
    """
    if b.side not in ('LONG', 'SHORT') or not (0 < b.low <= min(b.open,b.close) <= max(b.open,b.close) <= b.high) or b.entry <= 0:
        raise ValueError('invalid bar or side')
    if b.side == 'LONG':
        if b.stop >= b.entry or b.prior_best < b.entry:
            raise ValueError('invalid LONG stop/prior best')
        hit = b.low <= b.stop
        lower = max(0., b.prior_best / b.entry - 1, b.open / b.entry - 1)
        upper = max(lower, b.high / b.entry - 1)
    else:
        if b.stop <= b.entry or b.prior_best > b.entry:
            raise ValueError('invalid SHORT stop/prior best')
        hit = b.high >= b.stop
        lower = max(0., 1 - b.prior_best / b.entry, 1 - b.open / b.entry)
        upper = max(lower, 1 - b.low / b.entry)
    return hit, lower, upper, hit and upper > lower + 1e-12
