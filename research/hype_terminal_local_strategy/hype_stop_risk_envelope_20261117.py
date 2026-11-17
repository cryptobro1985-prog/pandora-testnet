"""Research-only deterministic risk envelope; not exchange fill replay."""
from math import isfinite

def envelope(equity, entry, stop, side, fee_fraction, slippage_fraction, gap_fraction, risk_fraction, leverage=25, aggregate_risk_fraction=0.01, existing_reserved_risk=0):
    vals=(equity,entry,stop,fee_fraction,slippage_fraction,gap_fraction,risk_fraction,leverage,aggregate_risk_fraction,existing_reserved_risk)
    if any(not isfinite(x) for x in vals) or equity<=0 or entry<=0 or stop<=0 or leverage<=0: raise ValueError('invalid numeric input')
    if side not in ('LONG','SHORT'): raise ValueError('invalid side')
    if (side=='LONG' and stop>=entry) or (side=='SHORT' and stop<=entry): raise ValueError('stop wrong side')
    if any(x<0 for x in (fee_fraction,slippage_fraction,gap_fraction,risk_fraction,aggregate_risk_fraction,existing_reserved_risk)): raise ValueError('negative budget')
    adverse=abs(entry-stop)/entry
    unit_loss=adverse+fee_fraction+slippage_fraction+gap_fraction
    remaining=max(0,equity*aggregate_risk_fraction-existing_reserved_risk)
    risk_cash=min(equity*risk_fraction,remaining)
    notional=risk_cash/unit_loss if unit_loss else 0
    return dict(side=side,stop_distance=adverse,stress_unit_loss=unit_loss,allowed_loss_cash=risk_cash,notional=notional,account_exposure=notional/equity,initial_margin=notional/leverage,remaining_aggregate_risk=remaining,model_only=True)

def tests():
    a=envelope(100,100,99,'LONG',.0015,.001,.005,.0025)
    b=envelope(100,100,101,'SHORT',.0015,.001,.005,.0025)
    assert abs(a['notional']-b['notional'])<1e-12
    assert abs(a['account_exposure']-(.0025/.0175))<1e-12
    assert abs(a['initial_margin']-a['notional']/25)<1e-12
    c=envelope(100,100,99,'LONG',.0015,.001,.005,.005,existing_reserved_risk=.9)
    assert abs(c['allowed_loss_cash']-.1)<1e-10
    d=envelope(100,100,99,'LONG',.0015,.001,.005,.005,existing_reserved_risk=1)
    assert d['notional']==0
    for args in [(100,100,101,'LONG'),(100,100,99,'SHORT'),(100,100,100,'LONG')]:
        try: envelope(*args,.0015,.001,.005,.0025)
        except ValueError: pass
        else: raise AssertionError('invalid stop accepted')
    print('PASS 7/7 deterministic budget checks; no historical fills verified')
if __name__=='__main__': tests()
