"""Regression guards for the complete INTERNAL/STRICT first-signal denominator.

Run: python -m unittest research.hype_false_local_entry.test_full_scope_first_signal_contract
No network, orders, or teacher data enter the causal signal engine.
"""
import unittest
from types import SimpleNamespace

from .first_flip_path_audit import score_first_flips


class FullScopeFirstSignalContract(unittest.TestCase):
    def labels(self, n):
        return [
            {"label_id": f"turn-{i}", "side": "LOW" if i % 2 == 0 else "HIGH",
             "extreme_interval_start_ms": i * 3_600_000,
             "extreme_price": 100 if i % 2 == 0 else 110}
            for i in range(n)
        ]

    def test_full_internal_and_strict_denominators_with_no_signals(self):
        for n, swings in ((122, 121), (76, 75)):
            with self.subTest(n=n):
                result = score_first_flips([], self.labels(n), [])
                self.assertEqual(result["finalized_locals"], n)
                self.assertEqual(result["complete_swings"], swings)
                self.assertEqual(result["detected_locals"], 0)
                self.assertEqual(result["missed_locals"], n)
                self.assertEqual(result["missed_local_rate"], 1.0)
                self.assertIsNone(result["first_signal_precision"])

    def test_wrong_first_cannot_be_rescued_by_later_correct_flip(self):
        labels = self.labels(2)
        wrong = SimpleNamespace(ts_ms=60_000, side="HIGH", stage="HARD_CONFIRMED", close=105)
        later = SimpleNamespace(ts_ms=120_000, side="LOW", stage="ULTRA_CONFIRMED", close=104)
        result = score_first_flips([], labels, [wrong, later])
        self.assertEqual(result["detected_locals"], 0)
        self.assertEqual(result["false_first"], 2)
        self.assertEqual(result["missed_locals"], 2)
        self.assertEqual(result["first_signal_precision"], 0.0)

    def test_first_correct_and_later_duplicate_count_separately(self):
        labels = self.labels(2)
        first = SimpleNamespace(ts_ms=60_000, side="LOW", stage="HARD_CONFIRMED", close=102)
        duplicate = SimpleNamespace(ts_ms=120_000, side="LOW", stage="ULTRA_CONFIRMED", close=103)
        result = score_first_flips([], labels, [first, duplicate])
        self.assertEqual(result["detected_locals"], 1)
        self.assertEqual(result["false_first"], 1)
        self.assertAlmostEqual(result["first_signal_precision"], 0.5)
        self.assertEqual(result["complete_swings"], 1)


if __name__ == "__main__":
    unittest.main()
