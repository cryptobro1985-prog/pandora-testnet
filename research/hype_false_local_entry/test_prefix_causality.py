"""Prefix-invariance contracts for the completed-M1 HYPE research engine.

Run: python -m unittest research.hype_false_local_entry.test_prefix_causality
No orders, labels or future observations are used.
"""
import unittest

from .dense_causal_reachability import dense_completed_m1_candidates
from .causal_sequential_engine import CausalReversalMachine


def sample_bars(n=90):
    bars = []
    for i in range(n):
        close = 100 + (i % 17 - 8) * 0.15
        bars.append(dict(ts_ms=(i + 1) * 60000,
                         low=close - 0.1, high=close + 0.1,
                         close=close, buy_notional=100 + (i % 5) * 10,
                         sell_notional=100 + (i % 7) * 10))
    return bars


class PrefixCausalityTests(unittest.TestCase):
    def test_dense_candidates_are_prefix_invariant_and_not_signals(self):
        bars = sample_bars()
        all_events = list(dense_completed_m1_candidates(bars))
        for n in (1, 2, 30, 60, 89):
            prefix = list(dense_completed_m1_candidates(bars[:n]))
            self.assertEqual(prefix, all_events[:2*n])
            self.assertTrue(all(not x["entry_signal"] for x in prefix))
            self.assertTrue(all(x["signal_ts_ms"] > x["extreme_ts_ms"]
                                for x in prefix))

    def test_first_signals_do_not_depend_on_future_bars(self):
        bars = sample_bars()
        machine = CausalReversalMachine()
        all_events = []
        for bar in bars:
            all_events.extend(machine.on_bar(bar))
        for n in (29, 30, 45, 60, 89):
            fresh = CausalReversalMachine()
            prefix_events = []
            for bar in bars[:n]:
                prefix_events.extend(fresh.on_bar(bar))
            self.assertEqual(prefix_events,
                             [e for e in all_events if e.ts_ms <= n * 60000])
        self.assertTrue(all(not e.core_flip or
                            e.stage in ("HARD_CONFIRMED", "ULTRA_CONFIRMED")
                            for e in all_events))

    def test_no_core_flip_on_early_or_confirmed(self):
        machine = CausalReversalMachine()
        for bar in sample_bars():
            for event in machine.on_bar(bar):
                if event.stage in ("WATCH", "FORMING", "EARLY_PROBE", "CONFIRMED"):
                    self.assertFalse(event.core_flip)


if __name__ == "__main__":
    unittest.main()
