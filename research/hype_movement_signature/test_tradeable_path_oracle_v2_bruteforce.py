"""Independent brute-force audit of the hindsight path DP (tiny inputs only)."""
import itertools
import unittest
from tradeable_path_oracle_v2 import oracle

def rows(prices, step=60):
    return [(i*step, float(p), float(p), float(p)) for i,p in enumerate(prices)]

def brute(prices, threshold=.0025, cost_bps=0, hold=60, cooldown=60):
    n=len(prices)
    friction=2*cost_bps/10000
    memo={}
    def solve(first):
        if first>=n-1: return 0.
        if first in memo:return memo[first]
        best=solve(first+1)
        for i in range(first,n-1):
            for j in range(i+1,n):
                if (j-i)*60<hold:continue
                for ret in (prices[j]/prices[i]-1-friction, 1-prices[j]/prices[i]-friction):
                    if ret<threshold:continue
                    next_first=next((k for k in range(j+1,n) if (k-j)*60>=max(cooldown,1e-9)),n)
                    best=max(best,ret+solve(next_first))
        memo[first]=best
        return best
    return solve(0)*100

class BruteForceAudit(unittest.TestCase):
    def test_exhaustive_small_paths(self):
        # 3^6 paths; verifies global optimum, not only plausible zigzags.
        for seq in itertools.product((99,100,101),repeat=6):
            actual=oracle(rows(seq),fee_bps=0,slip_bps=0,
                          min_hold_seconds=60,cooldown_seconds=60)
            expected=brute(seq)
            self.assertAlmostEqual(actual["total_net_pct"],expected,places=8,msg=str(seq))

    def test_no_trade_crosses_gap(self):
        rr=rows((100,101,102))+[(3600,105,105,105),(3660,106,106,106)]
        out=oracle(rr,fee_bps=0,slip_bps=0,max_gap_seconds=300)
        self.assertEqual(out["trade_count"],2)

    def test_strictly_positive_execution_cost(self):
        rr=[(0,100,99.95,100.05),(60,100.2,100.15,100.25)]
        out=oracle(rr,min_net_return=.001,fee_bps=6,slip_bps=2)
        self.assertEqual(out["trade_count"],0)

if __name__=="__main__":unittest.main()
