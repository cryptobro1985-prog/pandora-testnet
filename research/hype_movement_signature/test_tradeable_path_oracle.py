import unittest
from datetime import datetime,timezone
from tradeable_path_oracle import benchmark

def rows(prices,dt=60):
    return [(i*dt,float(p),float(p),float(p)) for i,p in enumerate(prices)]

class OracleTests(unittest.TestCase):
    def test_flat_market_no_trades(self):
        self.assertEqual(benchmark(rows([100]*10),.0025)["trade_count"],0)
    def test_zigzag_exceeds_net_move(self):
        r=benchmark(rows([100,102,100,103,101,106]),.0025,0,0)
        self.assertGreater(r["total_net_pct"],6)
        self.assertGreater(r["long_net_pct"],0)
        self.assertGreater(r["short_net_pct"],0)
    def test_costs_reduce_upper_bound(self):
        p=rows([100,101,100,102])
        a=benchmark(p,.0025,0,0)["total_net_pct"]
        b=benchmark(p,.0025,10,5)["total_net_pct"]
        self.assertGreaterEqual(a,b)
    def test_gap_blocks_trade(self):
        p=[(0,100,100,100),(3600,110,110,110)]
        self.assertEqual(benchmark(p,.0025)["trade_count"],0)
    def test_no_negative_trades(self):
        r=benchmark(rows([100,101,99,103,97,102]),.0025)
        self.assertTrue(all(t["net_underlying_pct"]>0 for t in r["trades"]))

if __name__=="__main__":unittest.main()
