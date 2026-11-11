"""Contract regression checks for confirmed-local bounce CV.

Run: python -m unittest research.hype_false_local_entry.test_confirmed_bounce_contract
"""
import unittest

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

    def test_no_features_not_misreported_as_coverage(self):
        result = cv.predictor_coverage({"period_a": [{"features": {}}]})["period_a"]
        self.assertEqual(result["available_point_count"], 0)
        self.assertEqual(result["decision_rows"], 1)


if __name__ == "__main__":
    unittest.main()
