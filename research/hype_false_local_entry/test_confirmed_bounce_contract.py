"""Contract regression checks for confirmed-local bounce CV.

Run: python -m unittest research.hype_false_local_entry.test_confirmed_bounce_contract
"""
import unittest
from unittest.mock import patch

from research.hype_false_local_entry import confirmed_local_bounce_cv as cv
from research.hype_quant.feature_contract import INPUT_IDS


class ConfirmedBounceContractTests(unittest.TestCase):
    def test_input_contract_size(self):
        self.assertEqual(len(INPUT_IDS), 86)

    def test_malformed_and_nonfinite_values_rejected(self):
        for name in ("", "unknown", "p999_not_a_real_point"):
            self.assertFalse(cv.legal_predictor(name, 1.0))
        for value in (None, float("nan"), float("inf"), "3.14", True, False, cv.np.bool_(True)):
            self.assertFalse(cv.legal_predictor("p001_any", value))

    def test_empty_certified_micro_not_counted(self):
        rows = {"period_a": [
            {"clean_features": {}, "features": {}},
            {"clean_features": {"unknown": 1.0}, "features": {}},
        ]}
        audit = cv.micro_provenance(rows)["period_a"]
        self.assertEqual(audit["decision_rows"], 2)
        self.assertEqual(audit["certified_micro_rows"], 0)
        self.assertFalse(audit["rich_micro_validated_for_cv"])

    def test_event_sampling_reaches_inventory(self):
        # Verify the CLI-facing CV builder does not silently revert to the
        # legacy candidate-age grid.
        with patch.object(cv.replay, "inventory", return_value=({}, {})) as inventory:
            periods, rows = cv.build("unused-master", decision_sampling="completed_m1_events")
        inventory.assert_called_once_with(
            "unused-master", {}, decision_sampling="completed_m1_events"
        )
        self.assertEqual(periods, {})
        self.assertEqual(rows, {})

    def test_post_extreme_confirmation_requires_observed_reversal(self):
        low = {"side": "LOW", "price": 100.0, "signal_price": 100.01}
        high = {"side": "HIGH", "price": 100.0, "signal_price": 99.99}
        self.assertTrue(cv.reversal_observed(low))
        self.assertTrue(cv.reversal_observed(high))
        for row in (
            {**low, "signal_price": 100.0},
            {**low, "signal_price": 99.99},
            {**high, "signal_price": 100.0},
            {**high, "signal_price": 100.01},
            {**low, "signal_price": float("nan")},
        ):
            self.assertFalse(cv.reversal_observed(row))

    def test_model_cannot_fit_only_pre_reversal_rows(self):
        rows = [
            {"side": "LOW", "price": 100.0, "signal_price": 100.0,
             "terminal": False, "features": {"p001_any": 1.0}, "candidate_id": "a"},
            {"side": "LOW", "price": 100.0, "signal_price": 99.9,
             "terminal": True, "features": {"p001_any": 2.0}, "candidate_id": "b"},
        ]
        with self.assertRaisesRegex(ValueError, "Post-reversal training"):
            cv.fit(rows, ["p001_any"])

    def test_no_features_not_misreported_as_coverage(self):
        result = cv.predictor_coverage({"period_a": [{"features": {}}]})["period_a"]
        self.assertEqual(result["available_point_count"], 0)
        self.assertEqual(result["decision_rows"], 1)


if __name__ == "__main__":
    unittest.main()
