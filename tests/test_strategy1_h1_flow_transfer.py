import unittest
from unittest.mock import patch

import app


class Strategy1H1FlowTransferTests(unittest.TestCase):
    def flow(self, i60, i180, i300, r300, age=1.0):
        return {
            "trade_data_fresh": True,
            "latest_trade_age_seconds": age,
            "flow_imbalance": i60,
            "flow_imbalance_180s": i180,
            "flow_imbalance_300s": i300,
            "price_return_300s": r300,
            "volume_source": "bybit_v5_public_trade",
        }

    def test_persistent_seller_control_blocks_false_local_low(self):
        with patch.object(app.MARKET_OBS, "flow_context",
                          return_value=self.flow(-.30, -.22, -.18, -.012)):
            x = app.strategy1_h1_flow_transfer("INIT", 1, 1000)
        self.assertFalse(x["confirmed"])
        self.assertEqual(x["reason"], "opposite_structure_but_previous_side_still_controls")

    def test_buyer_control_transfer_confirms_local_low(self):
        with patch.object(app.MARKET_OBS, "flow_context",
                          return_value=self.flow(.28, .19, .12, .009)):
            x = app.strategy1_h1_flow_transfer("INIT", 1, 1000)
        self.assertTrue(x["confirmed"])

    def test_absorbed_buying_does_not_confirm_local_low(self):
        # Aggressive buys dominate, but price still falls: sellers are absorbing.
        with patch.object(app.MARKET_OBS, "flow_context",
                          return_value=self.flow(.35, .25, .16, -.006)):
            x = app.strategy1_h1_flow_transfer("INIT", 1, 1000)
        self.assertFalse(x["confirmed"])

    def test_seller_control_transfer_confirms_local_high(self):
        with patch.object(app.MARKET_OBS, "flow_context",
                          return_value=self.flow(-.24, -.16, -.11, -.008)):
            x = app.strategy1_h1_flow_transfer("GRASS", -1, 1000)
        self.assertTrue(x["confirmed"])

    def test_missing_m3_m5_coverage_fails_closed(self):
        flow = {
            "trade_data_fresh": True,
            "latest_trade_age_seconds": 1,
            "flow_imbalance": .5,
            "flow_imbalance_180s": None,
            "flow_imbalance_300s": None,
            "price_return_300s": None,
        }
        with patch.object(app.MARKET_OBS, "flow_context", return_value=flow):
            x = app.strategy1_h1_flow_transfer("INIT", 1, 1000)
        self.assertFalse(x["confirmed"])
        self.assertEqual(x["reason"], "waiting_for_m1_m3_m5_flow_coverage")


if __name__ == "__main__":
    unittest.main()
