from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from research.hype_local_only.delayed_teacher import H, Pending, pivot_catalog, teacher_verdict
from research.hype_local_only.live_daemon import LocalRuntime
from research.hype_local_only.model import Candidate, STAGES
from research.hype_local_only.promotion import ForwardEvidence
from research.hype_local_only.reliability import (CheckpointStore, DedupWindow, DurableTailer,
    JsonlEvidence, WriterLock, event_identity)
from research.hype_quant.features import FeatureState

ORIGIN = 100 * H


class FixtureModel:
    """Deterministic model only for runtime failure-path integration tests."""
    def __init__(self):
        self.model_version_id = "fixture"
        self.feature_policy = "causal_m1_v1"
        self.labels = {(s, h): 0 for s in ("LOW", "HIGH") for h in STAGES}
        self.positive = dict(self.labels)
        self.thresholds = {(s, h): 0.5 for s in ("LOW", "HIGH") for h in STAGES}
        self.live_labels = 0
        self.last_signal = None
        self.h1_shadow = {}
        self.h1_labels = {"LOW": 0, "HIGH": 0}
        self.h1_positive = dict(self.h1_labels)
        self.history_meta = {"causal_reconstruction": True}
        self.inference_errors = 0

    def make_online_challenger(self):
        return copy.deepcopy(self)

    def predict(self, *_):
        return 0.9, True

    def learn(self, side, stage, x, y, source="live", repeat=1):
        assert repeat == 1
        self.labels[(side, stage)] += 1
        self.positive[(side, stage)] += bool(y)
        self.live_labels += 1

    def h1_prior(self, _):
        return 0.5

    def relationship_evidence(self, *_):
        return {"supports": [], "contradicts": [], "pairs": []}

    def report(self):
        return {"fixture": True}


def teacher_state(ambiguous=False, late=False):
    state = FeatureState()
    for i in range(15):
        start = ORIGIN + i * H
        high, low = (120.0, 70.0 if ambiguous else 91.0) if i == 6 else ((99.0, 70.0) if i == 12 else (100.0, 90.0))
        state.candles["60"][start] = {
            "start_ms": start, "open": 95.0, "close": 95.0,
            "high": high, "low": low, "confirm": True,
            "received_ts_ms": ORIGIN + 25 * H if late and i == 0 else start + H,
            "source_timestamp_ms": start + H,
        }
        if i == 6 and not ambiguous:
            state.candles["60"][start]["open"] = 96.0
    return state


def pending(candidate="H-fixture", price=120, index=6, side="HIGH", stage=300):
    extreme = ORIGIN + index * H + 1000
    return Pending(candidate, side, stage, price, extreme, {"fixture": 1.0},
                   ORIGIN + (index + 3) * H, prediction_ts_ms=extreme + stage * 1000,
                   event_key=f"{side}:{ORIGIN+index*H}", champion_probability=.6,
                   challenger_probability=.8, challenger_id="candidate",
                   evidence={"price_reference": "PUBLIC_TRADE"})


def test_teacher_waits_for_opposite_pivot_and_exact_price():
    state = teacher_state()
    assert teacher_verdict(state, pending(), ORIGIN + 9 * H) is None
    assert teacher_verdict(state, pending(), ORIGIN + 15 * H)["label"] is True
    assert teacher_verdict(state, pending(price=119), ORIGIN + 15 * H)["label"] is False
    assert teacher_verdict(state, pending(index=12, side="LOW", price=70), ORIGIN + 15 * H) is None


def test_teacher_censors_ambiguous_hour_and_does_not_fill_h1_gaps():
    state = teacher_state(ambiguous=True)
    assert teacher_verdict(state, pending(), ORIGIN + 15 * H)["label"] is None
    state = teacher_state()
    state.candles["60"].pop(ORIGIN + H)
    assert teacher_verdict(state, pending(), ORIGIN + 15 * H) is None


