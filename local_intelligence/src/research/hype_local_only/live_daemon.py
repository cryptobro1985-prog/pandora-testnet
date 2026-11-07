#!/usr/bin/env python3
"""Causal inference with coherent recovery and frozen forward evaluation.

No private exchange endpoints or orders. External publication is opt-in and
replay is local. Existing monitor producer fields remain backward compatible.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import pickle
import signal
import time
import uuid
from pathlib import Path

import requests

from research.hype_quant.features import FeatureState
from .delayed_teacher import H, Pending, completed_h1, pivot_catalog, strict_label, strict_pivots, teacher_verdict
from .live_features import live_to_archive_features
from .model import Candidate, LocalOnlyModel, STAGES
from .promotion import ForwardEvidence
from .reliability import (CheckpointStore, DedupWindow, DurableTailer, JsonlEvidence,
                          WriterLock, atomic_json, event_identity)
from .temporal import candidate_temporal_features


def load_pickle(path, default):
    if not path.exists():
        return default
    try:
        with path.open("rb") as stream:
            return pickle.load(stream)
    except Exception as exc:
        raise RuntimeError(f"unreadable legacy state {path}; restore a known checkpoint: {exc}") from exc


def _online_copy(model):
    return model.make_online_challenger() if hasattr(model, "make_online_challenger") else copy.deepcopy(model)


def _model_version(model):
    return str(getattr(model, "model_version_id", "legacy-unversioned"))


def _fitted_through(model):
    meta = getattr(model, "history_meta", {}) or {}
    return max(int(meta.get(name, 0) or 0) for name in (
        "training_cutoff_ms", "max_train_available_ms", "max_calibration_available_ms",
        "threshold_validated_until_ms"))


class LocalRuntime:
    """Testable engine. Caller holds WriterLock during all mutations."""

    def __init__(self, checkpoint_dir: Path, seed_model=None, seed_state=None):
        self.root = Path(checkpoint_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = CheckpointStore(self.root)
        self.events = JsonlEvidence(self.root / "LOCAL_EVENTS.jsonl")
        self.labels = JsonlEvidence(self.root / "LOCAL_LIVE_LABELS.jsonl")
        bundle = self.store.load()
        if bundle is None:
            model = seed_model if seed_model is not None else LocalOnlyModel.load(self.root / "local_only_model.pkl")
            state = seed_state if seed_state is not None else load_pickle(self.root / "feature_state.pkl", FeatureState())
            legacy = load_pickle(self.root / "local_runtime.pkl", {})
            self.champion, self.learner = model, _online_copy(model)
            self.challenger = copy.deepcopy(self.learner)
            self.previous_champion = None
            self.state = state
            self.rt = {
                "candidates": legacy.get("candidates") or {"LOW": None, "HIGH": None},
                "pending": legacy.get("pending", []), "expected_side": legacy.get("expected_side"),
                "last_teacher_local": legacy.get("last_teacher_local"),
                "last_seen": getattr(state, "last_ts_ms", None), "last_source_ts": None,
                "next_sample": 0, "learned_ids": set(), "positive_events": set(), "negative_events": set(),
                "unique_event_labels": set(), "dedup_ids": [], "tail_offsets": {},
                "censored_labels": 0, "rejected_inputs": 0, "duplicate_inputs": 0,
                "migration_cutoff_ms": max(int(getattr(state, "last_ts_ms", 0) or 0),
                                            int(getattr(state, "last_raw_received_ts", 0) or 0)),
                "last_proposal_trade_received_ms": None,
            }
            self.forward = None
            self.status = {}
        else:
            self.champion, self.learner, self.challenger = bundle["champion"], bundle["learner"], bundle["challenger"]
            self.previous_champion = bundle.get("previous_champion")
            self.state, self.rt = bundle["feature_state"], bundle["runtime"]
            self.forward, self.status = bundle["forward_evidence"], bundle.get("status", {})
        self.rt["pending"] = [Pending(**item) if isinstance(item, dict) else item for item in self.rt["pending"]]
        self.rt.setdefault("negative_events", set())
        self.tail = DurableTailer(self.rt["tail_offsets"])
        self.dedup = DedupWindow(self.rt["dedup_ids"])
        if self.store.recovery:
            self.events.append({"event_id": f"recovery:{self.store.active_generation}",
                                "event": "CHECKPOINT_RECOVERED", **self.store.recovery})

    def _start_forward(self, ts):
        if self.forward is not None:
            return
        cutoff = max(int(ts), _fitted_through(self.challenger))
        identity = _model_version(self.challenger) + ":" + uuid.uuid4().hex[:12]
        self.forward = ForwardEvidence(identity, cutoff)
        self.events.append({"event_id": "challenger:" + identity, "event": "CHALLENGER_FROZEN",
                            "ts_ms": ts, "challenger_id": identity, "training_cutoff_ms": cutoff,
                            "champion_version": _model_version(self.champion),
                            "embargo_ms": self.forward.embargo_ms})

    def process(self, ts: int, kind: str, row: dict):
        if ts <= 0:
            self.rt["rejected_inputs"] += 1
            return
        if ts <= self.rt.get("migration_cutoff_ms", 0):
            return
        if self.dedup.seen(event_identity(kind, row)):
            self.rt["duplicate_inputs"] += 1
            return
        if self.rt["last_seen"] is not None and ts < self.rt["last_seen"]:
            self.rt["rejected_inputs"] += 1
            return
        if kind == "raw":
            self.state.update_raw_frame(row)
            return
        if kind == "market":
            self.state.update_market_context(row)
            return
        if kind == "struct":
            self.state.update_structural_context(row)
            return
        source_ts = int(row.get("ts_ms") or ts)
        if self.rt.get("last_source_ts") is not None and source_ts <= self.rt["last_source_ts"]:
            self.rt["rejected_inputs"] += 1
            return
        previous = self.rt["last_seen"]
        self.rt["last_seen"], self.rt["last_source_ts"] = ts, source_ts
        try:
            price, features = self.state.update_micro(row, as_of_ms=ts)
        except (ValueError, TypeError, KeyError) as exc:
            self.rt["rejected_inputs"] += 1
            self.events.append({"event_id": f"input-error:{ts}", "event": "INPUT_REJECTED",
                                "ts_ms": ts, "reason": str(exc)})
            return
        if previous is not None and ts - previous > 15_000:
            self.events.append({"event_id": f"gap:{previous}:{ts}", "event": "INPUT_GAP",
                                "from_ts_ms": previous, "to_ts_ms": ts,
                                "action": "RESET_CANDIDATES_KEEP_PENDING_LABELS"})
            self.rt["candidates"] = {"LOW": None, "HIGH": None}
        if ts < self.rt["next_sample"]:
            return
        self.rt["next_sample"] = ts + 5000
        self._start_forward(ts)
        self._update_teacher(ts)
        self._propose(ts, price, features)
        self._predict_stages(ts, price, features)
        self.settle(ts)
        self._status(ts)

    def _update_teacher(self, ts, catalog=None):
        pivots = (catalog or pivot_catalog(self.state, ts))[2]
        if not pivots:
            return
        latest = pivots[-1]
        previous = self.rt["last_teacher_local"]
        if previous is None or latest["hour_ms"] >= int(previous.get("hour_ms", 0)):
            self.rt["last_teacher_local"] = latest
            # A model signal cannot change the confirmed structural leg.
            self.rt["expected_side"] = "LOW" if latest["side"] == "HIGH" else "HIGH"

    def _propose(self, ts, price, features):
        since = self.rt.get("last_proposal_trade_received_ms")
        since = ts - 5000 if since is None else since
        extrema = (self.state.causal_trade_extrema(since, ts)
                   if hasattr(self.state, "causal_trade_extrema") else {})
        self.rt["last_proposal_trade_received_ms"] = ts
        structural = getattr(self.state, "structural", {}) or {}
        stamp = int(structural.get("ts_ms") or structural.get("received_ts_ms") or 0)
        received = int(structural.get("received_ts_ms") or stamp)
        if stamp <= 0 or stamp > ts or received > ts or ts - stamp > 180_000:
            structural = {}
        levels = {
            "LOW": [("5m", features.get("running_low_300s")), ("15m", features.get("running_low_900s")),
                    ("60m", structural.get("rolling_60m_low")), ("6h", structural.get("rolling_6h_low"))],
            "HIGH": [("5m", features.get("running_high_300s")), ("15m", features.get("running_high_900s")),
                     ("60m", structural.get("rolling_60m_high")), ("6h", structural.get("rolling_6h_high"))],
        }
        for side in ("LOW", "HIGH"):
            observed = extrema.get("low" if side == "LOW" else "high")
            proposal_price = float(observed["price"]) if observed else float(price)
            extreme_ts = int(observed["source_ts_ms"]) if observed else int(ts)
            observed_ts = int(observed["received_ts_ms"]) if observed else int(ts)
            price_reference = "PUBLIC_TRADE" if observed else "MID_QUOTE_PROXY"
            valid = [(name, float(value)) for name, value in levels[side]
                     if isinstance(value, (int, float)) and math.isfinite(value) and value > 0]
            hit = [(name, value) for name, value in valid
                   if (proposal_price <= value * (1 + 0.75 / 10000) if side == "LOW" else proposal_price >= value * (1 - 0.75 / 10000))]
            if not hit:
                continue
            old = self.rt["candidates"].get(side)
            extends = (old is None or (proposal_price < old.extreme_price if side == "LOW" else proposal_price > old.extreme_price)
                       or (price_reference == "PUBLIC_TRADE" and old.evidence.get("price_reference") != "PUBLIC_TRADE"))
            stale = old is not None and ts - old.extreme_ts_ms > H
            if not extends and not stale:
                continue
            evidence = {"proposal": "MULTIWINDOW_CAUSAL", "windows": [name for name, _ in hit], "accepted_stages": [],
                        "price_reference": price_reference, "extreme_source_ts_ms": extreme_ts,
                        "extreme_received_ts_ms": observed_ts, "proposal_observed_ts_ms": ts,
                        "trade_window_complete": bool(extrema.get("complete_window", False))}
            candidate = Candidate(side, proposal_price, extreme_ts, f"{side[0]}-{extreme_ts}-{observed_ts}", evidence=evidence)
            self.rt["candidates"][side] = candidate
            self.events.append({"event_id": "candidate:" + candidate.candidate_id,
                                "event": "NEW_CANDIDATE", "ts_ms": ts, "side": side,
                                "price": proposal_price, "extreme_ts_ms": extreme_ts,
                                "candidate_id": candidate.candidate_id, "evidence": evidence})

    def _predict_stages(self, ts, price, features):
        for side in ("LOW", "HIGH"):
            candidate = self.rt["candidates"].get(side)
            if candidate is None or candidate.invalidated:
                continue
            age = max(0.0, (ts - candidate.extreme_ts_ms) / 1000)
            for stage in STAGES:
                if age < stage or stage in candidate.stages_done:
                    continue
                candidate.stages_done.add(stage)
                if age > stage + 15:
                    self.events.append({"event_id": f"late-stage:{candidate.candidate_id}:{stage}",
                                        "event": "STAGE_CENSORED", "ts_ms": ts,
                                        "candidate_id": candidate.candidate_id, "stage": stage,
                                        "reason": "STAGE_CLOCK_MISSED", "age_s": age})
                    continue
                fx = live_to_archive_features(side, age, candidate.extreme_price, price, features, self.state)
                fx = candidate_temporal_features(fx, candidate.snapshots)
                before = int(getattr(self.champion, "inference_errors", 0))
                probability, accepted = self.champion.predict(side, stage, fx)
                shadow_probability, _ = self.challenger.predict(side, stage, fx)
                inference_ok = int(getattr(self.champion, "inference_errors", 0)) == before
                known_population = ("6h" in candidate.evidence.get("windows", [])
                                    and candidate.evidence.get("price_reference") == "PUBLIC_TRADE")
                causal_model = (getattr(self.champion, "feature_policy", "legacy") == "causal_m1_v1"
                                or bool((getattr(self.champion, "history_meta", {}) or {}).get("causal_reconstruction")))
                prediction_after_fit = ts > _fitted_through(self.champion)
                accepted = bool(accepted and inference_ok and known_population and causal_model and prediction_after_fit)
                if accepted:
                    candidate.evidence.setdefault("accepted_stages", []).append(stage)
                candidate.snapshots[stage], candidate.probabilities[stage] = fx, probability
                hour = candidate.extreme_ts_ms // H * H
                event_key = f"{side}:{hour}"
                pending = Pending(candidate.candidate_id, side, stage, candidate.extreme_price,
                                  candidate.extreme_ts_ms, fx, hour + 3 * H,
                                  prediction_ts_ms=ts, event_key=event_key,
                                  champion_probability=probability, challenger_probability=shadow_probability,
                                  champion_threshold=self.champion.thresholds[(side, stage)],
                                  challenger_threshold=self.challenger.thresholds[(side, stage)],
                                  challenger_id=self.forward.challenger_id,
                                  evidence={"windows": list(candidate.evidence.get("windows", [])),
                                            "known_training_population": known_population,
                                            "price_reference": candidate.evidence.get("price_reference", "UNKNOWN"),
                                            "extreme_received_ts_ms": candidate.evidence.get("extreme_received_ts_ms")})
                self.rt["pending"].append(pending)
                if known_population:
                    self.forward.register(pending)
                snapshot = getattr(self.state, "last_archive_feature_snapshot", None)
                self.events.append({"event_id": f"stage:{candidate.candidate_id}:{stage}",
                                    "event": "LOCAL_STAGE", "ts_ms": ts, "side": side, "stage": stage,
                                    "probability": probability, "threshold": pending.champion_threshold,
                                    "accepted": accepted, "h1_prior": self.champion.h1_prior(side),
                                    "expected_side": self.rt["expected_side"],
                                    "candidate_id": candidate.candidate_id, "event_key": event_key,
                                    "champion_version": _model_version(self.champion),
                                    "challenger_id": pending.challenger_id,
                                    "challenger_probability": shadow_probability,
                                    "known_training_population": known_population,
                                    "causal_model": causal_model, "prediction_after_fit": prediction_after_fit, "features": fx,
                                    "feature_evidence": snapshot.as_dict() if snapshot is not None else {},
                                    "relationship_evidence": self.champion.relationship_evidence(side, stage, fx)})
                if accepted and (self.rt["expected_side"] is None or side == self.rt["expected_side"]):
                    signal_state = "FORMING_LOCAL" if stage == 60 else "PROBABLE_LOCAL" if stage == 180 else "LOCAL_SIGNAL"
                    self.champion.last_signal = {
                        "side": side, "price": candidate.extreme_price, "candidate_id": candidate.candidate_id,
                        "detected_ts_ms": ts, "probability": probability,
                        "h1_prior": self.champion.h1_prior(side), "stage": stage, "state": signal_state}
                    self.events.append({"event_id": f"signal:{candidate.candidate_id}:{stage}",
                                        "event": signal_state, **self.champion.last_signal,
                                        "next_expected": self.rt["expected_side"]})

    def settle(self, ts):
        if not self.rt["pending"]:
            return
        catalog = pivot_catalog(self.state, ts)
        self._update_teacher(ts, catalog)
        keep = []
        for item in sorted(self.rt["pending"], key=lambda p: (p.extreme_ts_ms, p.stage, p.candidate_id)):
            if item.label_id in self.rt["learned_ids"]:
                continue
            verdict = teacher_verdict(self.state, item, ts, catalog)
            if verdict is None:
                keep.append(item)
                continue
            label = verdict["label"]
            teacher_label, teacher_reason = label, verdict["reason"]
            if item.evidence.get("price_reference") != "PUBLIC_TRADE":
                label = None
                verdict = {**verdict, "reason": "UNVERIFIED_TRADE_EXTREME_REFERENCE"}
            positive_key = f"{item.side}:{verdict['hour_ms']}:{item.stage}"
            if label and positive_key in self.rt["positive_events"]:
                label = None
                verdict = {**verdict, "reason": "DUPLICATE_EXTREME_STAGE"}
            elif label is False and positive_key in self.rt["negative_events"]:
                label = None
                verdict = {**verdict, "reason": "DUPLICATE_NEGATIVE_EVENT_STAGE"}
            if label is not None:
                self.learner.learn(item.side, item.stage, item.x, bool(label), source="live", repeat=1)
                self.rt["unique_event_labels"].add(item.event_key or f"{item.side}:{verdict['hour_ms']}")
                if label:
                    self.rt["positive_events"].add(positive_key)
                else:
                    self.rt["negative_events"].add(positive_key)
            else:
                self.rt["censored_labels"] += 1
            self.rt["learned_ids"].add(item.label_id)
            if self.forward is not None:
                # Evaluation uses the preselected prediction's genuine teacher
                # outcome even when correlated learning examples are skipped.
                self.forward.observe(item, teacher_label)
            self.labels.append({"event_id": item.label_id, "ts_ms": ts, "candidate_id": item.candidate_id,
                                "event_key": item.event_key, "side": item.side, "stage": item.stage,
                                "is_latest_extreme_in_hour": label is True,
                                "teacher": "H1_L6_K2_STRICT_FINALIZED",
                                "prediction_ts_ms": item.prediction_ts_ms,
                                "extreme_ts_ms": item.extreme_ts_ms,
                                "probability": item.champion_probability,
                                "challenger_probability": item.challenger_probability,
                                "challenger_id": item.challenger_id, **verdict, "label": label,
                                "teacher_label": teacher_label, "teacher_reason": teacher_reason,
                                "learning_applied": label is not None})
        self.rt["pending"] = keep
        self._consider_promotion(ts)

    def _consider_promotion(self, ts):
        if self.forward is None:
            return
        decision = self.forward.decision()
        if decision["reason"] in {"COLLECTING_FIXED_FORWARD_COHORT", "WAITING_COHORT_LABEL_MATURITY"}:
            return
        self.events.append({"event_id": "decision:" + self.forward.challenger_id,
                            "event": "CHALLENGER_PROMOTED" if decision["promote"] else "CHALLENGER_REJECTED",
                            "ts_ms": ts, **decision})
        if decision["promote"]:
            self.previous_champion = self.champion
            self.champion = copy.deepcopy(self.challenger)
            self.champion.history_meta = dict(self.champion.history_meta, role="forward_validated_champion",
                                             forward_evidence=decision, promoted_ts_ms=ts)
        self.challenger = copy.deepcopy(self.learner)
        self.challenger.model_version_id = uuid.uuid4().hex
        self.forward = None
        self._start_forward(ts)

    def _status(self, ts):
        expected = self.rt["expected_side"]
        candidate = self.rt["candidates"].get(expected) if expected else None
        if candidate is None:
            options = [item for item in self.rt["candidates"].values() if item is not None]
            candidate = max(options, key=lambda c: max(c.probabilities.values(), default=0), default=None)
        coverage = self.state.coverage_report()
        done = sorted(candidate.snapshots) if candidate else []
        stage = done[-1] if done else None
        accepted = candidate.evidence.get("accepted_stages", []) if candidate else []
        self.status = {
            "status": "LEARNING_LIVE" if self.learner.live_labels else "HISTORY_PRETRAINED_LIVE_WATCH",
            "updated_ts_ms": ts, "expected_side": expected, "last_teacher_local": self.rt["last_teacher_local"],
            "candidate": None if candidate is None else {
                "candidate_id": candidate.candidate_id, "side": candidate.side,
                "extreme_price": candidate.extreme_price, "age_s": round(max(0, (ts - candidate.extreme_ts_ms) / 1000), 1),
                "probabilities": {str(k): round(v, 6) for k, v in candidate.probabilities.items()},
                "thresholds": {str(k): self.champion.thresholds[(candidate.side, k)] for k in STAGES},
                "h1_prior": round(self.champion.h1_prior(candidate.side), 6),
                "evidence": candidate.evidence,
                "relationship_evidence": self.champion.relationship_evidence(candidate.side, stage, candidate.snapshots[stage])
                                         if stage is not None else {"supports": [], "contradicts": [], "pairs": []},
                "stage": "LOCAL_SIGNAL" if 300 in accepted else "PROBABLE" if 180 in accepted else "FORMING" if 60 in accepted else "WATCH"},
            "historical_labels": sum(self.champion.labels.values()) - self.champion.live_labels,
            "live_labels": self.learner.live_labels, "pending_labels": len(self.rt["pending"]),
            "model_report": self.champion.report(), "h1_baseline": self.champion.h1_shadow,
            "h1_training": {"labels": self.learner.h1_labels, "positive": self.learner.h1_positive},
            "seen_input_count": coverage.get("seen_input_count"), "feature_contract": coverage,
            "last_signal": self.champion.last_signal, "mode": "LOCAL_ONLY",
            "local_target": "FULL_HISTORY_STRICT_H1_L6_K2", "github_run_id": os.getenv("GITHUB_RUN_ID"),
            "github_sha": os.getenv("GITHUB_SHA"), "cortex_state": "RELATIONSHIP_MEMORY_READY", "cortex": {},
            "research_only": True, "real_orders": False,
            "cortex_evidence": {} if stage is None else {
                "prediction_ts_ms": candidate.extreme_ts_ms + int(candidate.snapshots[stage].get("age_s", stage) * 1000),
                "features": candidate.snapshots[stage], "candidate_id": candidate.candidate_id,
                "side": candidate.side, "stage": stage, "stage_s": stage,
                "event_key": f"{candidate.side}:{candidate.extreme_ts_ms // H * H}"},
            "reliability": {"checkpoint_generation": self.store.active_generation,
                            "recovery": self.store.recovery,
                            "learned_stage_count": len(self.rt["learned_ids"]),
                            "unique_event_labels": len(self.rt["unique_event_labels"]),
                            "censored_labels": self.rt["censored_labels"],
                            "rejected_inputs": self.rt["rejected_inputs"],
                            "duplicate_inputs": self.rt["duplicate_inputs"],
                            "champion_version": _model_version(self.champion),
                            "learner_version": _model_version(self.learner),
                            "forward_evidence": self.forward.decision() if self.forward else {},
                            "online_updates_apply_to": "learner_only_until_independent_forward_promotion"},
        }
        cortex_path = self.root / "CORTEX_LOCAL_ONLY_STATUS.json"
        if cortex_path.exists():
            try:
                self.status["cortex"] = json.loads(cortex_path.read_text(encoding="utf-8"))
                self.status["cortex_state"] = self.status["cortex"].get("state", "RELATIONSHIP_MEMORY_READY")
            except (ValueError, OSError):
                pass

    def checkpoint(self):
        self.rt["dedup_ids"] = list(self.dedup.keys)
        self.rt["tail_offsets"] = self.tail.offsets
        generation = self.store.save({
            "schema": CheckpointStore.SCHEMA, "champion": self.champion,
            "learner": self.learner, "challenger": self.challenger,
            "previous_champion": self.previous_champion,
            "feature_state": self.state, "runtime": self.rt,
            "forward_evidence": self.forward, "status": self.status,
        })
        if self.status:
            self.status["reliability"]["checkpoint_generation"] = generation
            atomic_json(self.root / "LOCAL_ONLY_STATUS.json", self.status)
        return generation


def publish_monitor(status):
    url=os.getenv("LOCAL_ONLY_MONITOR_URL","").strip()
    if not url:return
    payload=dict(status)
    payload["mode"]="LOCAL_ONLY"
    payload["local_target"]="FULL_HISTORY_STRICT_H1_L6_K2"
    payload["github_run_id"]=os.getenv("GITHUB_RUN_ID")
    payload["github_sha"]=os.getenv("GITHUB_SHA")
    payload["research_only"]=True
    payload["real_orders"]=False
    try:
        r=requests.post(url,
            headers={"X-Caterpillar-Research":"1","User-Agent":"pandora-hype-local-only/1.0"},
            json=payload,timeout=6)
        r.raise_for_status()
    except Exception:
        pass

def publish_issue(status):
    token=os.getenv("GITHUB_TOKEN")
    if not token:return
    repo=os.getenv("GITHUB_REPOSITORY","cryptobro1985-prog/pandora-testnet")
    c=status.get("candidate") or {};p=c.get("probabilities") or {}
    lines=[
        "# HYPE LOCAL-ONLY — LIVE",
        f"**Status:** {status.get('status')}  ",
        f"**Expected next Local:** {status.get('expected_side') or 'UNKNOWN'}  ",
        f"**Last teacher Local:** {status.get('last_teacher_local') or '—'}  ",
        f"**Candidate:** {c.get('side','—')} @ {c.get('extreme_price','—')} · age {c.get('age_s','—')}s  ",
        f"**P60/P180/P300:** {p.get('60','—')} / {p.get('180','—')} / {p.get('300','—')}  ",
        f"**Stage:** {c.get('stage','WAIT')}  ",
        f"**Historical labels:** {status.get('historical_labels')} · live matured {status.get('live_labels')} · pending {status.get('pending_labels')}  ",
        f"**Inputs seen:** {status.get('seen_input_count')}/86  ",
        f"**Cortex:** {status.get('cortex_state')}  ",
        "",
        "~~~json",json.dumps(status,separators=(",",":"),ensure_ascii=False),"~~~",
    ]
    try:
        r=requests.patch(f"https://api.github.com/repos/{repo}/issues/24",
            headers={"Authorization":f"Bearer {token}","Accept":"application/vnd.github+json"},
            json={"body":"\n".join(lines)},timeout=10)
        r.raise_for_status()
    except Exception:pass



def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--minutes", type=float, default=60)
    parser.add_argument("--replay", action="store_true", help="drain captures and exit; disables external publication")
    parser.add_argument("--max-events-per-poll", type=int, default=2000)
    parser.add_argument("--publish-existing-monitor", action="store_true")
    parser.add_argument("--publish-issue", action="store_true")
    parser.add_argument("--rollback-generation", help="verify/select existing complete generation, then exit")
    args = parser.parse_args(argv)
    if args.max_events_per_poll <= 0 or args.minutes < 0:
        parser.error("event limit must be positive and minutes nonnegative")
    with WriterLock(args.checkpoint_dir / ".local_writer.lock"):
        if args.rollback_generation:
            CheckpointStore(args.checkpoint_dir).rollback(args.rollback_generation)
            return
        runtime = LocalRuntime(args.checkpoint_dir)
        stop = False
        def stopfn(*_):
            nonlocal stop
            stop = True
        signal.signal(signal.SIGTERM, stopfn)
        signal.signal(signal.SIGINT, stopfn)
        deadline = time.monotonic() + args.minutes * 60
        next_save = next_monitor = next_issue = 0.0
        while not stop and (args.replay or time.monotonic() < deadline):
            events = runtime.tail.read_events(args.capture_root, args.max_events_per_poll)
            for ts, _, kind, row in events:
                runtime.process(ts, kind, row)
            for notice in runtime.tail.notices:
                runtime.events.append({"event_id": "source-notice:" + uuid.uuid4().hex, **notice})
            runtime.tail.notices.clear()
            now = time.monotonic()
            if events:
                runtime.settle(max(event[0] for event in events))
                if runtime.rt["last_seen"]:
                    runtime._status(runtime.rt["last_seen"])
            if now >= next_save:
                runtime.checkpoint()
                next_save = now + 30
            if not args.replay and args.publish_existing_monitor and now >= next_monitor and runtime.status:
                publish_monitor(runtime.status)
                next_monitor = now + 10
            if not args.replay and args.publish_issue and now >= next_issue and runtime.status:
                publish_issue(runtime.status)
                next_issue = now + 30
            if not events:
                if args.replay:
                    break
                time.sleep(0.5)
        runtime.checkpoint()
        print("LOCAL_ONLY=" + json.dumps(runtime.status, separators=(",", ":"), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
