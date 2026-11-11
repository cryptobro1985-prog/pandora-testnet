import unittest
from tradeable_path_oracle_v2 import oracle

def r(p,dt=60):
    return [(i*dt,float(x),float(x),float(x)) for i,x in enumerate(p)]

class Tests(unittest.TestCase):
    def test_flat(self):
        self.assertEqual(oracle(r([100]*8))["trade_count"],0)
    def test_zigzag(self):
        x=oracle(r([100,102,100,103,101,106]),fee_bps=0,slip_bps=0)
        self.assertGreater(x["total_net_pct"],6)
    def test_gap(self):
        self.assertEqual(oracle([(0,100,100,100),(3600,110,110,110)])["trade_count"],0)
    def test_cooldown_reduces_or_equal(self):
        p=r([100,102,100,102,100,102])
        a=oracle(p,fee_bps=0,slip_bps=0,cooldown_seconds=0)["total_net_pct"]
        b=oracle(p,fee_bps=0,slip_bps=0,cooldown_seconds=120)["total_net_pct"]
        self.assertGreaterEqual(a,b)
    def test_hold_constraint(self):
        p=r([100,105,100])
        a=oracle(p,fee_bps=0,slip_bps=0,min_hold_seconds=60)["total_net_pct"]
        b=oracle(p,fee_bps=0,slip_bps=0,min_hold_seconds=180)["total_net_pct"]
        self.assertGreater(a,b)
    def test_fee(self):
        p=r([100,102,100,103])
        a=oracle(p,fee_bps=0,slip_bps=0)["total_net_pct"]
        b=oracle(p,fee_bps=10,slip_bps=5)["total_net_pct"]
        self.assertGreaterEqual(a,b)

if __name__=="__main__":unittest.main()