def test_teacher_delayed_old_bar_cannot_backdate_finalization():
    state = teacher_state(late=True)
    assert teacher_verdict(state, pending(), ORIGIN + 15 * H) is None
    result = teacher_verdict(state, pending(), ORIGIN + 25 * H)
    assert result["label"] is True
    assert result["label_available_ms"] == ORIGIN + 25 * H


def test_teacher_rejects_nonfinal_or_missing_provenance_bars():
    state = teacher_state()
    state.candles["60"][ORIGIN]["confirm"] = False
    assert teacher_verdict(state, pending(), ORIGIN + 15 * H) is None
    state.candles["60"][ORIGIN]["confirm"] = True
    state.candles["60"][ORIGIN].pop("received_ts_ms")
    assert teacher_verdict(state, pending(), ORIGIN + 15 * H) is None


def test_generation_checksum_fallback_and_explicit_rollback(tmp_path):
    store = CheckpointStore(tmp_path)
    one = store.save({"schema": 1, "runtime": {"last_seen": 1}, "model": [1]})
    two = store.save({"schema": 1, "runtime": {"last_seen": 2}, "model": [2]})
    payload = tmp_path / "runtime_generations" / two / "bundle.pkl"
    payload.write_bytes(payload.read_bytes()[:-5] + b"broken")
    restored = CheckpointStore(tmp_path)
    assert restored.load()["model"] == [1]
    assert restored.recovery["rejected"][0]["generation"] == two
    restored.rollback(one)
    assert json.loads((tmp_path / "RUNTIME_CURRENT.json").read_text())["current"] == one
    with pytest.raises(ValueError):
        restored.rollback("../escape")


def test_corrupt_only_checkpoint_fails_closed(tmp_path):
    store = CheckpointStore(tmp_path)
    name = store.save({"schema": 1, "runtime": {}})
    (tmp_path / "runtime_generations" / name / "manifest.json").write_text("{}")
    with pytest.raises(RuntimeError, match="no intact"):
        CheckpointStore(tmp_path).load()


def test_single_writer_exclusion(tmp_path):
    with WriterLock(tmp_path / "lock"):
        with pytest.raises(RuntimeError, match="another writer"):
            with WriterLock(tmp_path / "lock"):
                pass
    with WriterLock(tmp_path / "lock"):
        pass


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_tailer_bounded_merge_restart_partial_lines_and_rotation(tmp_path):
    a = tmp_path / "HYPE_live_raw_frames.jsonl"
    b = tmp_path / "HYPE_live_microstructure_1s.jsonl"
    write_rows(a, [{"received_ts_ms": 10, "raw_text": "x" * 140}, {"received_ts_ms": 30}])
    write_rows(b, [{"ts_ms": 20}, {"ts_ms": 40}])
    tail = DurableTailer()
    assert [row[0] for row in tail.read_events(tmp_path, 2)] == [10, 20]
    restored = DurableTailer(copy.deepcopy(tail.offsets))
    assert [row[0] for row in restored.read_events(tmp_path, 2)] == [30, 40]
    with b.open("a") as stream:
        stream.write('{"ts_ms":50')
    assert restored.read_events(tmp_path, 2) == []
    with b.open("a") as stream:
        stream.write("}\n")
    assert [row[0] for row in restored.read_events(tmp_path)] == [50]
    write_rows(a, [{"received_ts_ms": 60, "raw_text": "z" * 140}])
    assert [row[0] for row in restored.read_events(tmp_path)] == [60]
    assert restored.notices[0]["event"] == "SOURCE_ROTATED"


def test_raw_reconnect_replays_deduplicate_without_path_or_receipt():
    raw = json.dumps({"topic": "publicTrade.HYPEUSDT", "ts": 4, "data": [{"i": "trade1"}]})
    a = {"raw_text": raw, "received_ts_ms": 5, "_source_path": "a"}
    b = {"raw_text": raw, "received_ts_ms": 8, "_source_path": "b"}
    dedup = DedupWindow()
    assert not dedup.seen(event_identity("raw", a))
    assert dedup.seen(event_identity("raw", b))


