"""Regression checks for causal anchor persistence and flip policy. PAPER ONLY."""
import unittest
from .causal_sequential_engine import CausalReversalMachine, STAGES

def bar(i, low, high, close, buy=0, sell=0):
    return {"ts_ms": i * 60000, "bar_end_ms": (i+1)*60000,
            "low": low, "high": high, "close": close,
            "buy_notional": buy, "sell_notional": sell}

class AnchorRegression(unittest.TestCase):
    def test_anchor_does_not_expire_after_30m(self):
        machine = CausalReversalMachine()
        for i in range(45):
            machine.on_bar(bar(i, 90 if i == 0 else 95, 110, 100))
        self.assertEqual(machine.anchor["LOW"], 95)  # initialized after 30 bars
        for i in range(45, 90):
            machine.on_bar(bar(i, 94 if i == 45 else 95, 110, 100))
        self.assertEqual(machine.anchor["LOW"], 94)
        self.assertEqual(machine.anchor_end["LOW"], 46*60000)

    def test_no_early_core_flip(self):
        machine = CausalReversalMachine()
        for i in range(60):
            events = machine.on_bar(bar(i, 100, 101, 100.5))
            for event in events:
                if event.stage in ("WATCH", "FORMING", "EARLY_PROBE", "CONFIRMED"):
                    self.assertFalse(event.core_flip)

    def test_reject_out_of_order(self):
        machine = CausalReversalMachine()
        machine.on_bar(bar(0, 100, 101, 100.5))
        with self.assertRaises(ValueError):
            machine.on_bar(bar(0, 100, 101, 100.5))

if __name__ == "__main__":
    unittest.main()
