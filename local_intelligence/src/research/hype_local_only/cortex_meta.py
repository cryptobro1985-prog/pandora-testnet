"""Bounded, numerical Cortex research. This module cannot modify Quantum.

Discovery and validation are separate chronological partitions. An hourly
side/stage is one evidence unit, regardless of the number of candidate rows.
Intervals describe validation associations; they are not causal evidence or
permission to promote a model. The final OOS partition is never scored here.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import tempfile
from typing import Any

HOUR_MS = 3_600_000
VERSION = "CORTEX-STATISTICAL-v1"
FORBIDDEN = ("future", "label", "target", "strict", "teacher", "confirmed", "evaluation")


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def causal_feature(name: str) -> bool:
    lower = str(name).lower()
    if any(word in lower for word in FORBIDDEN):
        return False
    match = re.fullmatch(r"(?:f|point|input|feature)?[_-]?0*(\d+)", lower)
    return not (match and 81 <= int(match.group(1)) <= 110)


def clean_features(features: Any) -> dict[str, float]:
    if not isinstance(features, dict):
        return {}
    return {str(k): float(v) for k, v in features.items()
            if causal_feature(str(k)) and finite(v)}


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def atomic_json(path: Path, value: Any) -> None:
    """Unique temporary file prevents concurrent tmp-name collisions."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save_memory(path: Path, payload: dict) -> None:
    atomic_json(path, {"sha256": hashlib.sha256(canonical(payload)).hexdigest(), "payload": payload})


def load_memory(path: Path) -> dict:
    envelope = json.loads(Path(path).read_text(encoding="utf-8"))
    payload = envelope["payload"]
    if hashlib.sha256(canonical(payload)).hexdigest() != envelope.get("sha256"):
        raise ValueError("cortex_memory_checksum_mismatch")
    if payload.get("version") != VERSION:
        raise ValueError("cortex_memory_version_mismatch")
    return payload


def wilson(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    if total <= 0:
        return None
    proportion = successes / total
    denom = 1.0 + z * z / total
    center = (proportion + z * z / (2 * total)) / denom
    radius = z * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total)) / denom
    return [max(0.0, center - radius), min(1.0, center + radius)]


def matches(conditions: list[dict], features: dict) -> bool | None:
    """Missing evidence stays unknown; it is never replaced by zero."""
    for condition in conditions:
        value = features.get(condition["feature"])
        if not finite(value):
            return None
    return all(features[c["feature"]] >= c["threshold"] if c["op"] == "ge"
               else features[c["feature"]] <= c["threshold"] for c in conditions)


