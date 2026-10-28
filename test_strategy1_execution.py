import unittest

import local_order_flow as flow


def m15(side, *, partial=False, recovery=3, adverse=0, median=.008):
    return {
        "ready": True,
        "partial": partial,
        "return_15m": .002 * side,
        "candle_direction": side,
        "recovery_score": recovery,
        "adverse_score": adverse,
        "median_range_move": median,
    }


def tape(side, imbalance=.20):
    return {
        "trade_data_fresh": True,
        "latest_trade_age_seconds": 1,
        "buy_volume_60s": 120 if side > 0 else 80,
        "sell_volume_60s": 80 if side > 0 else 120,
        "flow_imbalance": imbalance * side,
    }


class Strategy1ExecutionTests(unittest.TestCase):
    def test_exit_uses_first_completed_opposite_m15(self):
        pos = {"side": -1}
        self.assertEqual(flow.pressure_exit(pos, m15(1), 100, tape(1)),
                         "m15_opposite_control_exit")
        self.assertIsNone(flow.pressure_exit(pos, m15(1, partial=True), 100, tape(1)))

    def test_reentry_rejects_first_tick_and_partial_candle(self):
        watch = {"side": -1, "exit_price": 100,
                 "context": {"phase": "WAIT_RESUMPTION", "counter_pressure_seen": True,
                             "pullback_extreme": 102}}
        self.assertFalse(flow.reentry_ready(-1, m15(-1), 101.97, watch, tape(-1), 0))
        self.assertFalse(flow.reentry_ready(-1, m15(-1, partial=True), 101.8, watch, tape(-1), 0))

    def test_reentry_requires_flow_and_m15_quality(self):
        watch = {"side": -1, "exit_price": 100,
                 "context": {"phase": "WAIT_RESUMPTION", "counter_pressure_seen": True,
                             "pullback_extreme": 102}}
        self.assertFalse(flow.reentry_ready(-1, m15(-1), 101.8, watch, tape(-1, .08), 0))
        self.assertFalse(flow.reentry_ready(-1, m15(-1, recovery=1), 101.8, watch, tape(-1), 0))
        self.assertFalse(flow.reentry_ready(-1, m15(-1, adverse=2), 101.8, watch, tape(-1), 0))
        self.assertTrue(flow.reentry_ready(-1, m15(-1), 101.8, watch, tape(-1), 0))

    def test_entry_candidate_uses_same_resumption_gate(self):
        analysis = {"ready": True, "h1_direction_anchor": True,
                    "entry_blocked": False, "entry_side": 1}
        self.assertFalse(flow.entry_candidate("INIT", analysis, m15(1), tape(1, .08), 0)["eligible"])
        self.assertTrue(flow.entry_candidate("INIT", analysis, m15(1), tape(1), 0)["eligible"])


if __name__ == "__main__":
    unittest.main()
