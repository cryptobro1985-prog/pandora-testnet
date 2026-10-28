import unittest

import local_order_flow as flow


def tape(side, a15, a30, a60, event=1000.0, *, fresh=True, counts=(6, 12, 24)):
    """Build raw tape values from imbalances aligned to the H1 side."""
    raw15, raw30, raw60 = side * a15, side * a30, side * a60
    def volumes(imbalance, total):
        return total * (1 + imbalance) / 2, total * (1 - imbalance) / 2
    b15, s15 = volumes(raw15, 1000)
    b30, s30 = volumes(raw30, 2000)
    b60, s60 = volumes(raw60, 4000)
    return {
        "trade_data_fresh": fresh,
        "latest_trade_age_seconds": 1,
        "volume_window_end_epoch": event + 1,
        "flow_imbalance_15s": raw15,
        "flow_imbalance_30s": raw30,
        "flow_imbalance": raw60,
        "buy_volume_15s": b15,
        "sell_volume_15s": s15,
        "buy_volume_30s": b30,
        "sell_volume_30s": s30,
        "buy_volume_60s": b60,
        "sell_volume_60s": s60,
        "trade_count_15s": counts[0],
        "trade_count_30s": counts[1],
        "trade_count_60s": counts[2],
    }


class Strategy1ExecutedFlowTests(unittest.TestCase):
    def test_counter_takeover_exits_long_and_short_without_m15(self):
        for side in (-1, 1):
            pos = {"side": side, "entry": 100, "features": {"estimated_round_trip_cost_move": .001}}
            counter = tape(side, -.30, -.20, .02)
            mark = 100 + side * 1
            self.assertEqual(flow.pressure_exit(pos, None, mark, counter),
                             "executed_flow_profit_flip_exit")

    def test_red_or_green_m15_never_substitutes_for_executed_takeover(self):
        for side in (-1, 1):
            pos = {"side": side, "entry": 100}
            aligned = tape(side, .30, .20, .15)
            hostile_m15 = {"ready": True, "partial": False, "return_15m": -side * .02,
                           "candle_direction": -side, "adverse_score": 5}
            self.assertIsNone(flow.pressure_exit(pos, hostile_m15, 99, aligned))

    def test_sparse_stale_or_one_print_flow_cannot_flip_control(self):
        pos = {"side": -1, "entry": 100}
        self.assertIsNone(flow.pressure_exit(pos, None, 99, tape(-1, -.5, -.4, 0, counts=(1, 1, 1))))
        self.assertIsNone(flow.pressure_exit(pos, None, 99, tape(-1, -.5, -.4, 0, fresh=False)))

    def test_losing_trade_exits_on_real_counter_takeover_too(self):
        pos = {"side": -1, "entry": 100, "features": {"estimated_round_trip_cost_move": .001}}
        self.assertEqual(flow.pressure_exit(pos, None, 101, tape(-1, -.30, -.20, -.05)),
                         "executed_flow_risk_flip_exit")

    def test_restart_during_established_counter_control_still_exits(self):
        pos = {"side": 1, "entry": 100}
        self.assertEqual(flow.pressure_exit(pos, None, 99, tape(1, -.30, -.22, -.15)),
                         "executed_flow_risk_flip_exit")

    def test_reentry_requires_counter_then_later_h1_side_takeover(self):
        for side in (-1, 1):
            watch = {"side": side, "exit_price": 100, "context": {"phase": "WAIT_COUNTER_CONTROL"}}
            counter = tape(side, -.30, -.20, .02, event=1000)
            watch = flow.update_watch(watch, 100 - side, None, counter, 1001)
            self.assertEqual(watch["context"]["phase"], "WAIT_RESUMPTION")
            self.assertFalse(flow.reentry_ready(side, None, 100, watch, counter, 1001))

            same_event_resumption = tape(side, .30, .20, .05, event=1000)
            self.assertFalse(flow.reentry_ready(side, None, 100, watch, same_event_resumption, 1001))

            later_resumption = tape(side, .30, .20, .05, event=1002)
            self.assertTrue(flow.reentry_ready(side, None, 100, watch, later_resumption, 1003))

            established_resumption = tape(side, .30, .20, .12, event=1004)
            self.assertTrue(flow.reentry_ready(side, None, 100, watch, established_resumption, 1005))

    def test_reentry_stays_blocked_while_counter_side_still_dominates(self):
        watch = {"side": -1, "exit_price": 100, "context": {"phase": "WAIT_COUNTER_CONTROL"}}
        watch = flow.update_watch(watch, 101, None, tape(-1, -.30, -.20, -.05, event=1000), 1001)
        still_buying = tape(-1, -.20, -.15, -.10, event=1002)
        self.assertFalse(flow.reentry_ready(-1, None, 101.2, watch, still_buying, 1003))

    def test_initial_entry_uses_h1_side_and_live_aggressor_control_only(self):
        analysis = {"ready": True, "h1_direction_anchor": True,
                    "entry_blocked": False, "entry_side": 1}
        self.assertTrue(flow.entry_candidate("INIT", analysis, None,
                                             tape(1, .25, .15, .10), 0)["eligible"])
        self.assertFalse(flow.entry_candidate("INIT", analysis, None,
                                              tape(1, -.25, -.15, -.10), 0)["eligible"])


if __name__ == "__main__":
    unittest.main()