def test_evidence_replay_is_idempotent_and_repairs_partial_tail(tmp_path):
    path = tmp_path / "evidence.jsonl"
    evidence = JsonlEvidence(path)
    assert evidence.append({"event_id": "a", "label": True})
    with path.open("ab") as stream:
        stream.write(b'{"event_id":"bad')
    evidence = JsonlEvidence(path)
    assert not evidence.append({"event_id": "a", "label": True})
    assert evidence.append({"event_id": "b", "label": False})
    assert [json.loads(line)["event_id"] for line in path.read_text().splitlines()] == ["a", "b"]


def test_crash_after_learning_before_commit_replays_exactly_once(tmp_path):
    runtime = LocalRuntime(tmp_path, FixtureModel(), teacher_state())
    runtime.rt["pending"] = [pending()]
    runtime.checkpoint()
    runtime.settle(ORIGIN + 15 * H)
    assert runtime.learner.live_labels == 1
    # Simulated process crash: logs persisted, but bundle has not committed.
    restored = LocalRuntime(tmp_path)
    assert restored.learner.live_labels == 0
    assert len(restored.rt["pending"]) == 1
    restored.settle(ORIGIN + 15 * H)
    restored.checkpoint()
    again = LocalRuntime(tmp_path)
    again.settle(ORIGIN + 16 * H)
    assert again.learner.live_labels == 1
    assert again.learner.positive[("HIGH", 300)] == 1
    assert again.champion.live_labels == 0  # Champion never trained in place.
    assert len((tmp_path / "LOCAL_LIVE_LABELS.jsonl").read_text().splitlines()) == 1


def test_same_genuine_extreme_deduplicates_without_false_training(tmp_path):
    runtime = LocalRuntime(tmp_path, FixtureModel(), teacher_state())
    runtime.rt["pending"] = [pending("one"), pending("two")]
    runtime.settle(ORIGIN + 15 * H)
    assert runtime.learner.live_labels == 1
    assert runtime.learner.positive[("HIGH", 300)] == 1
    labels = [json.loads(line) for line in (tmp_path / "LOCAL_LIVE_LABELS.jsonl").read_text().splitlines()]
    assert labels[1]["label"] is None
    assert labels[1]["teacher_label"] is True
    assert labels[1]["reason"] == "DUPLICATE_EXTREME_STAGE"


def test_causal_signal_does_not_flip_confirmed_expected_side(tmp_path):
    runtime = LocalRuntime(tmp_path, FixtureModel(), FeatureState())
    runtime.rt["expected_side"] = "LOW"
    extreme = ORIGIN + 1000
    runtime.rt["candidates"]["LOW"] = Candidate("LOW", 90.0, extreme, "fixture-low", evidence={"windows": ["6h"], "price_reference": "PUBLIC_TRADE"})
    runtime._start_forward(extreme)
    runtime._predict_stages(extreme + 60_000, 91.0, {})
    runtime._predict_stages(extreme + 180_000, 91.0, {})
    runtime._predict_stages(extreme + 300_000, 91.0, {})
    assert runtime.champion.last_signal["stage"] == 300
    assert runtime.rt["expected_side"] == "LOW"


def test_late_stage_is_censored_instead_of_labelled_as_early(tmp_path):
    runtime = LocalRuntime(tmp_path, FixtureModel(), FeatureState())
    runtime.rt["candidates"]["LOW"] = Candidate("LOW", 90, ORIGIN, "fixture", evidence={"windows": ["6h"], "price_reference": "PUBLIC_TRADE"})
    runtime._start_forward(ORIGIN)
    runtime._predict_stages(ORIGIN + 10 * 60_000, 91, {})
    assert runtime.rt["pending"] == []
    assert runtime.champion.last_signal is None


