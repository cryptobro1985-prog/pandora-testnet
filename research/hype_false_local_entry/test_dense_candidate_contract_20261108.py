"""Regression tests for causal completed-M1 candidate reachability; PAPER ONLY."""
import unittest

from .dense_causal_reachability import dense_completed_m1_candidates
from .audit_dense_coverage import evaluate


def bar(ts, low=99., high=101., **extra):
    return {"ts_ms": ts, "bar_end_ms": ts + 60000, "low": low, "high": high, **extra}


class DenseCandidateContract(unittest.TestCase):
    def test_both_sides_available_only_after_close(self):
        events = list(dense_completed_m1_candidates([bar(120000)]))
        self.assertEqual({e["side"] for e in events}, {"LOW", "HIGH"})
        self.assertTrue(all(e["signal_ts_ms"] == 180000 for e in events))
        self.assertTrue(all(not e["entry_signal"] for e in events))

    def test_price_mismatch_cannot_count_as_recall(self):
        events = list(dense_completed_m1_candidates([bar(120000)]))
        label = {"label_id": "l", "side": "LOW", "extreme_interval_start_ms": 120000,
                 "extreme_interval_end_ms": 180000, "extreme_price": 98.}
        result = evaluate(events, [label], tolerance_ms=60000, price_tolerance_bps=1)
        self.assertEqual((result["covered"], result["missed"]), (0, 1))

    def test_reachability_not_detector_recall(self):
        events = list(dense_completed_m1_candidates([bar(120000)]))
        label = {"label_id": "l", "side": "LOW", "extreme_interval_start_ms": 120000,
                 "extreme_interval_end_ms": 180000, "extreme_price": 99.}
        result = evaluate(events, [label])
        self.assertEqual(result["covered"], 1)
        self.assertTrue(all(e["entry_signal"] is False for e in events))

    def test_reject_overlapping_minutes(self):
        with self.assertRaises(ValueError):
            list(dense_completed_m1_candidates([bar(120000), bar(150000)]))

    def test_reject_extreme_timestamp_before_bar(self):
        with self.assertRaises(ValueError):
            list(dense_completed_m1_candidates([bar(120000, low_ts_ms=119999)]))

    def test_reject_extreme_timestamp_at_or_after_close(self):
        with self.assertRaises(ValueError):
            list(dense_completed_m1_candidates([bar(120000, high_ts_ms=180000)]))


if __name__ == "__main__":
    unittest.main()
