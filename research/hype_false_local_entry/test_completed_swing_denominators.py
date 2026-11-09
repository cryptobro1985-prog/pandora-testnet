"""Regression for finalized-local vs completed-swing denominators (paper only)."""
import unittest
from types import SimpleNamespace
from .first_flip_path_audit import score_first_flips


class CompletedSwingDenominatorTests(unittest.TestCase):
    def test_terminal_local_is_not_completed_swing(self):
        labels = [
            {"label_id": str(i), "side": "LOW" if i % 2 == 0 else "HIGH",
             "extreme_interval_start_ms": i * 120000,
             "extreme_price": 100 if i % 2 == 0 else 110}
            for i in range(3)
        ]
        flips = [SimpleNamespace(ts_ms=60000, side="LOW",
                                 stage="HARD_CONFIRMED", close=101)]
        scored = score_first_flips([], labels, flips)
        self.assertEqual(scored["finalized_locals"], 3)
        self.assertEqual(scored["complete_swings"], 2)
        self.assertEqual(scored["detected_locals"], 1)
        self.assertEqual(scored["completed_swing_true_first"], 1)
        self.assertEqual(scored["completed_swing_missed"], 1)
        self.assertEqual(scored["completed_swing_recall"], 0.5)
        self.assertEqual(scored["completed_swing_missed_rate"], 0.5)

    def test_wrong_first_not_replaced_by_later_correct(self):
        labels = [
            {"label_id": "a", "side": "LOW", "extreme_interval_start_ms": 0,
             "extreme_price": 100},
            {"label_id": "b", "side": "HIGH", "extreme_interval_start_ms": 120000,
             "extreme_price": 110},
        ]
        flips = [
            SimpleNamespace(ts_ms=60000, side="HIGH",
                            stage="HARD_CONFIRMED", close=102),
            SimpleNamespace(ts_ms=90000, side="LOW",
                            stage="HARD_CONFIRMED", close=103),
        ]
        scored = score_first_flips([], labels, flips)
        self.assertEqual(scored["completed_swing_true_first"], 0)
        self.assertEqual(scored["completed_swing_wrong_first"], 1)
        self.assertEqual(scored["false_first"], 2)
        self.assertEqual(scored["first_signal_precision"], 0.0)


if __name__ == "__main__":
    unittest.main()
