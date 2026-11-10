"""Regression tests for first-signal attribution; no orders, no market access."""
import unittest
from types import SimpleNamespace
from .first_flip_path_audit import score_first_flips


def label(i, side, minute, price):
    return {"label_id": i, "side": side,
            "extreme_interval_start_ms": minute * 60000,
            "extreme_price": price}


def flip(minute, side, price, stage="HARD_CONFIRMED"):
    return SimpleNamespace(ts_ms=minute * 60000, side=side,
                           close=price, stage=stage)


class FirstFlipAccountingTests(unittest.TestCase):
    def setUp(self):
        self.labels = [label(1, "LOW", 0, 100),
                       label(2, "HIGH", 20, 110),
                       label(3, "LOW", 40, 102)]
        self.bars = [{"ts_ms": m * 60000, "high": 111, "low": 99,
                      "close": 105} for m in range(1, 61)]

    def test_wrong_first_not_rescued_by_later_correct_flip(self):
        result = score_first_flips(self.bars, self.labels, [
            flip(3, "HIGH", 101), flip(4, "LOW", 102),
            flip(24, "HIGH", 108), flip(44, "LOW", 104)])
        self.assertFalse(result["matched"][0]["detected"])
        self.assertTrue(result["matched"][0]["first_signal_wrong_side"])
        self.assertEqual(result["completed_swing_true_first"], 1)
        self.assertEqual(result["completed_swing_wrong_first"], 1)
        self.assertEqual(result["total_core_flips"], 4)
        self.assertEqual(result["completed_swing_false_first"], 3)

    def test_no_signal_distinct_from_wrong_first(self):
        result = score_first_flips(self.bars, self.labels, [
            flip(24, "LOW", 108), flip(44, "LOW", 104)])
        self.assertFalse(result["matched"][0]["first_signal_present"])
        self.assertTrue(result["matched"][1]["first_signal_wrong_side"])
        self.assertEqual(result["completed_swing_missed"], 2)
        self.assertEqual(result["completed_swing_wrong_first"], 1)

    def test_terminal_local_not_a_completed_swing(self):
        result = score_first_flips(self.bars, self.labels, [
            flip(3, "LOW", 102), flip(24, "HIGH", 108),
            flip(44, "LOW", 104)])
        self.assertEqual(result["finalized_locals"], 3)
        self.assertEqual(result["complete_swings"], 2)
        self.assertEqual(result["completed_swing_true_first"], 2)
        self.assertEqual(result["completed_swing_false_first"], 1)
        self.assertEqual(result["first_signal_precision"], 1)
        self.assertAlmostEqual(result["completed_swing_first_signal_precision"], 2 / 3)


if __name__ == "__main__":
    unittest.main()
