import unittest

import local_order_flow as flow


def tape(side, a300, price_aligned, event=1000.0, *, fresh=True, coverage=320):
    """Build M5 executed flow and price response aligned to the H1 side."""
    raw300 = side * a300
    price_return = side * price_aligned
    total = 10000.0
    buy300 = total * (1 + raw300) / 2
    sell300 = total * (1 - raw300) / 2
    return {
        "trade_data_fresh": fresh,
        "latest_trade_age_seconds": 1,
        "trade_coverage_seconds": coverage,
        "volume_window_end_epoch": event + 1,
        "flow_imbalance_300s": raw300,
        "buy_volume_300s": buy300,
        "sell_volume_300s": sell300,
        "trade_count_300s": 100,
        "price_return_300s": price_return,
        "flow_imbalance": raw300,
        "flow_imbalance_15s": raw300,
        "flow_imbalance_30s": raw300,
    }


class Strategy1ExecutedFlowTests(unittest.TestCase):
    def test_counter_flow_only_exits_when_price_responds(self):
        for side in (-1, 1):
            pos = {"side": side, "entry": 100}
            effective_counter = tape(side, -.25, -.01)
            self.assertIsNotNone(flow.pressure_exit(pos, None, 100 - side, effective_counter))
            absorbed_counter = tape(side, -.25, .002)
            self.assertIsNone(flow.pressure_exit(pos, None, 100, absorbed_counter))

    def test_short_buying_without_price_rise_holds(self):
        pos = {"side": -1, "entry": 100}
        # Buyers dominate raw flow, but price still falls: sellers absorb them.
        absorbed_buying = tape(-1, -.30, .006)
        self.assertIsNone(flow.pressure_exit(pos, None, 99.4, absorbed_buying))

    def test_long_selling_without_price_drop_holds(self):
        pos = {"side": 1, "entry": 100}
        # Sellers dominate raw flow, but price still rises: buyers absorb them.
        absorbed_selling = tape(1, -.30, .006)
        self.assertIsNone(flow.pressure_exit(pos, None, 100.6, absorbed_selling))

    def test_reentry_accepts_resumed_flow_or_failed_counterflow(self):
        for side in (-1, 1):
            watch = {"side": side, "exit_price": 100,
                     "context": {"phase": "WAIT_COUNTER_CONTROL"}}
            counter = tape(side, -.30, -.01, event=1000)
            watch = flow.update_watch(watch, 100 - side, None, counter, 1001)
            self.assertEqual(watch["context"]["phase"], "WAIT_RESUMPTION")

            resumed = tape(side, .20, .006, event=1002)
            self.assertTrue(flow.reentry_ready(side, None, 100 + side, watch, resumed, 1003))

            failed_counter = tape(side, -.20, .006, event=1004)
            self.assertTrue(flow.reentry_ready(side, None, 100 + side, watch, failed_counter, 1005))

    def test_initial_entry_needs_h1_side_flow_and_matching_price_response(self):
        analysis = {"ready": True, "h1_direction_anchor": True,
                    "entry_blocked": False, "entry_side": 1}
        self.assertTrue(flow.entry_candidate("INIT", analysis, None,
                                             tape(1, .20, .005), 0)["eligible"])
        self.assertFalse(flow.entry_candidate("INIT", analysis, None,
                                              tape(1, .20, -.005), 0)["eligible"])
        self.assertFalse(flow.entry_candidate("INIT", analysis, None,
                                              tape(1, -.20, .005), 0)["eligible"])

    def test_stale_or_not_warmed_m5_flow_cannot_trade(self):
        pos = {"side": -1, "entry": 100}
        self.assertIsNone(flow.pressure_exit(pos, None, 101, tape(-1, -.3, -.01, fresh=False)))
        self.assertIsNone(flow.pressure_exit(pos, None, 101, tape(-1, -.3, -.01, coverage=120)))


if __name__ == "__main__":
    unittest.main()
