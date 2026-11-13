"""Research-only HYPE stop-risk sizing regression."""
import unittest
from research.hype_terminal_local_strategy.risk_budget_research import RiskInputs, max_notional_fraction, planned_max_loss_fraction

class TestRiskBudget(unittest.TestCase):
    def test_quarter_percent(self):
        p=RiskInputs(.01,.0025)
        self.assertAlmostEqual(max_notional_fraction(p),.2)
        self.assertAlmostEqual(planned_max_loss_fraction(p),.0025)
    def test_half_percent(self):
        self.assertAlmostEqual(max_notional_fraction(RiskInputs(.01,.005)),.4)
    def test_slippage(self):
        self.assertLess(max_notional_fraction(RiskInputs(.01,.005,extra_slippage_fraction=.004)),.4)
    def test_leverage_is_margin_cap(self):
        self.assertAlmostEqual(max_notional_fraction(RiskInputs(.01,.005,exchange_leverage=1,max_margin_fraction=.2)),.2)
    def test_invalid_stop(self):
        with self.assertRaises(ValueError):
            max_notional_fraction(RiskInputs(0,.005))
    def test_funding_reserved(self):
        self.assertLess(max_notional_fraction(RiskInputs(.01,.005,expected_funding_fraction=.0005)),.4)

if __name__=="__main__":
    unittest.main()
