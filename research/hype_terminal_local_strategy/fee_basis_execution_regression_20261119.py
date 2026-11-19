"""Research-only fee basis test. Synthetic executions, NOT Bybit trade replay."""
from math import isclose, isfinite

def fees(entry_price, exit_price, qty, entry_rate, exit_rate):
    assert all(isfinite(v) for v in (entry_price, exit_price, qty, entry_rate, exit_rate))
    assert entry_price > 0 and exit_price > 0 and qty > 0
    assert 0 <= entry_rate < 1 and 0 <= exit_rate < 1
    return qty * (entry_price * entry_rate + exit_price * exit_rate)

def run():
    cases = [('LONG',100,120,.165,.150),('LONG',100,80,.135,.150),
             ('SHORT',100,120,.165,.150),('SHORT',100,80,.135,.150)]
    for side, entry, exit_price, expected, old in cases:
        actual = fees(entry, exit_price, 1, .00075, .00075)
        assert isclose(actual, expected, abs_tol=1e-12)
        assert isclose(actual-old, .00075*(exit_price-entry), abs_tol=1e-12)
        print(side, entry, exit_price, 'correct', actual, 'old', old, 'delta', actual-old)
    print('PASS 4 synthetic fee-basis regressions; NO historical fills')

if __name__ == '__main__':
    run()
