"""Safety invariants for causal first-signal replay (no exchange orders)."""
import unittest
from .causal_sequential_engine import CausalReversalMachine, Signal

def bar(i, *, ts=None, end=None, high=101., low=99., close=100.):
    t = i * 60000 if ts is None else ts
    d = {"ts_ms": t, "high": high, "low": low, "close": close,
         "buy_notional": 100., "sell_notional": 100.}
    if end is not None:
        d["bar_end_ms"] = end
    return d

class TestCausalBarInvariants(unittest.TestCase):
    def test_reject_overlapping_bar_even_if_end_increases(self):
        m = CausalReversalMachine()
        m.on_bar(bar(0))
        with self.assertRaisesRegex(ValueError, "overlapping"):
            m.on_bar(bar(0, ts=30000, end=90000))

    def test_reject_zero_duration(self):
        m = CausalReversalMachine()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            m.on_bar(bar(0, end=0))  # fallback end is one minute
        # explicit negative interval is invalid
    def test_invalid_bar_does_not_advance_clock(self):
        m = CausalReversalMachine()
        with self.assertRaises(ValueError):
            m.on_bar(bar(0, high=99., low=101.))
        self.assertIsNone(m.last_ts)
        m.on_bar(bar(0))
        self.assertEqual(m.last_ts, 60000)

    def test_no_flip_below_hard(self):
        m = CausalReversalMachine()
        for i in range(30):
            events = m.on_bar(bar(i))
            self.assertTrue(all(not e.core_flip or e.stage in
                                ("HARD_CONFIRMED", "ULTRA_CONFIRMED") for e in events))
        self.assertLessEqual(sum(e.core_flip for e in m.events if e.ts_ms == 30*60000), 1)

if __name__ == "__main__":
    unittest.main()
