"""Research-only fail-closed invariants for quote replay. Run from repository root:
python -m unittest research.hype_terminal_local_strategy.test_quote_event_replay_invariants
No historical fills are inferred from these synthetic cases.
"""
import unittest
from research.hype_terminal_local_strategy.quote_event_stop_replay_research import Event, replay

class QuoteReplayInvariants(unittest.TestCase):
    def test_long_stop_uses_bid_not_close(self):
        out = replay("LONG", 0, 100, [Event(1, 100, 100.2, 100), Event(2, 98.5, 98.7, 98.6)])
        self.assertEqual(out["reason"], "STOP")
        self.assertEqual(out["exit_quote"], 98.5)
        self.assertLess(out["net_pnl"], 0)

    def test_short_stop_uses_ask(self):
        out = replay("SHORT", 0, 100, [Event(1, 99.8, 100.2, 100), Event(2, 101.1, 101.3, 101.2)])
        self.assertEqual(out["reason"], "STOP")
        self.assertEqual(out["exit_quote"], 101.3)

    def test_same_timestamp_opposite_and_stop_unresolved(self):
        out = replay("LONG", 0, 100, [Event(1, 98.5, 98.7, 98.6, True)])
        self.assertEqual(out["status"], "ORDER_UNRESOLVED")

    def test_preentry_quote_rejected(self):
        with self.assertRaises(ValueError):
            replay("LONG", 10, 100, [Event(10, 99, 100, 99.5)])

    def test_crossed_quote_rejected(self):
        with self.assertRaises(ValueError):
            replay("SHORT", 0, 100, [Event(1, 101, 100, 100)])

    def test_opposite_exit_has_no_future_extreme(self):
        out = replay("LONG", 0, 100, [Event(1, 101, 101.2, 101.1), Event(2, 102, 102.2, 102.1, True), Event(3, 200, 201, 200)])
        self.assertEqual(out["reason"], "OPPOSITE")
        self.assertEqual(out["exit_quote"], 102)
        self.assertEqual(out["ts_ms"], 2)

    def test_stop_gap_worsens_loss(self):
        near = replay("LONG", 0, 100, [Event(1, 99, 99.2, 99.1)])
        gap = replay("LONG", 0, 100, [Event(1, 97, 97.2, 97.1)])
        self.assertLess(gap["net_pnl"], near["net_pnl"])
        self.assertEqual(near["notional"], gap["notional"])

if __name__ == "__main__":
    unittest.main()
