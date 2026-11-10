"""Regression checks for causal completed-M1 decision timestamps.

Run: python -m unittest research.hype_false_local_entry.test_causal_decision_bars
"""
import unittest
from types import SimpleNamespace

import numpy as np

from research.hype_false_local_entry.full116_candidate_features import causal_decision_bars


class CausalDecisionBarsTests(unittest.TestCase):
    def setUp(self):
        self.tape = SimpleNamespace(end=np.array([60_000, 120_000, 180_000, 240_000, 300_000], dtype=np.int64))

    def test_no_decision_before_or_at_candidate_timestamp(self):
        self.assertEqual(list(causal_decision_bars(self.tape, 120_000, 5)), [2, 3, 4])
        self.assertEqual(list(causal_decision_bars(self.tape, 120_001, 5)), [2, 3, 4])

    def test_first_completed_bar_after_intrabar_extreme(self):
        self.assertEqual(list(causal_decision_bars(self.tape, 90_000, 5)), [1, 2, 3, 4])

    def test_candidate_replacement_is_exclusive(self):
        self.assertEqual(list(causal_decision_bars(self.tape, 90_000, 3)), [1, 2])

    def test_start_bar_and_empty_window(self):
        self.assertEqual(list(causal_decision_bars(self.tape, 90_000, 5, start_bar=3)), [3, 4])
        self.assertEqual(list(causal_decision_bars(self.tape, 300_000, 5)), [])

    def test_no_fixed_age_gate(self):
        # A candidate just before a completed bar gets an immediate opportunity,
        # even when its age is far below 30/60/300 seconds.
        self.assertEqual(list(causal_decision_bars(self.tape, 119_999, 3)), [1, 2])


if __name__ == "__main__":
    unittest.main()
