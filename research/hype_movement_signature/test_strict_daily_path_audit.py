import csv
import tempfile
import unittest
from pathlib import Path

from strict_daily_path_audit import audit


class StrictDailyPathAuditTest(unittest.TestCase):
    def write_rows(self, rows, fields=("timestamp", "price", "executable_bid", "executable_ask")):
        temp = tempfile.TemporaryDirectory()
        path = Path(temp.name) / "prices.csv"
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        self.addCleanup(temp.cleanup)
        return path

    def test_rejects_missing_bid_ask(self):
        path = self.write_rows([{"timestamp": "2026-11-10T00:00:00Z", "price": 100}],
                               fields=("timestamp", "price"))
        with self.assertRaisesRegex(ValueError, "bid/ask"):
            audit(path)

    def test_rejects_nonfinite_quotes(self):
        path = self.write_rows([{"timestamp": "2026-11-10T00:00:00Z",
                                "price": "nan", "executable_bid": 99, "executable_ask": 101}])
        with self.assertRaisesRegex(ValueError, "invalid"):
            audit(path)

    def test_incomplete_day_has_no_oracle(self):
        path = self.write_rows([{"timestamp": "2026-11-10T00:00:00Z",
                                "price": 100, "executable_bid": 99.99, "executable_ask": 100.01}])
        report = audit(path)
        day = report["days"]["2026-11-10"]
        self.assertEqual(day["status"], "REJECT_INCOMPLETE_COVERAGE")
        self.assertEqual(day["thresholds"], {})

    def test_complete_tiny_day_uses_strict_quotes(self):
        rows = [
            {"timestamp": f"2026-11-10T{i*6:02d}:00:00Z", "price": p,
             "executable_bid": p-0.01, "executable_ask": p+0.01}
            for i, p in enumerate([100, 102, 100, 102])
        ]
        path = self.write_rows(rows)
        report = audit(path, expected_step_seconds=21600, max_gap_seconds=21600, min_coverage=1.0)
        day = report["days"]["2026-11-10"]
        self.assertEqual(day["status"], "EVALUATION_ONLY")
        self.assertIn("0.0025", day["thresholds"])
        self.assertEqual(len(report["source_sha256"]), 64)


    def test_dense_burst_does_not_fake_daily_coverage(self):
        rows = [
            {"timestamp": f"2026-11-10T00:00:{i:02d}Z", "price": 100,
             "executable_bid": 99.99, "executable_ask": 100.01}
            for i in range(60)
        ]
        report = audit(self.write_rows(rows), expected_step_seconds=1440,
                       max_gap_seconds=300, min_coverage=0.95)
        day = report["days"]["2026-11-10"]
        self.assertEqual(day["status"], "REJECT_INCOMPLETE_COVERAGE")
        self.assertLess(day["coverage_fraction"], 0.95)

    def test_rejects_naive_datetime(self):
        path = self.write_rows([{"timestamp": "2026-11-10T00:00:00",
                                "price": 100, "executable_bid": 99.99,
                                "executable_ask": 100.01}])
        with self.assertRaisesRegex(ValueError, "timezone"):
            audit(path)

if __name__ == "__main__":
    unittest.main()
