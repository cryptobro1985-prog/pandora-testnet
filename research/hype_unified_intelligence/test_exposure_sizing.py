#!/usr/bin/env python3
"""Paper-only sizing, margin, and liquidation-cushion regression tests."""
import unittest
from research.hype_unified_intelligence.exposure_sizing import (
    ExposureScenario,evaluate,scenario_grid
)

class SizingTest(unittest.TestCase):
    def test_25x_20pct_margin_rejected(self):
        x=evaluate(ExposureScenario(25,.20))
        self.assertEqual(x["result"],"REJECT")
        self.assertGreater(x["assumed_stressed_equity_loss_pct"],7.)
        self.assertFalse(x["real_orders"])

    def test_5x_5pct_margin_passes_bounded_scenario(self):
        x=evaluate(ExposureScenario(5,.05))
        self.assertEqual(x["result"],"PAPER_STRESS_PASS")
        self.assertAlmostEqual(x["assumed_stressed_equity_loss_pct"],.3875)
        self.assertGreater(x["liquidation_cushion_multiple"],4.)

    def test_3x_10pct_margin_passes_bounded_scenario(self):
        x=evaluate(ExposureScenario(3,.10))
        self.assertEqual(x["result"],"PAPER_STRESS_PASS")
        self.assertAlmostEqual(x["assumed_stressed_equity_loss_pct"],.465)

    def test_25x_even_2pct_rejected_due_cushion(self):
        x=evaluate(ExposureScenario(25,.02))
        self.assertEqual(x["result"],"REJECT")
        self.assertFalse(x["liquidation_cushion_gate_pass"])

    def test_10x_3pct_passes_bounded_scenario(self):
        x=evaluate(ExposureScenario(10,.03))
        self.assertEqual(x["result"],"PAPER_STRESS_PASS")
        self.assertLessEqual(x["assumed_stressed_equity_loss_pct"],.5)

    def test_invalid_scenario_rejected(self):
        for s in (ExposureScenario(0,.1),ExposureScenario(5,1.1),
                  ExposureScenario(5,.1,equity_risk_budget=0)):
            with self.assertRaises(ValueError):
                evaluate(s)

    def test_all_grid_research_only(self):
        g=scenario_grid()
        self.assertEqual(len(g),8*6)
        self.assertTrue(all(not x["real_orders"] for x in g))

if __name__=="__main__":unittest.main()
