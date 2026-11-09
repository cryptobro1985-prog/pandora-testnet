"""Regression checks for full-scope reconciliation; synthetic data only, orders OFF."""
import copy
import unittest
from .verify_full_replay import verify


def fixture():
    scopes = {}
    coverage = {}
    for name, n in (("internal", 122), ("strict", 76)):
        rows = [{"label_id": f"{name}-{i}", "side": "LOW" if i % 2 == 0 else "HIGH",
                 "detected": False, "first_signal_wrong_side": False,
                 "first_signal_present": False} for i in range(n)]
        scopes[name] = {
            "finalized_locals": n, "complete_swings": n - 1, "matched": rows,
            "completed_swing_true_first": 0, "completed_swing_wrong_first": 0,
            "completed_swing_missed": n - 1, "total_core_flips": 0,
            "completed_swing_false_first": 0,
            "completed_swing_first_signal_precision": 0,
            "completed_swing_recall": 0,
        }
        coverage[name] = {"finalized": n, "covered": n, "missed": 0, "recall": 1}
    return {"orders": "OFF", "core_flip_policy": "HARD_CONFIRMED_OR_ULTRA_CONFIRMED_ONLY",
            "candidate_generation": coverage, "first_signal": scopes}


class FullReplayRegression(unittest.TestCase):
    def test_complete_contract(self):
        result = verify(fixture())
        self.assertEqual(len(result["scopes"]["internal"]["ledger"]), 121)
        self.assertEqual(len(result["scopes"]["strict"]["ledger"]), 75)

    def test_missing_candidate_rejected(self):
        data = fixture()
        data["candidate_generation"]["internal"].update(covered=121, missed=1)
        with self.assertRaises(ValueError):
            verify(data)

    def test_missing_local_row_rejected(self):
        data = fixture()
        data["first_signal"]["internal"]["matched"].pop()
        with self.assertRaises(ValueError):
            verify(data)

    def test_duplicate_label_rejected(self):
        data = fixture()
        data["first_signal"]["internal"]["matched"][1]["label_id"] = "internal-0"
        with self.assertRaises(ValueError):
            verify(data)

    def test_early_core_flip_rejected(self):
        data = fixture()
        row = data["first_signal"]["strict"]["matched"][0]
        row.update(first_signal_present=True, stage="EARLY_PROBE")
        with self.assertRaises(ValueError):
            verify(data)

    def test_orders_must_be_off(self):
        data = fixture()
        data["orders"] = "ON"
        with self.assertRaises(ValueError):
            verify(data)


if __name__ == "__main__":
    unittest.main()
