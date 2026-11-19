"""Research-only deterministic gap-reserved sizing. Not historical fills."""
from math import isfinite

def size(equity, risk, stop, fee, gap, exposure_cap=1):
    assert all(isfinite(x) for x in (equity,risk,stop,fee,gap,exposure_cap))
    assert equity>0 and 0<risk<=.005 and 0<stop<1 and fee>=0 and gap>=0 and exposure_cap>0
    return min(equity*risk/(stop+fee+gap), equity*exposure_cap)

def loss_fraction(notional,equity,adverse,fee):
    return notional/equity*(adverse+fee)

if __name__=='__main__':
    equity=100; stop=.01; fee=.0015
    for risk in (.0025,.005):
        for reserved_gap in (0,.005,.02):
            n=size(equity,risk,stop,fee,reserved_gap)
            print(f'risk={risk:.4%} gap_reserve={reserved_gap:.2%} notional={n:.4f} exposure={n/equity:.4f}x',end='')
            for actual_gap in (0,.005,.02):
                realized=loss_fraction(n,equity,stop+actual_gap,fee)
                print(f' actual_gap={actual_gap:.2%}:loss={realized:.4%}',end='')
            print()
    assert abs(loss_fraction(size(100,.005,.01,.0015,.02),100,.03,.0015)-.005)<1e-12
    assert loss_fraction(size(100,.005,.01,.0015,0),100,.03,.0015)>.005
    print('2 invariant checks passed')
