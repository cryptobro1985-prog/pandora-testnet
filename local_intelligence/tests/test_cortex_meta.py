import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from research.hype_local_only.cortex_meta import (
    HOUR_MS, VERSION, ResearchConfig, StatisticalCortex, causal_feature,
    discover, evidence, load_memory, matches, save_memory, validate_forward_proposals,
)
from research.hype_local_only.cortex_daemon import BackgroundProvider, acquire_owner, json_object, persist_proposals


def row(hour, label, value, candidate=None, stage=60):
    stamp = hour * HOUR_MS
    return {"side": "LOW", "delay_s": stage, "candidate_ts_ms": stamp,
            "snapshot_ts_ms": stamp + stage * 1000,
            "label_mature_ms": stamp + 3 * HOUR_MS,
            "candidate_id": candidate or str(hour), "strict_true": label,
            "features": {"flow": value, "future_label": int(label), "f083": int(label)}}


class MetaTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def test_targets_are_not_features(self):
        for name in ("future_return", "strict_true", "teacher_price", "f081", "f083", "point_110", "target_probability"):
            self.assertFalse(causal_feature(name))
        self.assertTrue(causal_feature("flow_60s"))
        self.assertTrue(causal_feature("f111"))

    def test_missing_is_unknown(self):
        condition = [{"feature": "flow", "op": "ge", "threshold": 0}]
        self.assertIsNone(matches(condition, {}))
        self.assertTrue(matches(condition, {"flow": 0}))

    def test_hourly_event_count_ignores_candidate_multiplicity(self):
        conditions = [{"feature": "flow", "op": "ge", "threshold": 0}]
        rows = [row(1, True, 1, str(i)) for i in range(50)] + [row(2, False, -1)]
        result = evidence(rows, conditions)
        self.assertEqual(result["rows"], 51)
        self.assertEqual(result["events"], 2)
        self.assertEqual(result["selected_positive_events"], 1)
        self.assertEqual(result["other_events"], 1)

    def test_purge_and_embargo_and_reserved_oos(self):
        config = ResearchConfig(train_end_ms=100 * HOUR_MS, oos_start_ms=200 * HOUR_MS)
        rows = [row(90, True, 2), row(98, False, 1), row(101, False, 0),
                row(110, False, -1), row(198, True, 2), row(205, True, 5)]
        result = discover(rows, config, "test")
        self.assertEqual(result["splits"]["train_rows"], 1)
        self.assertEqual(result["splits"]["validation_rows"], 1)
        self.assertEqual(result["splits"]["purged_or_embargoed_rows"], 3)
        self.assertEqual(result["splits"]["oos_reserved_rows"], 1)

    def test_oos_features_and_labels_never_change_hypotheses(self):
        rows = [row(h, h % 4 == 0, 2 if h % 4 == 0 else -1) for h in range(1, 90)]
        rows += [row(h, h % 4 == 0, 2 if h % 4 == 0 else -1) for h in range(110, 190)]
        rows += [row(210, True, 1)]
        config = ResearchConfig(100 * HOUR_MS, 200 * HOUR_MS)
        baseline = discover(rows, config, "unchanged")
        changed = copy.deepcopy(rows)
        changed[-1]["features"] = {"unseen_future_feature": 1e300}
        changed[-1]["strict_true"] = False
        second = discover(changed, config, "unchanged")
        self.assertEqual(baseline, second)
        self.assertTrue(baseline["hypotheses"])
        self.assertFalse(any(h["production_eligible"] for h in baseline["hypotheses"]))
        self.assertTrue(all(c["feature"] == "flow" for h in baseline["hypotheses"] for c in h["conditions"]))

    def test_research_preserves_rejection_and_never_promotes(self):
        rows = [row(h, h % 4 == 0, 2 if h % 4 == 0 else -1) for h in range(1, 90)]
        rows += [row(h, h % 4 == 0, -2 if h % 4 == 0 else 1) for h in range(110, 190)]
        result = discover(rows, ResearchConfig(100 * HOUR_MS, 200 * HOUR_MS), "test")
        self.assertTrue(result["hypotheses"])
        self.assertTrue(all(h["status"] in ("REJECTED_VALIDATION", "INSUFFICIENT_EVIDENCE") for h in result["hypotheses"]))
        self.assertIsNone(result["method"]["additive_quantum_value"])

    def test_checksum_tamper_detected(self):
        path = self.path / "memory.json"
        save_memory(path, {"version": VERSION, "observations": []})
        self.assertEqual(load_memory(path)["version"], VERSION)
        stored = json.loads(path.read_text())
        stored["payload"]["observations"] = ["altered"]
        path.write_text(json.dumps(stored))
        with self.assertRaisesRegex(ValueError, "checksum"):
            load_memory(path)

    def test_stale_status_abstains_and_does_not_record(self):
        analyst = StatisticalCortex(self.path / "state.json")
        result = analyst.analyze({"updated_ts_ms": 1000, "candidate": {"side": "HIGH"}}, 100_000)
        self.assertFalse(result["fresh_status"])
        self.assertEqual(result["decision"]["verdict"], "WAIT")
        self.assertEqual(result["observations_retained"], 0)

    def test_repeated_polls_do_not_create_independent_evidence(self):
        analyst = StatisticalCortex(self.path / "state.json")
        status = {"updated_ts_ms": 1000, "candidate": {"side": "LOW", "candidate_id": "x", "probabilities": {"60": .4}},
                  "cortex_evidence": {"candidate_id": "x", "side": "LOW", "prediction_ts_ms": 900, "features": {"flow": .1}}}
        analyst.analyze(status, 1000)
        status["updated_ts_ms"] = 2000
        result = analyst.analyze(status, 2000)
        self.assertEqual(result["observations_retained"], 1)
        restarted = StatisticalCortex(self.path / "state.json")
        self.assertEqual(len(restarted.history), 1)
        self.assertFalse(result["model_or_threshold_changes"])

    def test_buffer_is_bounded(self):
        analyst = StatisticalCortex(self.path / "state.json")
        for i in range(270):
            analyst.analyze({"updated_ts_ms": 1000 + i,
                             "candidate": {"side": "LOW", "candidate_id": str(i)}}, 1000 + i)
        self.assertEqual(len(analyst.history), 256)

    def test_mismatched_evidence_and_future_timestamp_are_not_current(self):
        analyst = StatisticalCortex(self.path / "state.json")
        status = {"updated_ts_ms": 1000, "candidate": {"side": "LOW", "candidate_id": "current"},
                  "cortex_evidence": {"candidate_id": "old", "side": "LOW", "prediction_ts_ms": 900,
                                      "features": {"flow": .1}}}
        self.assertFalse(analyst.analyze(status, 1000)["fresh_features"])
        status["cortex_evidence"].update({"candidate_id": "current", "prediction_ts_ms": 1001})
        self.assertFalse(analyst.analyze(status, 1000)["fresh_features"])

    def test_proposals_remain_unvalidated_and_deduplicated(self):
        proposal = {"feature": "flow", "op": "ge", "threshold": 1, "side": "LOW", "stage_s": 60, "rationale": "test"}
        path = self.path / "proposals.json"
        persist_proposals(path, [proposal, proposal], 1, "mock")
        persist_proposals(path, [proposal], 2, "mock")
        saved = load_memory(path)["hypotheses"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["status"], "PENDING_OFFLINE_VALIDATION")
        self.assertFalse(saved[0]["production_eligible"])

    def test_worker_returns_immediately_and_prevents_parallel_calls(self):
        gate = threading.Event()
        class SlowProvider:
            def generate(self, payload):
                gate.wait(2)
                return {"verdict": "WAIT"}
        worker = BackgroundProvider(SlowProvider())
        start = time.monotonic()
        try:
            self.assertTrue(worker.submit({"candidate": {"candidate_id": "x"}}, 1))
            self.assertLess(time.monotonic() - start, .2)
            self.assertFalse(worker.submit({}, 2))
            self.assertIsNone(worker.poll())
        finally:
            gate.set()
            worker.worker.join(2)
        self.assertEqual(worker.poll()["candidate_id"], "x")

    def test_partial_json_is_not_recovered(self):
        with self.assertRaises(ValueError):
            json_object('reasoning {"verdict":"WAIT"}')

    def test_single_writer_lock_releases_on_close(self):
        owner = acquire_owner(self.path)
        try:
            with self.assertRaisesRegex(RuntimeError, "already_running"):
                acquire_owner(self.path)
        finally:
            owner.close()
        acquire_owner(self.path).close()

    def test_live_proposal_cannot_borrow_older_historical_labels(self):
        rows = [row(h, True, 2) for h in range(1, 90)]
        proposal = {"id": "x", "proposed_ts_ms": 100 * HOUR_MS,
                    "proposal": {"feature": "flow", "op": "ge", "threshold": 0, "side": "LOW", "stage_s": 60}}
        result = validate_forward_proposals(rows, [proposal], 200 * HOUR_MS)[0]
        self.assertEqual(result["evidence"]["events"], 0)
        self.assertEqual(result["status"], "PENDING_FORWARD_EVIDENCE")
        self.assertFalse(result["production_eligible"])

    def test_forward_validation_respects_history_boundary_and_maturity(self):
        proposal = {"id": "x", "proposed_ts_ms": 100 * HOUR_MS,
                    "proposal": {"feature": "flow", "op": "ge", "threshold": 0, "side": "LOW", "stage_s": 60}}
        result = validate_forward_proposals([row(105, True, 2), row(199, True, 2)], [proposal],
                                            200 * HOUR_MS, minimum_ts_ms=110 * HOUR_MS)[0]
        self.assertEqual(result["evidence"]["events"], 0)


if __name__ == "__main__":
    unittest.main()
