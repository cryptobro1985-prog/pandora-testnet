"""Research-only preflight for M1 execution claims; no real fills or orders."""
from math import isfinite

def assess(side, entry_ms, entry_price, stop_price, bar, tick_size=None):
    if side not in ('LONG','SHORT'): return 'INVALID_SIDE'
    prices=[entry_price,stop_price,*[bar[k] for k in ('open','high','low','close')]]
    if any(not isfinite(v) or v<=0 for v in prices): return 'INVALID_PRICE'
    o,h,l,c=(bar[k] for k in ('open','high','low','close'))
    if not l<=min(o,c)<=max(o,c)<=h: return 'INVALID_OHLC'
    if (side=='LONG' and stop_price>=entry_price) or (side=='SHORT' and stop_price<=entry_price): return 'INVALID_STOP_SIDE'
    start=int(bar['start_ms'])
    if entry_ms<start: return 'POSITION_PREEXISTS_BAR_STOP_PATH_UNRESOLVED'
    if entry_ms>=start+60000: return 'ENTRY_AFTER_BAR'
    if entry_ms>start: return 'ENTRY_INSIDE_BAR_UNKNOWN_PATH'
    tolerance=tick_size/2 if tick_size is not None else 0
    if abs(entry_price-o)>tolerance: return 'ENTRY_PRICE_NOT_BAR_OPEN_FILL_UNVERIFIED'
    if (side=='LONG' and o<=stop_price) or (side=='SHORT' and o>=stop_price): return 'STOP_ALREADY_BREACHED_AT_ENTRY'
    if (side=='LONG' and l<=stop_price) or (side=='SHORT' and h>=stop_price): return 'STOP_TOUCHED_FILL_UNVERIFIED'
    return 'NO_STOP_TOUCH_FILL_STILL_UNVERIFIED'

def test():
    b={'start_ms':0,'open':100.,'high':103.,'low':98.,'close':101.}
    cases=[('LONG',0,100,99,b,'STOP_TOUCHED_FILL_UNVERIFIED'),('SHORT',0,100,101,b,'STOP_TOUCHED_FILL_UNVERIFIED'),('LONG',0,102,99,b,'ENTRY_PRICE_NOT_BAR_OPEN_FILL_UNVERIFIED'),('SHORT',0,98,101,b,'ENTRY_PRICE_NOT_BAR_OPEN_FILL_UNVERIFIED'),('LONG',30000,100,99,b,'ENTRY_INSIDE_BAR_UNKNOWN_PATH'),('LONG',60000,100,99,b,'ENTRY_AFTER_BAR'),('LONG',-60000,100,99,b,'POSITION_PREEXISTS_BAR_STOP_PATH_UNRESOLVED'),('LONG',0,100,101,b,'INVALID_STOP_SIDE'),('LONG',0,100,97,b,'NO_STOP_TOUCH_FILL_STILL_UNVERIFIED'),('SHORT',0,100,104,b,'NO_STOP_TOUCH_FILL_STILL_UNVERIFIED')]
    for side,t,e,s,bar,want in cases:
        got=assess(side,t,e,s,bar)
        assert got==want,(got,want)
    print('PASS 10/10 synthetic entry-bar causality cases; zero historical fills validated')
if __name__=='__main__': test()
