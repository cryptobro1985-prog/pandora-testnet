import unittest
from research.hype_terminal_local_strategy.causal_exit_replay_research import replay

def bar(t,lo,hi,cl,opp="0",avail=0,side="LONG"):
    return dict(ts_ms=t,low=lo,high=hi,close=cl,opposite_confirmed=opp,
                available_ts_ms=avail,side=side,entry_price=100)
class TestCausalExitReplay(unittest.TestCase):
    def test_long_stop_first(self):
        x=replay([bar(100,98,103,98,"1",100)])
        self.assertEqual(x["exit_reason"],"STOP")
        self.assertAlmostEqual(x["net_equity_pct"],-.45)
    def test_short_stop_first(self):
        self.assertEqual(replay([bar(100,97,102,102,"1",100,"SHORT")])["exit_reason"],"STOP")
    def test_long_opposite(self):
        x=replay([bar(100,100,103,102,"1",100)])
        self.assertAlmostEqual(x["net_equity_pct"],.35)
    def test_future_signal_not_allowed(self):
        self.assertEqual(replay([bar(100,100,103,102,"1",101)])["exit_reason"],"OPEN")
    def test_delayed_signal(self):
        x=replay([bar(100,100,103,102,"1",101),bar(101,101,104,103,"1",101)])
        self.assertEqual(x["exit_reason"],"OPPOSITE")
    def test_intrabar_drawdown(self):
        self.assertLess(replay([bar(100,99.1,102,101)])["worst_intrabar_equity_pct"],0)
    def test_mfe_giveback(self):
        self.assertAlmostEqual(replay([bar(100,100,104,102,"1",100)])["giveback_fraction"],.5)
    def test_bad_bar(self):
        with self.assertRaises(ValueError): replay([bar(100,101,100,100)])
    def test_bad_time_order(self):
        with self.assertRaises(ValueError):
            replay([bar(100,99.1,100.9,100),bar(100,99.1,100.9,100)])
if __name__=="__main__": unittest.main()
