"""Research-only regression: delayed pre-entry exchange events must not trigger stops.
No live orders; does not establish fill quality or historical returns.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Event:
    exchange_ms: int
    received_ms: int
    price: float
    kind: str = 'trade'

def gate(side, entry_price, entry_exchange_ms, entry_received_ms, events, stop_pct=.01):
    if side not in ('LONG','SHORT') or entry_price <= 0 or stop_pct <= 0:
        raise ValueError('invalid position')
    if entry_exchange_ms is None or entry_received_ms is None:
        raise ValueError('both entry clocks required')
    direction = 1 if side == 'LONG' else -1
    stop = entry_price * (1 - direction * stop_pct)
    last_receive = entry_received_ms
    eligible = []
    for e in events:
        if e.received_ms < last_receive or e.price <= 0:
            raise ValueError('invalid event sequence')
        last_receive = e.received_ms
        if e.exchange_ms <= entry_exchange_ms or e.received_ms <= entry_received_ms:
            continue
        eligible.append(e)
    if any(b.exchange_ms < a.exchange_ms for a,b in zip(eligible, eligible[1:])):
        raise ValueError('exchange reorder: reconcile first')
    mfe = 0.0
    for e in eligible:
        if e.kind == 'opposite_available':
            return {'status':'OPPOSITE_SIGNAL_NOT_FILL','mfe_pct':100*mfe}
        if e.kind != 'trade':
            raise ValueError('unknown event kind')
        movement = direction*(e.price/entry_price-1)
        if (direction==1 and e.price <= stop) or (direction==-1 and e.price >= stop):
            return {'status':'STOP_TRIGGER_NOT_FILL','mfe_pct':100*mfe}
        mfe=max(mfe,movement)
    return {'status':'UNRESOLVED','mfe_pct':100*mfe}

def test():
    for side, pre, post in [('LONG',98,103),('SHORT',102,97)]:
        result=gate(side,100,100,110,[Event(90,120,pre),Event(130,140,post)])
        assert result['status']=='UNRESOLVED' and round(result['mfe_pct'])==3
        result=gate(side,100,100,110,[Event(120,130,pre),Event(140,150,post)])
        assert result['status']=='STOP_TRIGGER_NOT_FILL' and result['mfe_pct']==0
    try: gate('LONG',100,None,110,[])
    except ValueError: pass
    else: raise AssertionError('missing exchange entry time accepted')
    try: gate('LONG',100,100,110,[Event(140,150,101),Event(130,160,102)])
    except ValueError: pass
    else: raise AssertionError('exchange reordering accepted')
    return '6 regression checks passed'
if __name__=='__main__': print(test())
