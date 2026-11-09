"""Regression checks for the full-contract research replay."""
import gzip
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

import numpy as np

from research.hype_false_local_entry import full116_candidate_features as f
from research.hype_false_local_entry import full116_sources as s
from research.hype_false_local_entry import full116_terminal_replay as r
from research.hype_false_local_entry.test_early_trajectory import bars


def cache_row():
    values = {"fullmicro_book_valid": 1, "fullmicro_book_crossed": 0,
              "fullmicro_spread_bps": 0.5, "fullmicro_book_gap_count": 0}
    for sec in f.WINDOWS:
        values[f"fullmicro_book_window_valid_{sec}s"] = 0
    for sec in f.LIQ_WINDOWS:
        values[f"fullmicro_liq_stream_valid_{sec}s"] = 0
    values.update(fullmicro_liq_stream_valid_60s=1, fullmicro_liq_count_60s=0,
                  fullmicro_long_liq_notional_60s=0, fullmicro_short_liq_notional_60s=0)
    return dict(side="LOW", candidate_ts_ms=1_000_000, snapshot_ts_ms=1_180_000, delay_s=180,
                extreme_price=72.391, strict_true=True, strict_label_id=83, features=values)


def decision(**changes):
    row = dict(side="LOW", candidate_ts_ms=1_000_000, signal_ts_ms=1_190_000,
               price=72.391, signal_price=72.7, retrace_bps=42.68, features={})
    return dict(row, **changes)


class Full116ReplayTest(unittest.TestCase):
    def test_m1_prefix_and_teacher_mutation_invariance(self):
        rows = bars()
        rows[376].update(low=97, close=98)
        for row in rows:
            row.update(volume=30, turnover=3000, trade_count=3, strict_true=True)
        _, full, _ = f.m1_states(rows)
        cutoff = rows[372]["bar_end_ms"]
        for row in rows:
            row.update(strict_true=False, strict_label_id=28, feature_107=9999)
        _, prefix, _ = f.m1_states(rows[:373])
        self.assertEqual(prefix, [x for x in full if x["signal_ts_ms"] <= cutoff])

    def test_m1_unknown_flow_is_not_a_zero_observation(self):
        rows = bars()
        rows[361].update(flow_observed=False, buy_notional=1000, sell_notional=0)
        _, snapshots, _ = f.m1_states(rows)
        first = next(x for x in snapshots if x["side"] == "LOW")
        self.assertNotIn("p017_m1_log_buy", first["features"])
        rows[361].update(flow_observed=True, buy_notional=0)
        _, snapshots, _ = f.m1_states(rows)
        first = next(x for x in snapshots if x["side"] == "LOW")
        self.assertEqual(first["features"]["p017_m1_log_buy"], 0)

    def test_replaced_candidate_never_decides_on_replacement_bar(self):
        rows = bars()
        rows[361].update(low=98, close=98.5)
        _, decisions, _ = f.m1_states(rows)
        self.assertNotIn(f"LOW-{rows[360]['low_ts_ms']}", {d["candidate_id"] for d in decisions})
        self.assertIn(f"LOW-{rows[361]['low_ts_ms']}", {d["candidate_id"] for d in decisions})

    def test_clean_features_exact_anchor_and_available_time(self):
        row = cache_row()
        s.validate_snapshot(row)
        index = f.snapshot_index([row])
        observed = f.clean_micro_features(decision(), index)
        self.assertEqual(observed["p072_count_60s"], 0)
        self.assertNotIn("p072_count_300s", observed)
        self.assertEqual(f.clean_micro_features(decision(signal_ts_ms=1_179_999), index), {})
        self.assertEqual(f.clean_micro_features(decision(price=72.392), index), {})
        self.assertEqual(f.clean_micro_features(decision(signal_ts_ms=1_240_000), index), {})

    def test_invalid_liquidation_and_book_are_rejected(self):
        row = cache_row()
        row["features"]["fullmicro_liq_count_300s"] = 0
        with self.assertRaisesRegex(ValueError, "unobserved liquidation"):
            s.validate_snapshot(row)
        row = cache_row()
        row["features"]["fullmicro_spread_bps"] = 0
        with self.assertRaisesRegex(ValueError, "invalid point book"):
            s.validate_snapshot(row)
        row = cache_row()
        del row["features"]["fullmicro_book_window_valid_60s"]
        with self.assertRaisesRegex(ValueError, "continuous book"):
            s.validate_snapshot(row)

    def test_checked_archive_rejects_older_producer(self):
        row = cache_row()
        payload = gzip.compress(json.dumps(row).encode())
        name = "candidate_snapshots_full_micro.jsonl.gz"
        audit = {"rows": 1, "book_valid_rows": 1,
                 "liq_valid_rows": {str(sec): int(sec == 60) for sec in f.LIQ_WINDOWS}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"cache.zip"
            def write(contract):
                with ZipFile(path, "w") as z:
                    z.writestr("manifest.json", json.dumps({"microstructure_quality_contract": contract}))
                    z.writestr("CLEAN_MICRO_AUDIT.json", json.dumps(audit))
                    z.writestr(name, payload)
                    z.writestr("artifact_manifest.json", json.dumps({
                        name: {"bytes": len(payload), "sha256": s.sha_bytes(payload)}}))
                return s.sha_bytes(path.read_bytes())
            self.assertEqual(len(s.read_clean_cache(path, write(f.MICRO_CONTRACT))), 1)
            with self.assertRaisesRegex(ValueError, "predates"):
                s.read_clean_cache(path, write("previous"))

    def test_stale_oi_cannot_appear_as_fresh_positioning(self):
        row = cache_row()
        row["features"].update(fullmicro_open_interest_sum_open_interest=1000,
                               fullmicro_open_interest_age_ms=295_000)
        index = f.snapshot_index([row])
        self.assertNotIn("p058_open_interest_log", f.clean_micro_features(decision(), index))
        self.assertIn("p058_open_interest_log",
                      f.clean_micro_features(decision(signal_ts_ms=1_182_000), index))

    def test_role_isolation_and_coverage_denominator(self):
        self.assertRaises(ValueError, f.put, {}, 83, bad=1.0)
        self.assertRaises(ValueError, f.put, {}, 82, bad=1.0)
        p = {"source": "verified", "period_utc": ["a", "b"], "decision_rows": 8,
             "counts": Counter({4: 6})}
        audit = s.coverage({"history": p}, {}, {}, predictor_ids={4})
        self.assertEqual(len(audit["points"]), 116)
        self.assertEqual(audit["points"][3]["historical"]["history"]["coverage_pct"], 75.0)
        self.assertFalse(audit["points"][106]["allowed_as_predictor"])
        self.assertIsNone(audit["points"][3]["live"]["coverage_pct"])

    def test_missing_predictors_use_an_explicit_indicator(self):
        x = np.array([[np.nan], [1.0], [3.0]])
        np.testing.assert_equal(r.transform(x, [1.0], [2.0], [0]),
                                [[0, 1], [0, 0], [1, 0]])


if __name__ == "__main__":
    unittest.main()
