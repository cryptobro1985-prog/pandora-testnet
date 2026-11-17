"""Research-only conservative OHLC stop/exit collision classifier; no live orders."""
from dataclasses import dataclass
from math import isfinite

@dataclass(frozen=True)
class Bar:
    start_ms: int
    open: float
    high: float
    low: float
    close: float

def classify(side: str, entry_ms: int, stop: float, bar: Bar,
             opposite_confirm_ms: int | None = None):
    if side not in ('LONG','SHORT') or any(not isfinite(x) or x <= 0 for x in (bar.open,bar.high,bar.low,bar.close,stop)):
        raise ValueError('invalid side/price')
    if not bar.low <= min(bar.open,bar.close) <= max(bar.open,bar.close) <= bar.high:
        raise ValueError('invalid OHLC')
    if entry_ms >= bar.start_ms + 60000:
        return 'BEFORE_ENTRY', None
    if bar.start_ms < entry_ms < bar.start_ms + 60000:
        return 'INTRABAR_ENTRY_UNKNOWN_PATH', None
    hit = bar.low <= stop if side == 'LONG' else bar.high >= stop
    if hit:
        adverse_open = bar.open < stop if side == 'LONG' else bar.open > stop
        return ('GAP_THROUGH_STOP' if adverse_open else 'STOP_TOUCHED_FILL_UNVERIFIED'), (bar.open if adverse_open else stop)
    if opposite_confirm_ms is not None and bar.start_ms <= opposite_confirm_ms < bar.start_ms + 60000:
        return 'OPPOSITE_CONFIRMED_IN_BAR_FILL_UNVERIFIED', None
    return 'HOLD', None

if __name__ == '__main__':
    b=Bar(0,100,102,98,101)
    assert classify('LONG',0,99,b)[0]=='STOP_TOUCHED_FILL_UNVERIFIED'
    assert classify('SHORT',0,101,b)[0]=='STOP_TOUCHED_FILL_UNVERIFIED'
    assert classify('LONG',0,101,b)==('GAP_THROUGH_STOP',100)
    assert classify('SHORT',0,99,b)==('GAP_THROUGH_STOP',100)
    assert classify('LONG',30000,99,b)[0]=='INTRABAR_ENTRY_UNKNOWN_PATH'
    assert classify('LONG',60000,99,b)[0]=='BEFORE_ENTRY'
    assert classify('LONG',0,97,b,opposite_confirm_ms=30000)[0]=='OPPOSITE_CONFIRMED_IN_BAR_FILL_UNVERIFIED'
    assert classify('LONG',0,97,b)[0]=='HOLD'
    print('8/8 synthetic assertions passed; NO real fills validated')
