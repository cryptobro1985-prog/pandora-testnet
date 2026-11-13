import unittest
from research.hype_terminal_local_strategy.portfolio_accounting_research import evaluate

def trade(a,b,side,move,exposure=.2,cost=.0025):
    return dict(entry_ts_ms=a,exit_ts_ms=b,side=side,underlying_return_fraction=move,account_exposure=exposure,roundtrip_cost_fraction=cost)

class TestPortfolio(unittest.TestCase):
    def test_compound(self):
        r=evaluate([trade(1000,2000,"LONG",.02),trade(3000,4000,"SHORT",-.01)])
        self.assertAlmostEqual(r["end_equity"],100*(1+.2*(.02-.0025))*(1+.2*(-.01-.0025)))
    def test_overlap_rejected(self):
        with self.assertRaises(ValueError):
            evaluate([trade(1000,3000,"LONG",.01),trade(2000,4000,"SHORT",.01)])
    def test_loss_and_dd(self):
        r=evaluate([trade(1000,2000,"LONG",-.02)])
        self.assertAlmostEqual(r["max_closed_drawdown_fraction"],.0045)
    def test_funding_cost(self):
        t=trade(1000,2000,"SHORT",.02);t["funding_fraction"]=.001
        self.assertAlmostEqual(evaluate([t])["end_equity"],100*(1+.2*(.02-.0035)))
    def test_infinite_rejected(self):
        t=trade(1000,2000,"LONG",float("inf"))
        with self.assertRaises(ValueError): evaluate([t])
    def test_liquidation_rejected(self):
        with self.assertRaises(ValueError): evaluate([trade(1000,2000,"LONG",-1.0,exposure=5)])
if __name__=="__main__": unittest.main()