def evidence(rows: list[dict], conditions: list[dict], z: float = 1.96) -> dict:
    # Event outcome is the existence of a strict teacher local in this hour.
    # Any matching snapshot can flag the event, but contributes only one count.
    groups: dict[tuple, dict] = {}
    for row in rows:
        key = (str(row["side"]), int(row["candidate_ts_ms"]) // HOUR_MS)
        unit = groups.setdefault(key, {"y": False, "known": False, "selected": False})
        unit["y"] |= bool(row["strict_true"])
        match = matches(conditions, row["features"])
        unit["known"] |= match is not None
        unit["selected"] |= match is True
    selected = [u for u in groups.values() if u["known"] and u["selected"]]
    other = [u for u in groups.values() if u["known"] and not u["selected"]]
    positive = sum(u["y"] for u in selected)
    negative_group_positive = sum(u["y"] for u in other)
    return {
        "unit": "side_hour_event_at_fixed_stage",
        "rows": len(rows), "events": len(groups),
        "available_events": len(selected) + len(other),
        "missing_events": sum(not u["known"] for u in groups.values()),
        "selected_events": len(selected), "selected_positive_events": positive,
        "other_events": len(other), "other_positive_events": negative_group_positive,
        "selected_rate": positive / len(selected) if selected else None,
        "other_rate": negative_group_positive / len(other) if other else None,
        "selected_interval": wilson(positive, len(selected), z),
        "other_interval": wilson(negative_group_positive, len(other), z),
    }


@dataclass(frozen=True)
class ResearchConfig:
    train_end_ms: int
    oos_start_ms: int
    embargo_ms: int = 3 * HOUR_MS
    max_features: int = 8
    max_per_head: int = 12
    min_events: int = 8


def discover(rows: list[dict], config: ResearchConfig, source_sha256: str) -> dict:
    """No OOS features or labels are inspected by the discovery/validation loop."""
    if not config.train_end_ms < config.oos_start_ms or config.embargo_ms < 0:
        raise ValueError("invalid_chronological_split")
    if not 1 <= config.max_features <= 16 or not 1 <= config.max_per_head <= 32:
        raise ValueError("research_budget_exceeded")
    train, valid = [], []
    excluded = {"oos_reserved_rows": 0, "purged_or_embargoed_rows": 0, "invalid_rows": 0}
    for raw in rows:
        # Branch before reading features/labels from the sealed final partition.
        stamp = int(raw.get("snapshot_ts_ms", raw.get("candidate_ts_ms", 0)))
        if stamp >= config.oos_start_ms:
            excluded["oos_reserved_rows"] += 1
            continue
        if raw.get("side") not in ("LOW", "HIGH") or int(raw.get("delay_s", -1)) not in (60, 180, 300):
            excluded["invalid_rows"] += 1
            continue
        if not isinstance(raw.get("strict_true"), bool) or "label_mature_ms" not in raw:
            excluded["invalid_rows"] += 1
            continue
        matured = int(raw["label_mature_ms"])
        if matured < stamp or stamp < int(raw["candidate_ts_ms"]) + int(raw["delay_s"]) * 1000:
            excluded["invalid_rows"] += 1
            continue
        if stamp < config.train_end_ms and matured < config.train_end_ms:
            destination = train
        elif (stamp >= config.train_end_ms + config.embargo_ms
              and matured < config.oos_start_ms):
            destination = valid
        else:
            excluded["purged_or_embargoed_rows"] += 1
            continue
        row = dict(raw)
        row["features"] = clean_features(raw.get("features"))
        destination.append(row)

    candidates = []
    for side in ("LOW", "HIGH"):
        for stage in (60, 180, 300):
            training = [r for r in train if r["side"] == side and int(r["delay_s"]) == stage]
            # Exactly one row per candidate/stage, chosen by earliest timestamp.
            unique = {}
            for row in sorted(training, key=lambda r: int(r["snapshot_ts_ms"])):
                unique.setdefault(str(row.get("candidate_id", row["candidate_ts_ms"])), row)
            training = list(unique.values())
            effects = []
            names = sorted({k for r in training for k in r["features"]})
            for name in names:
                pos = [r["features"][name] for r in training if r["strict_true"] and name in r["features"]]
                neg = [r["features"][name] for r in training if not r["strict_true"] and name in r["features"]]
                if len(pos) < 3 or len(neg) < 3:
                    continue
                values = pos + neg
                median = statistics.median(values)
                mad = statistics.median(abs(v - median) for v in values)
                effect = (statistics.median(pos) - statistics.median(neg)) / max(mad * 1.4826, 1e-9)
                if not math.isfinite(effect) or abs(effect) < .05:
                    continue
                condition = {"feature": name, "op": "ge" if effect > 0 else "le", "threshold": median}
                effects.append((abs(effect), condition))
            effects.sort(key=lambda e: (-e[0], e[1]["feature"]))
            singles = [condition for _, condition in effects[:config.max_features]]
            conditions = [[condition] for condition in singles]
            conditions += [[a, b] for i, a in enumerate(singles[:4]) for b in singles[i + 1:4]]
            for condition in conditions[:config.max_per_head]:
                identity = {"side": side, "stage_s": stage, "conditions": condition}
                candidates.append({"id": hashlib.sha256(canonical(identity)).hexdigest()[:20],
                                   **identity, "discovery": evidence(training, condition)})

    # Simultaneous Wilson intervals with Bonferroni alpha allocation across both
    # intervals of every candidate; remaining serial dependence is disclosed.
    tests = len(candidates)
    z = statistics.NormalDist().inv_cdf(1 - .05 / (4 * max(1, tests)))
    for hypothesis in candidates:
        validation = [r for r in valid if r["side"] == hypothesis["side"]
                      and int(r["delay_s"]) == hypothesis["stage_s"]]
        measured = evidence(validation, hypothesis["conditions"], z)
        enough = (measured["selected_events"] >= config.min_events
                  and measured["other_events"] >= config.min_events
                  and measured["selected_positive_events"] >= 3)
        intervals = measured["selected_interval"], measured["other_interval"]
        if not enough:
            state = "INSUFFICIENT_EVIDENCE"
        elif intervals[0][0] > intervals[1][1]:
            state = "VALIDATED_RESEARCH_ONLY"
        else:
            state = "REJECTED_VALIDATION"
        hypothesis.update({"status": state, "validation": measured,
                           "production_eligible": False, "forward_validation_required": True})
    return {
        "version": VERSION, "source_sha256": source_sha256,
        "splits": {"train_end_ms": config.train_end_ms, "validation_start_ms": config.train_end_ms + config.embargo_ms,
                   "oos_start_ms": config.oos_start_ms, "embargo_ms": config.embargo_ms,
                   "train_rows": len(train), "validation_rows": len(valid), **excluded},
        "hypotheses": candidates,
        "method": {"feature_selection": "train_only_median_effect_and_pairs",
                   "multiplicity_tests": tests, "family_alpha": .05,
                   "interval_z": z, "intervals": "Bonferroni-adjusted Wilson",
                   "dependence_limit": "Adjacent hourly events remain dependent; intervals assume independent hours. Forward blocked replication required.",
                   "target": "Any strict teacher local of the side in candidate hour; condition may fire once per hourly event.",
                   "additive_quantum_value": None,
                   "additive_value_reason": "No paired forward OOS Quantum/Cortex decisions; association is not incremental predictive improvement.",
                   "oos_used_for_selection": False, "model_or_threshold_changes": False},
    }


def validate_forward_proposals(rows: list[dict], proposals: list[dict], as_of_ms: int,
                               min_events: int = 8, minimum_ts_ms: int = 0) -> list[dict]:
    """Frozen LLM conditions can only use labels from *after* proposal time.

    Historical validation predating a live proposal cannot confirm it. Results
    remain research records; promotion needs paired Quantum/challenger evidence.
    """
    if len(proposals) > 256:
        raise ValueError("cortex_proposal_budget_exceeded")
    z = statistics.NormalDist().inv_cdf(1 - .05 / (4 * max(1, len(proposals))))
    output = []
    for submitted in proposals:
        proposal = submitted.get("proposal") or {}
        stamp = submitted.get("proposed_ts_ms")
        result = {"id": submitted.get("id"), "production_eligible": False,
                  "evaluated_as_of_ms": as_of_ms, "proposed_ts_ms": stamp}
        valid_schema = (proposal.get("side") in ("LOW", "HIGH")
                        and proposal.get("stage_s") in (60, 180, 300)
                        and proposal.get("op") in ("ge", "le")
                        and isinstance(proposal.get("feature"), str)
                        and causal_feature(proposal["feature"])
                        and finite(proposal.get("threshold")) and finite(stamp)
                        and 0 <= stamp <= as_of_ms)
        if not valid_schema:
            output.append({**result, "status": "REJECTED_PROPOSAL_SCHEMA"})
            continue
        condition = [{k: proposal[k] for k in ("feature", "op", "threshold")}]
        future = []
        for row in rows:
            prediction = int(row.get("snapshot_ts_ms", 0))
            matured = row.get("label_mature_ms")
            if (prediction < max(stamp, minimum_ts_ms)
                    or int(row.get("candidate_ts_ms", 0)) < stamp
                    or prediction > as_of_ms or not finite(matured)
                    or not prediction <= matured <= as_of_ms
                    or row.get("side") != proposal["side"] or row.get("delay_s") != proposal["stage_s"]
                    or not isinstance(row.get("strict_true"), bool)):
                continue
            future.append({**row, "features": clean_features(row.get("features"))})
        measured = evidence(future, condition, z)
        enough = (measured["selected_events"] >= min_events and measured["other_events"] >= min_events
                  and measured["selected_positive_events"] >= 3)
        if not enough:
            state = "PENDING_FORWARD_EVIDENCE"
        elif measured["selected_interval"][0] > measured["other_interval"][1]:
            state = "VALIDATED_FORWARD_RESEARCH_ONLY"
        else:
            state = "REJECTED_FORWARD_VALIDATION"
        output.append({**result, "status": state, "evidence": measured,
                       "historical_preproposal_labels_used": False,
                       "incremental_quantum_value": None})
    return output


class StatisticalCortex:
    """Small persistent analyst. Evidence and hypotheses never become signals."""
    def __init__(self, state_path: Path, research_memory: dict | None = None, stale_ms: int = 90_000):
        self.path = Path(state_path)
        self.memory = research_memory or {}
        self.stale_ms = int(stale_ms)
        self.history = deque(maxlen=256)
        self.error = None
        if self.path.exists():
            try:
                stored = load_memory(self.path)
                self.history.extend(stored.get("observations", [])[-256:])
            except (ValueError, KeyError, TypeError, OSError):
                self.error = "cortex_state_invalid_ignored"

    def analyze(self, status: dict, now_ms: int) -> dict:
        candidate = status.get("candidate") or {}
        fresh = finite(status.get("updated_ts_ms")) and 0 <= now_ms - status["updated_ts_ms"] <= self.stale_ms
        side = candidate.get("side")
        evidence_input = status.get("cortex_evidence") or {}
        features = clean_features(evidence_input.get("features"))
        prediction_ts = evidence_input.get("prediction_ts_ms")
        identity_matches = (bool(candidate.get("candidate_id")) and side in ("LOW", "HIGH")
                            and evidence_input.get("candidate_id") == candidate.get("candidate_id")
                            and evidence_input.get("side", side) == side)
        feature_fresh = (finite(prediction_ts) and 0 <= now_ms - prediction_ts <= self.stale_ms
                         and identity_matches)
        supports, contradicts, unknown = [], [], []
        stage = evidence_input.get("stage_s")
        if stage is None:
            stage = max((int(k) for k in (candidate.get("probabilities") or {}) if str(k).isdigit()), default=0)
        if fresh and feature_fresh and side in ("LOW", "HIGH"):
            for hypothesis in self.memory.get("hypotheses", [])[:192]:
                if hypothesis.get("side") != side or hypothesis.get("stage_s") != stage:
                    continue
                result = matches(hypothesis["conditions"], features)
                if result is None:
                    unknown.append(hypothesis["id"])
                elif hypothesis.get("status") == "VALIDATED_RESEARCH_ONLY":
                    (supports if result else contradicts).append(hypothesis["id"])
        tracked_names = sorted({c["feature"] for h in self.memory.get("hypotheses", [])[:192]
                                for c in h.get("conditions", [])})[:16] or sorted(features)[:16]
        tracked_features = {k: features[k] for k in tracked_names if k in features} if feature_fresh and fresh else {}
        current = {"ts_ms": int(status.get("updated_ts_ms") or now_ms), "side": side,
                   "candidate_id": candidate.get("candidate_id"),
                   "prediction_ts_ms": prediction_ts,
                   "features": tracked_features,
                   "probabilities": {str(k): float(v) for k, v in (candidate.get("probabilities") or {}).items() if finite(v)}}
        current["observation_id"] = hashlib.sha256(canonical({k: v for k, v in current.items() if k != "ts_ms"})).hexdigest()[:20]
        previous = self.history[-1] if self.history else None
        deltas = {}
        if previous and previous.get("candidate_id") == current["candidate_id"]:
            for key, value in current["probabilities"].items():
                if key in previous.get("probabilities", {}):
                    deltas[key] = value - previous["probabilities"][key]
        if fresh and (previous is None or current["observation_id"] != previous.get("observation_id")):
            self.history.append(current)
        distribution_shift = []
        observed = [row for row in self.history if row.get("features") and row.get("side") == side]
        if len(observed) >= 48:
            reference, recent = observed[-48:-16], observed[-16:]
            for name in tracked_names:
                old = [row["features"][name] for row in reference if name in row["features"]]
                new = [row["features"][name] for row in recent if name in row["features"]]
                if len(old) < 24 or len(new) < 12:
                    continue
                center = statistics.median(old)
                scale = max(1e-9, 1.4826 * statistics.median(abs(v - center) for v in old))
                shift = (statistics.median(new) - center) / scale
                if abs(shift) >= 3:
                    distribution_shift.append({"feature": name, "robust_median_shift": max(-1e6, min(1e6, shift))})
        missing = []
        if not fresh:
            missing.append("fresh_quantum_status")
        if not feature_fresh or not features:
            missing.append("fresh_causal_feature_snapshot")
        if not self.memory.get("hypotheses"):
            missing.append("validated_hypothesis_memory")
        if unknown:
            missing.append("features_for_" + str(len(unknown)) + "_hypotheses")
        # Confidence is deliberately not invented from relationship lift. A
        # calibrated meta-probability needs separate paired forward evidence.
        decision = {"verdict": "WAIT", "confidence": 0.0,
                    "supporting_relationships": supports[:6], "contradicting_relationships": contradicts[:6],
                    "missing_live_evidence": missing[:12], "hypotheses": [],
                    "summary": "Statistical research advisory; Quantum inference remains independent. No calibrated Cortex signal or incremental OOS gain established."}
        report = {"decision": decision, "fresh_status": bool(fresh), "fresh_features": bool(feature_fresh),
                  "probability_deltas_same_stage": deltas, "observations_retained": len(self.history),
                  "matched_research_hypotheses": supports, "contradicted_research_hypotheses": contradicts,
                  "regime": "DESCRIPTIVE_DISTRIBUTION_SHIFT" if distribution_shift else "UNVALIDATED",
                  "distribution_shifts": distribution_shift,
                  "regime_note": "Observed shifts are diagnostics using 32 prior/16 recent distinct snapshots, not a validated market regime classifier.",
                  "model_or_threshold_changes": False, "incremental_oos_value": None, "load_error": self.error}
        save_memory(self.path, {"version": VERSION, "observations": list(self.history)})
        return report
