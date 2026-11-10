"""Regression checks for strict completed-minute reachability and false-first accounting.

Run: python -m unittest research.hype_false_local_entry.test_exact_minute_contract
No orders or live connections.
"""
import unittest
from .audit_dense_coverage import evaluate
from .dense_causal_reachability import dense_completed_m1_candidates
from .first_flip_path_audit import score_first_flips
from .causal_sequential_engine import Signal

T = 1_800_000_000_000

def label(side, start, price, label_id):
    return dict(side=side, extreme_interval_start_ms=start,
                extreme_interval_end_ms=start + 60000,
                extreme_price=price, label_id=label_id)

class ExactMinuteContract(unittest.TestCase):
    def test_same_minute_reachable_and_neighbor_rejected(self):
        bars = [dict(ts_ms=T+60000, low=99, high=101),
                dict(ts_ms=T+120000, low=99, high=101)]
        events = list(dense_completed_m1_candidates(bars))
        self.assertEqual(evaluate(events, [label("LOW", T, 99, "a")],
                                  tolerance_ms=0, price_tolerance_bps=0)["covered"], 1)
        # A neighboring completed candle with the same price is not a match.
        only_neighbor = [e for e in events if e["signal_ts_ms"] == T+120000]
        self.assertEqual(evaluate(only_neighbor, [label("LOW", T, 99, "a")],
                                  tolerance_ms=0, price_tolerance_bps=0)["covered"], 0)

    def test_wrong_first_cannot_be_repaired(self):
        labels = [label("LOW", T, 99, "low"), label("HIGH", T+600000, 110, "high")]
        flips = [Signal(T+120000, "HIGH", "HARD_CONFIRMED", 5, 110, 101, True),
                 Signal(T+180000, "LOW", "HARD_CONFIRMED", 5, 99, 102, True)]
        out = score_first_flips([], labels, flips)
        self.assertEqual(out["completed_swing_wrong_first"], 1)
        self.assertEqual(out["completed_swing_true_first"], 0)
        self.assertEqual(out["completed_swing_missed"], 1)

    def test_early_never_flips_core(self):
        machine_source = __import__(
            "research.hype_false_local_entry.causal_sequential_engine",
            fromlist=["CausalReversalMachine"])
        machine = machine_source.CausalReversalMachine()
        bars = [dict(ts_ms=T+(i+1)*60000, high=101+i*0.001,
                     low=99+i*0.001, close=100+i*0.001,
                     buy_notional=100, sell_notional=100) for i in range(35)]
        events = [event for bar in bars for event in machine.on_bar(bar)]
        self.assertTrue(all(not event.core_flip for event in events
                            if event.stage in ("WATCH", "FORMING", "EARLY_PROBE", "CONFIRMED")))

if __name__ == "__main__":
    unittest.main()
