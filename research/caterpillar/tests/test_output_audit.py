"""Research-report regressions: no false significance or partial-run promotion."""
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from caterpillar import __version__
from caterpillar.model import Config
from caterpillar.output import Metric, Output, Profile, package_source_sha256


class OutputAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = Config(min_evidence=30, min_evidence_days=5)

    def tearDown(self):
        self.tmp.cleanup()

    def make_profile(self, days=5, keys=("evaluation/feature/LONG/filled_open_combined",), timestamps=True):
        p = Profile()
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        for day in range(days):
            ts = (base+timedelta(days=day)).timestamp()
            for _ in range(30):
                for key in keys:
                    p.outcome(key, 10, ts=ts if timestamps else None)
        return p

    def report(self, p, status="completed", suffix="run", summary=None):
        out = Output(self.root/suffix, self.config, ("ZEC",), "historical_research")
        out.finish({"ZEC": p}, summary or {}, self.config, status)
        result = json.loads((out.root/"caterpillar_24_7_candidates.json").read_text())
        return result, out

    def test_nonfinite_or_nonnumeric_outcomes_cannot_poison_reports(self):
        p = Profile()
        for value in (math.nan, math.inf, -math.inf, None, "profit", True, 10**1000):
            self.assertFalse(p.outcome("evaluation/exit/combined/LONG", value))
        self.assertEqual(p.outcomes, {})
        self.assertEqual(p.counts["quality/nonfinite_outcome"], 7)
        result, out = self.report(p)
        self.assertEqual(result["candidates"], [])
        self.assertTrue((out.root/"CATERPILLAR_RESEARCH_REPORT.md").is_file())

    def test_finite_extreme_values_produce_json_safe_statistics(self):
        metric = Metric()
        metric.add(1e308); metric.add(-1e308)
        result = metric.result()
        self.assertEqual(result["mean"], 0)
        self.assertIsNone(result["std"])
        self.assertEqual(result["std_status"], "numeric_overflow")
        json.dumps(result, allow_nan=False)
        p = Profile()
        p.outcome("evaluation/feature/LONG/LONG", -1e308)
        p.outcome("evaluation/feature/LONG/control", 1e308)
        result = p.result()
        self.assertIsNone(result["hypotheses"]["evaluation/feature/LONG/control"]["delta_vs_direction_baseline_bps"])
        json.dumps(result, allow_nan=False)

    def test_single_day_repeated_labels_never_meet_multiday_gate(self):
        p = self.make_profile(days=1)
        result, _ = self.report(p)
        self.assertEqual(result["candidates"], [])
        self.assertFalse(result["deployment_ready"])

    def test_partial_failed_interrupted_runs_cannot_promote_candidates(self):
        p = self.make_profile()
        for status in ("incomplete_coverage", "failed/SourceError", "interrupted"):
            result, _ = self.report(p, status=status, suffix=status.replace("/", "-"))
            self.assertTrue(result["suppressed_due_to_run_status"])
            self.assertEqual(result["candidates"], [])

    def test_generic_features_and_unconditional_direction_are_not_strategies(self):
        keys = ("evaluation/feature/LONG/LONG", "evaluation/feature/LONG/control",
                "evaluation/feature/LONG/filled_open_combined", "evaluation/feature/SHORT/filled_reentry_combined",
                "evaluation/exit/combined/LONG")
        p = self.make_profile(keys=keys)
        result, _ = self.report(p)
        self.assertEqual({x["hypothesis"] for x in result["candidates"]}, set(keys[2:]))
        self.assertTrue(all(x["evidence_status"] == "exploratory_only" for x in result["candidates"]))
        self.assertNotIn("wilson_95", result["candidates"][0])
        self.assertIn("wilson_95_iid_reference_only", result["candidates"][0])

    def test_missing_outcome_timestamps_never_qualify_as_multiday_evidence(self):
        result, _ = self.report(self.make_profile(timestamps=False))
        self.assertEqual(result["candidates"], [])

    def test_same_side_baseline_and_sample_counts_are_explicit(self):
        p = Profile()
        p.outcome("evaluation/feature/LONG/LONG", 4)
        p.outcome("evaluation/feature/LONG/LONG", 8)
        p.outcome("evaluation/feature/LONG/control", 8)
        p.outcome("evaluation/feature/SHORT/SHORT", -100)
        row = p.result()["hypotheses"]["evaluation/feature/LONG/control"]
        self.assertEqual(row["delta_vs_direction_baseline_bps"], 2)
        self.assertEqual(row["baseline_samples"], 2)
        self.assertIn("subset is included", row["baseline_scope"])

    def test_daily_statistics_are_bounded_and_eviction_blocks_selection(self):
        p = self.make_profile(days=129)
        row = p.result()["hypotheses"]["evaluation/feature/LONG/filled_open_combined"]
        self.assertEqual(row["observed_utc_days"], 128)
        self.assertEqual(row["evicted_daily_buckets"], 1)
        self.assertEqual(row["daily_mean_median_net_bps"], 10)
        result, _ = self.report(p)
        self.assertEqual(result["candidates"], [])

    def test_exit_comparison_separates_closed_censored_and_open_positions(self):
        p = Profile()
        p.count("combined/closed", 2); p.count("combined/censored", 1)
        p.add("combined/net_usd", 5); p.add("combined/net_usd", -1)
        p.add("combined/mfe", 20); p.add("combined/mae", -2)
        result, out = self.report(p, summary={"open_books_not_realized": {"ZEC": {"combined": {"position": {"entry": 100}}}}})
        text = (out.root/"CATERPILLAR_RESEARCH_REPORT.md").read_text()
        self.assertIn("| combined | 2 | 1 | 1 | 4.0000 | 2.0000 | 20.0000 | -2.0000 |", text)
        self.assertIn("not paired trials", text)
        self.assertNotIn("are paired counterfactual", text)
        self.assertIn("own-side absorption veto", text)

    def test_manifest_fingerprints_actual_package_source_and_version(self):
        _, out = self.report(Profile())
        meta = json.loads((out.root/"run_manifest.json").read_text())
        self.assertEqual(meta["status"], "completed")
        self.assertEqual(meta["package_version"], __version__)
        self.assertEqual(meta["package_source_sha256"], package_source_sha256())
        self.assertEqual(len(meta["package_source_sha256"]), 64)

    def test_failed_report_finalization_closes_streams_and_does_not_claim_completed(self):
        out = Output(self.root/"broken", self.config, ("ZEC",), "historical_research")
        original = out.save_json
        def save(name, value):
            if name == "research_summary.json": raise OSError("fixture")
            return original(name, value)
        with patch.object(out, "save_json", side_effect=save):
            with self.assertRaises(OSError): out.finish({"ZEC": Profile()}, {}, self.config, "completed")
        self.assertTrue(all(handle.closed for handle in out.handles.values()))
        self.assertEqual(json.loads((out.root/"run_manifest.json").read_text())["status"], "finalizing")

    def test_unfilled_entry_and_reentry_signals_never_qualify(self):
        p = self.make_profile(keys=("evaluation/feature/LONG/open_combined",
                                    "evaluation/feature/SHORT/reentry_combined"))
        result, _ = self.report(p)
        self.assertEqual(result["candidates"], [])

    def test_concurrent_output_writers_cannot_mix_one_run(self):
        directory = self.root/"racing"
        directory.mkdir()
        barrier = threading.Barrier(2)
        original = Path.iterdir
        created, rejected = [], []
        def scan(path):
            entries = list(original(path))
            if path == directory:
                barrier.wait(timeout=3)
            return iter(entries)
        def create():
            try:
                created.append(Output(directory, self.config, ("ZEC",), "test"))
            except ValueError as exc:
                rejected.append(str(exc))
        with patch.object(Path, "iterdir", scan):
            threads = [threading.Thread(target=create) for _ in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(5)
        self.assertEqual(len(created), 1)
        self.assertEqual(len(rejected), 1)
        created[0].finish({"ZEC": Profile()}, {}, self.config, "completed")

    def test_failed_stream_initialization_closes_already_opened_files(self):
        original = Path.open
        opened = []
        def open_file(path, *args, **kwargs):
            if path.name == "locals.jsonl": raise OSError("fixture")
            handle = original(path, *args, **kwargs)
            opened.append(handle)
            return handle
        with patch.object(Path, "open", open_file):
            with self.assertRaises(OSError): Output(self.root/"broken-init", self.config, ("ZEC",), "test")
        self.assertTrue(opened)
        self.assertTrue(all(handle.closed for handle in opened))


if __name__ == "__main__": unittest.main()
