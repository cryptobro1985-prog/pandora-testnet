"""Research-only latency-aware event gate; NOT a fill simulator.
No orders. Event timestamps must share a validated clock domain.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Observation:
    exchange_ms:int
    received_ms:int
    sequence:int
    kind:str
    price:float

def causal_replay(side,entry_price,entry_received_ms,observations,stop_pct=.01,entry_exchange_ms=None):
    if side not in ('LONG','SHORT') or entry_price<=0 or stop_pct<=0: raise ValueError('position')
    direction=1 if side=='LONG' else -1
    stop=entry_price*(1-direction*stop_pct)
    seen=set(); prev_exchange=None; prev_receive=entry_received_ms
    mfe=0.; mae=0.; outcome=None; processed=0
    for e in observations:
        if e.received_ms<e.exchange_ms or e.price<=0 or e.kind not in ('trade','opposite_available'):
            raise ValueError('invalid event')
        if e.received_ms<prev_receive: raise ValueError('receive order')
        prev_receive=e.received_ms
        if e.received_ms<=entry_received_ms or (entry_exchange_ms is not None and e.exchange_ms<=entry_exchange_ms): continue
        key=(e.exchange_ms,e.sequence)
        if key in seen: raise ValueError('duplicate')
        seen.add(key)
        if prev_exchange is not None and e.exchange_ms<prev_exchange: raise ValueError('exchange reorder: require reconciliation')
        prev_exchange=e.exchange_ms
        processed+=1
        if e.kind=='opposite_available':
            outcome='OPPOSITE_SIGNAL_NOT_FILL';break
        move=direction*(e.price/entry_price-1)
        mfe=max(mfe,move);mae=min(mae,move)
        if (direction==1 and e.price<=stop) or (direction==-1 and e.price>=stop):
            outcome='STOP_TRIGGER_NOT_FILL';break
    return dict(outcome=outcome,mfe_pct=mfe*100,mae_pct=mae*100,processed=processed,fill_verified=False)

def self_test():
    O=Observation
    a=causal_replay('LONG',100,100,[O(101,120,1,'trade',98),O(121,140,2,'trade',105)])
    assert a['outcome']=='STOP_TRIGGER_NOT_FILL' and a['mfe_pct']==0
    b=causal_replay('SHORT',100,100,[O(101,120,1,'trade',102),O(121,140,2,'trade',95)])
    assert b['outcome']=='STOP_TRIGGER_NOT_FILL' and b['mfe_pct']==0
    c=causal_replay('LONG',100,100,[O(101,120,1,'trade',103),O(121,140,2,'opposite_available',103)])
    assert c['outcome']=='OPPOSITE_SIGNAL_NOT_FILL' and round(c['mfe_pct'])==3
    d=causal_replay('LONG',100,100,[O(99,101,1,'trade',98),O(101,120,2,'trade',105)],entry_exchange_ms=100)
    assert d['outcome'] is None and round(d['mfe_pct'])==5
    for events in ([O(110,109,1,'trade',100)],[O(110,120,1,'trade',100),O(111,121,1,'trade',100),O(110,122,2,'trade',100)]):
        try: causal_replay('LONG',100,100,events)
        except ValueError: pass
        else: raise AssertionError('bad event accepted')
    return '6 synthetic assertions passed'
if __name__=='__main__': print(self_test())
