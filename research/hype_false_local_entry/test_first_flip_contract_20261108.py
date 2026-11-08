"""Regression contract: full-denominator first-flip scoring, never subset precision."""
import unittest
from types import SimpleNamespace

from research.hype_false_local_entry.first_flip_path_audit import score_first_flips


def label(i, side, price):
    return {"label_id": str(i), "side": side,
            "extreme_interval_start_ms": i * 60000, "extreme_price": price}


def flip(minute, side, price):
    return SimpleNamespace(ts_ms=minute * 60000, side=side, close=price,
                           stage="HARD_CONFIRMED", core_flip=True)


class FirstFlipContract(unittest.TestCase):
    def test_wrong_first_cannot_be_rescued_by_later_correct_flip(self):
        labels = [label(0, "LOW", 100), label(10, "HIGH", 110)]
        flips = [flip(2, "HIGH", 101), flip(3, "LOW", 102)]
        result = score_first_flips([], labels, flips)
        self.assertEqual(result["detected_locals"], 0)
        self.assertEqual(result["missed_locals"], 2)
        self.assertEqual(result["false_first"], 2)
        self.assertEqual(result["first_signal_precision"], 0)

    def test_full_denominator_and_path_metrics(self):
        labels = [label(0, "LOW", 100), label(10, "HIGH", 110),
                  label(20, "LOW", 105)]
        flips = [flip(2, "LOW", 102), flip(12, "HIGH", 108)]
        bars = [{"ts_ms": minute*60000, "bar_end_ms": (minute+1)*60000,
                 "low": 101 if minute == 4 else 103,
                 "high": 109 if minute == 14 else 107}
                for minute in range(2, 20)]
        result = score_first_flips(bars, labels, flips)
        self.assertEqual(result["finalized_locals"], 3)
        self.assertEqual(result["complete_swings"], 2)
        self.assertEqual(result["detected_locals"], 2)
        self.assertEqual(result["missed_locals"], 1)
        self.assertAlmostEqual(result["first_signal_precision"], 1)
        self.assertAlmostEqual(result["matched"][0]["entry_distance_bps"], 200)
        self.assertAlmostEqual(result["matched"][0]["remaining_swing_fraction"], 0.8)
        self.assertGreater(result["matched"][0]["adverse_extension_bps"], 0)

    def test_unassigned_flips_are_false(self):
        labels = [label(0, "LOW", 100), label(10, "HIGH", 110)]
        flips = [flip(2, "LOW", 102), flip(3, "LOW", 103), flip(12, "HIGH", 108)]
        result = score_first_flips([], labels, flips)
        self.assertEqual(result["detected_locals"], 2)
        self.assertEqual(result["false_first"], 1)
        self.assertAlmostEqual(result["first_signal_precision"], 2/3)


if __name__ == "__main__":
    unittest.main()