def test_promotion_cannot_choose_best_event_after_labels_or_skip_embargo():
    gate = ForwardEvidence("candidate", ORIGIN, minimum_groups=2, maximum_groups=2, minimum_positives_per_side=1)
    item = pending(index=6)
    assert not gate.register(item)  # Nine-hour embargo.
    item = pending(index=10)
    assert gate.register(item)
    other = copy.deepcopy(item)
    other.candidate_id = "later_better"
    assert not gate.register(other)
    assert not gate.observe(other, True)
    assert gate.observe(item, False)
    assert gate.decision()["promote"] is False
    assert gate.decision()["reason"] == "COLLECTING_FIXED_FORWARD_COHORT"


def test_forward_promotion_requires_preselected_frozen_independent_evidence():
    gate = ForwardEvidence("candidate", ORIGIN, minimum_groups=32, maximum_groups=32, minimum_positives_per_side=8)
    items = []
    for i in range(32):
        for side in ("LOW", "HIGH"):
            item = pending(candidate=f"{side}{i}", index=10 + i * 9, side=side)
            item.champion_probability = .5
            item.challenger_probability = .9 if i % 2 else .1
            assert gate.register(item)
            items.append((item, bool(i % 2)))
    assert gate.decision()["reason"] == "WAITING_COHORT_LABEL_MATURITY"
    for item, label in items:
        assert gate.observe(item, label)
    result = gate.decision()
    assert result["promote"] is True
    assert result["independent_time_blocks"] == 32
    assert result["event_count"] == 64


def test_status_contract_preserves_original_keys(tmp_path):
    runtime = LocalRuntime(tmp_path, FixtureModel(), FeatureState())
    runtime._status(ORIGIN)
    original_path = Path(__file__).resolve().parents[4] / "artifacts/latest_checkpoint/LOCAL_ONLY_STATUS.json"
    original = json.loads(original_path.read_text())
    assert original.keys() <= runtime.status.keys()
    runtime.rt["candidates"]["LOW"] = Candidate("LOW", 90, ORIGIN, "candidate")
    runtime._status(ORIGIN + 1000)
    assert original["candidate"].keys() <= runtime.status["candidate"].keys()
    assert runtime.status["real_orders"] is False
    assert runtime.status["research_only"] is True


def test_mid_quote_proxy_cannot_become_a_negative_trade_label(tmp_path):
    runtime = LocalRuntime(tmp_path, FixtureModel(), teacher_state())
    item = pending()
    item.evidence = {"price_reference": "MID_QUOTE_PROXY"}
    runtime.rt["pending"] = [item]
    runtime.settle(ORIGIN + 15 * H)
    assert runtime.learner.live_labels == 0
    row = json.loads((tmp_path / "LOCAL_LIVE_LABELS.jsonl").read_text())
    assert row["label"] is None
    assert row["teacher_label"] is True
    assert row["reason"] == "UNVERIFIED_TRADE_EXTREME_REFERENCE"


def test_trade_spike_between_samples_is_the_candidate_price(tmp_path):
    state = FeatureState()
    runtime = LocalRuntime(tmp_path, FixtureModel(), state)
    state.structural = {"ts_ms": ORIGIN, "received_ts_ms": ORIGIN,
                        "rolling_6h_low": 99.0, "rolling_6h_high": 101.0}
    state.update_event({"kind":"trade", "received_ts_ms":ORIGIN+1000,
                        "exchange_ts_ms":ORIGIN+900, "price":98, "qty":1, "side":"Sell"})
    runtime._propose(ORIGIN+5000, 100, {})
    candidate = runtime.rt["candidates"]["LOW"]
    assert candidate.extreme_price == 98
    assert candidate.extreme_ts_ms == ORIGIN+900
    assert candidate.evidence["price_reference"] == "PUBLIC_TRADE"
    assert "6h" in candidate.evidence["windows"]
