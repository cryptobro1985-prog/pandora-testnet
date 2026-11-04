"""Causal, research-only alternating H1 local detector.

The bounded score is an UNCALIBRATED heuristic, not a probability, likelihood
ratio, SPRT, or assurance of a reversal. Overlapping flow windows are not added
as independent evidence. Model selection and claims require external replay.
Input timestamps are bar-END availability times. OHLC extrema have intervals,
not invented within-bar times/order. No production runtime imports this module.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, asdict
import copy
import math
from typing import Any

try:
    from .features import FeatureBuilder
except ImportError:  # direct script import for repository research commands
    from features import FeatureBuilder


def finite(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def clamp(value, low=0.0, high=1.0):
    return min(high, max(low, value))


@dataclass(frozen=True)
class Config:
    model_family: str = "B"
    maturity_atr: float = 1.0
    accept_score: float = 0.65
    min_survival_seconds: float = 60.0
    warmup_hours: int = 6
    retracement_scale: float = 0.40
    evidence_half_life_seconds: float = 60.0
    # False is the price/flow baseline. True tests the stronger, unvalidated
    # climax -> absorption -> effective transfer hypothesis explicitly.
    require_absorption: bool = False
    climax_activity_ratio: float = 1.5
    absorption_activity_ratio: float = 1.0
    absorption_efficiency_decay: float = 0.5

    def __post_init__(self):
        if self.model_family not in "ABCDEF" or len(self.model_family) != 1:
            raise ValueError("model_family must be A, B, C, D, E or F")
        if self.warmup_hours < 6:
            raise ValueError("at least six completed H1 bars are required")
        for name in ("maturity_atr", "min_survival_seconds", "retracement_scale", "evidence_half_life_seconds"):
            if not finite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(name + " must be finite and positive")
        if not finite(self.accept_score) or not 0 < self.accept_score <= 1:
            raise ValueError("accept_score must lie in (0, 1]")
        for name in ("climax_activity_ratio", "absorption_activity_ratio"):
            if not finite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(name + " must be finite and positive")
        if not finite(self.absorption_efficiency_decay) or not 0 <= self.absorption_efficiency_decay <= 1:
            raise ValueError("absorption_efficiency_decay must lie in [0, 1]")
        if self.require_absorption and self.model_family == "A":
            raise ValueError("price-only A cannot require unobserved flow absorption")


class Engine:
    """Sequential state machine with no external/oracle local anchors.

    Bootstrapping chooses an initial observed anchor from the six-hour causal
    prefix in the direction of its net move. It is labelled BOOTSTRAP_SEED and
    excluded from confirmed locals. Confirmations alternate; an adverse extension
    of the previous same-side anchor is recorded without rewriting old signals.
    """
    def __init__(self, config: Config | None = None, *, retain_trajectory=True, retain_events=True):
        self.config = config or Config()
        self.builder = FeatureBuilder()
        self.candidates: list[dict] = []
        self.confirmed: list[dict] = []
        self.episodes: list[dict] = []
        self.trajectory: list[dict] = []
        self.events: list[dict] = []
        self.retain_trajectory = retain_trajectory
        self.retain_events = retain_events
        self._current_events = []
        self._external_feature_mode = None
        self.state = "WARMUP"
        self.anchor = None
        self.running = None
        self.candidate = None
        self.last_ts = None
        self.last_row = None
        self._history = deque()
        self._acceptance = deque()
        self._episode = None
        self._score_ts = None
        self._running_features = None

    def _event(self, kind, ts, **values):
        event = {"event": kind, "ts_ms": ts, **values}
        self._current_events.append(event)
        if self.retain_events:
            self.events.append(event)
        return event

    @staticmethod
    def _extreme(row, side):
        key = "high" if side == "HIGH" else "low"
        available = int(row["ts_ms"])
        end = int(row.get("bar_end_ms", int(row.get("start_ms", available - int(row.get("interval_ms", 60_000)))) + int(row.get("interval_ms", 60_000))))
        start = int(row.get("start_ms", end - int(row.get("interval_ms", 60_000))))
        exact = row.get(key + "_ts_ms")
        if exact is not None and not start <= exact <= end:
            raise ValueError("exact extreme timestamp is outside observed interval")
        return {"extreme_price": float(row[key]), "extreme_ts_ms": exact,
                "extreme_interval_start_ms": start, "extreme_interval_end_ms": end,
                "extreme_available_ms": available}

    @property
    def seek_side(self):
        return "HIGH" if self.anchor and self.anchor["side"] == "LOW" else "LOW"

    def _new_episode(self, ts):
        self._episode = {"episode_id": len(self.episodes) + 1,
                         "start_ts_ms": ts, "side": self.seek_side,
                         "anchor_side": self.anchor["side"], "anchor_price": self.anchor["price"],
                         "anchor_ts_ms": self.anchor["ts_ms"], "anchor_source": self.anchor["source"],
                         "first_candidate_id": None, "first_accepted_candidate_id": None,
                         "anchor_extensions": [], "end_ts_ms": None}
        self.episodes.append(self._episode)
        self._acceptance.clear()
        self.state = "ACTIVE_SWING"

    def _bootstrap(self, row):
        history = list(self._history)
        bullish = row["close"] >= history[0]["open"]
        side = "LOW" if bullish else "HIGH"
        key = "low" if bullish else "high"
        index = min(range(len(history)), key=lambda i: history[i][key]) if bullish else max(range(len(history)), key=lambda i: history[i][key])
        initial = self._extreme(history[index], side)
        self.anchor = {"side": side, "price": initial["extreme_price"],
                       "ts_ms": initial["extreme_available_ms"], "source": "BOOTSTRAP_SEED"}
        # Same-bar opposing extremum order is unknown: only subsequent bars can
        # define the initial active swing. A close is available after both bounds.
        subsequent = history[index + 1:]
        if subsequent:
            running_row = max(subsequent, key=lambda r: r["high"]) if bullish else min(subsequent, key=lambda r: r["low"])
            self.running = self._extreme(running_row, self.seek_side)
        else:
            self.running = {"extreme_price": float(row["close"]), "extreme_ts_ms": row["ts_ms"],
                            "extreme_interval_start_ms": row["ts_ms"], "extreme_interval_end_ms": row["ts_ms"],
                            "extreme_available_ms": row["ts_ms"]}
        self._new_episode(row["ts_ms"])
        self._event("BOOTSTRAP_SEED", row["ts_ms"], anchor=copy.deepcopy(self.anchor), side=self.seek_side)

    def _invalidate(self, ts, reason):
        if self.candidate:
            self.candidate.update(status="INVALIDATED", invalidation_ts_ms=ts, invalidation_reason=reason)
            self._event("CANDIDATE_INVALIDATED", ts, candidate_id=self.candidate["candidate_id"], reason=reason)
            self.candidate = None
        self._score_ts = None
        self._running_features = None
        self._acceptance.clear()
        self.state = "ACTIVE_SWING"

    def _missing(self, features):
        missing = []
        if self.config.model_family != "A":
            for key in ("flow_imbalance_60s", "flow_imbalance_300s", "price_displacement_60s"):
                if not finite(features.get(key)):
                    missing.append(key)
        if self.config.model_family in "CDEF":
            if not finite(features.get("oi_delta_300s")):
                missing.append("oi_delta_300s")
        if self.config.model_family in "DF":
            for key in ("long_liq_notional_60s", "short_liq_notional_60s"):
                if not finite(features.get(key)):
                    missing.append(key)
        if self.config.model_family in "EF":
            key = ("ask" if self.seek_side == "HIGH" else "bid") + "_replenishment_ratio_60s"
            if not finite(features.get(key)):
                missing.append(key)
        return missing

    def _note_stage(self, stage, ts, source_ts=None, **measurements):
        if any(x["stage"] == stage for x in self.candidate["stage_history"]):
            return
        self.candidate["stage_history"].append({"stage": stage, "ts_ms": ts,
            "source_ts_ms": ts if source_ts is None else source_ts,
            "measurements": measurements})

    def _observe_stages(self, features, ts, source_ts=None):
        """Record measured heuristic evidence, never infer stages from score."""
        if self.config.model_family == "A":
            return
        old_side = "buy" if self.seek_side == "HIGH" else "sell"
        a, b = features.get(old_side+"_notional_60s"), features.get(old_side+"_notional_300s")
        e, baseline = features.get(old_side+"_efficiency_60s"), features.get(old_side+"_efficiency_300s")
        activity = 5*a/b if finite(a) and finite(b) and b > 0 else None
        decay = clamp(1-e/baseline) if finite(e) and finite(baseline) and baseline > 0 else None
        if finite(activity) and activity >= self.config.climax_activity_ratio:
            self._note_stage("CLIMAX", ts, source_ts, activity_ratio=activity)
        seen = {s["stage"]: s for s in self.candidate["stage_history"]}
        source = ts if source_ts is None else source_ts
        # Windows may overlap, but one snapshot cannot establish temporal order
        # of climax, absorption and transfer. Require later observed sources.
        if "CLIMAX" in seen and source > seen["CLIMAX"]["source_ts_ms"] and finite(activity) and activity >= self.config.absorption_activity_ratio and finite(decay) and decay >= self.config.absorption_efficiency_decay:
            self._note_stage("ABSORPTION", ts, source_ts, activity_ratio=activity, efficiency_decay=decay,
                             interpretation="price-response proxy; passive fills are not identified")
        old_sign = 1 if self.seek_side == "HIGH" else -1
        imbalance, response = features.get("flow_imbalance_60s"), features.get("price_displacement_60s")
        seen = {s["stage"]: s for s in self.candidate["stage_history"]}
        if finite(imbalance) and finite(response) and imbalance*old_sign < 0 and response*old_sign < 0:
            if not self.config.require_absorption or ("ABSORPTION" in seen and source > seen["ABSORPTION"]["source_ts_ms"]):
                self._note_stage("EARLY_CONTROL_TRANSFER", ts, source_ts,
                                 flow_imbalance_60s=imbalance, price_displacement_60s=response)

    def _score(self, row, features, amplitude, atr, retracement, survival):
        old_sign = 1 if self.seek_side == "HIGH" else -1
        new_sign = -old_sign
        elapsed = row["ts_ms"] - self.running["extreme_available_ms"]
        self._acceptance.append((row["ts_ms"], old_sign * (self.running["extreme_price"] - row["close"]) > 0.03 * amplitude))
        while self._acceptance and self._acceptance[0][0] < row["ts_ms"] - 180_000:
            self._acceptance.popleft()
        acceptance = sum(x[1] for x in self._acceptance) / len(self._acceptance)
        components = {"structure": clamp(amplitude / (2 * self.config.maturity_atr * atr)),
                      "retracement": clamp(retracement / self.config.retracement_scale),
                      "survival": 1 - math.exp(-survival / 600), "price_acceptance": acceptance}
        weights = {"structure": .15, "retracement": .40, "survival": .25, "price_acceptance": .20}
        if self.config.model_family != "A":
            short = features.get("flow_imbalance_60s") or 0.0
            medium = features.get("flow_imbalance_300s") or 0.0
            price_response = new_sign * (features.get("price_displacement_60s") or 0.0)
            components["flow_persistence"] = clamp(new_sign * min(short, medium) if new_sign > 0 else new_sign * max(short, medium))
            new_side = "sell" if new_sign < 0 else "buy"
            new_short = features.get(new_side + "_efficiency_60s")
            new_medium = features.get(new_side + "_efficiency_300s")
            relative_efficiency = 0.0
            if finite(new_short) and finite(new_medium) and new_medium > 0:
                relative_efficiency = clamp((new_short / new_medium - .5) / 1.5)
            # Require effective directional price response AND improvement in
            # displacement per aggressive dollar versus the side's own baseline.
            components["new_side_efficiency"] = relative_efficiency * clamp(price_response / max(.10 * atr, 1e-12))
            old_side = "buy" if old_sign > 0 else "sell"
            old_short = features.get(old_side + "_efficiency_60s")
            old_medium = features.get(old_side + "_efficiency_300s")
            decay = 0.0 if not finite(old_short) or not finite(old_medium) or old_medium <= 0 else clamp(1 - old_short / old_medium)
            old_short_notional = features.get(old_side + "_notional_60s")
            old_medium_notional = features.get(old_side + "_notional_300s")
            activity_ratio = 0.0
            if finite(old_short_notional) and finite(old_medium_notional) and old_medium_notional > 0:
                activity_ratio = 5 * old_short_notional / old_medium_notional
            # The absence of old-side trades is not evidence of absorption.
            components["old_side_efficiency_decay"] = decay * clamp(activity_ratio)
            weights = {"structure": .10, "retracement": .30, "survival": .15, "price_acceptance": .15,
                       "flow_persistence": .15, "new_side_efficiency": .10, "old_side_efficiency_decay": .05}
        if self.config.model_family in "CDEF" and finite(features.get("oi_delta_300s")):
            # Unitless fractional OI growth. This is a directional context proxy,
            # never identification of positions or liquidation attribution.
            components["oi_context"] = clamp(max(features["oi_delta_300s"], 0) / .01)
            weights["oi_context"] = .05
        if self.config.model_family in "DF":
            climax_key = "short_liq_notional_60s" if self.seek_side == "HIGH" else "long_liq_notional_60s"
            opposite_key = "long_liq_notional_60s" if self.seek_side == "HIGH" else "short_liq_notional_60s"
            total = (features.get(climax_key) or 0) + (features.get(opposite_key) or 0)
            components["liquidation_climax"] = (features.get(climax_key) or 0) / total if total else 0.0
            weights["liquidation_climax"] = .05
        if self.config.model_family in "EF":
            key = ("ask" if self.seek_side == "HIGH" else "bid") + "_replenishment_ratio_60s"
            components["book_absorption"] = clamp((features.get(key) or 0) / 2)
            weights["book_absorption"] = .05
        raw_score = sum(components[k] * w for k, w in weights.items()) / sum(weights.values())
        # Time-weighted low-pass evidence, not a sum of dependent log likelihoods.
        previous = self.candidate["score"]
        step_seconds = max(0, (row["ts_ms"] - (self._score_ts or row["ts_ms"])) / 1000)
        alpha = 1 - math.exp(-math.log(2) * step_seconds / self.config.evidence_half_life_seconds)
        score = raw_score if self._score_ts is None else previous + alpha * (raw_score - previous)
        self._score_ts = row["ts_ms"]
        return score, components, acceptance

    def update(self, row: dict[str, Any], *, observed_features=None) -> list[dict]:
        """Consume a completed observed bar and emit immutable event snapshots.

        A trusted batch replay may share one strictly causal FeatureBuilder's
        snapshot across engines via observed_features. It must reset that builder
        at physical gaps, and may not mix supplied and internal features.
        """
        self._current_events = []
        ts = int(row["ts_ms"])
        if self.last_ts is not None and ts <= self.last_ts:
            raise ValueError("rows must have strictly increasing availability timestamps")
        for name in ("open", "high", "low", "close"):
            if not finite(row.get(name)) or row[name] <= 0:
                raise ValueError(name + " must be finite and positive")
        if row["low"] > min(row["open"], row["close"]) or row["high"] < max(row["open"], row["close"]):
            raise ValueError("invalid OHLC bounds")
        duration = int(row.get("interval_ms", 60_000))
        if duration <= 0:
            raise ValueError("interval_ms must be positive")
        start = int(row.get("start_ms", ts - duration))
        if start >= ts or ts < start + duration:
            raise ValueError("bar availability/start/duration mismatch")
        gap = self.last_row is not None and start != int(self.last_row.get("bar_end_ms", self.last_row.get("start_ms", self.last_ts - duration) + int(self.last_row.get("interval_ms", duration))))
        if gap:
            self._invalidate(ts, "DATA_GAP")
            if self._episode:
                self._episode.update(end_ts_ms=ts, termination_reason="DATA_GAP")
            self.anchor = self.running = self.candidate = None
            self._history.clear()
            self.builder = FeatureBuilder()
            self.state = "WARMUP"
            self._event("WAIT", ts, reason="DATA_GAP_REWARMUP")
        external_mode = observed_features is not None
        if self._external_feature_mode is None:
            self._external_feature_mode = external_mode
        elif external_mode != self._external_feature_mode:
            raise ValueError("cannot mix supplied and internally built feature histories")
        if external_mode:
            if observed_features.get("ts_ms") != ts:
                raise ValueError("supplied features must have the current availability timestamp")
            features = observed_features
        else:
            features = self.builder.update(row)
        if self.anchor is None:
            self._history.append(copy.deepcopy(row))
            while self._history and self._history[0]["ts_ms"] < ts - self.config.warmup_hours * 3_600_000:
                self._history.popleft()
        self.last_ts, self.last_row = ts, copy.deepcopy(row)
        if self.anchor is None:
            if features.get("completed_h1_count", 0) >= self.config.warmup_hours and features.get("atr_h1"):
                self._bootstrap(row)
                # Historical swing extremes within the seed prefix have no
                # retained feature snapshot; do not attach the current features
                # to their earlier availability times.
                if self.running["extreme_available_ms"] == ts:
                    self._running_features = copy.deepcopy(features)
                self._history.clear()
            return copy.deepcopy(self._current_events)
        # A same-side extension of the previous confirmed anchor is an extension,
        # not another accepted same-side local. Never amend old confirmation rows.
        anchor_side = self.anchor["side"]
        anchor_extreme = float(row["low"] if anchor_side == "LOW" else row["high"])
        extended_anchor = anchor_extreme < self.anchor["price"] if anchor_side == "LOW" else anchor_extreme > self.anchor["price"]
        if extended_anchor:
            self._invalidate(ts, "ANCHOR_EXTENSION")
            extension = {"ts_ms": ts, "old_price": self.anchor["price"], "new_price": anchor_extreme,
                         "side": anchor_side, "extreme_time_is_interval": True}
            self.anchor.update(price=anchor_extreme, ts_ms=ts, source="ANCHOR_EXTENSION")
            self._episode["anchor_extensions"].append(extension)
            # A same-bar high and low cannot establish which occurred second.
            self.running = {"extreme_price": float(row["close"]), "extreme_ts_ms": ts,
                            "extreme_interval_start_ms": ts, "extreme_interval_end_ms": ts,
                            "extreme_available_ms": ts}
            self._event("ANCHOR_EXTENSION", ts, **{k: v for k, v in extension.items() if k != "ts_ms"})
            return copy.deepcopy(self._current_events)
        side = self.seek_side
        same_side = float(row["high"] if side == "HIGH" else row["low"])
        new_extreme = same_side > self.running["extreme_price"] if side == "HIGH" else same_side < self.running["extreme_price"]
        if new_extreme:
            self._invalidate(ts, "NEW_SAME_SIDE_EXTREME")
            self.running = self._extreme(row, side)
            self._running_features = copy.deepcopy(features)
            self._event("RUNNING_EXTREME", ts, side=side, **self.running)
            return copy.deepcopy(self._current_events)
        amplitude = abs(self.running["extreme_price"] - self.anchor["price"])
        atr = features.get("atr_h1")
        if not finite(atr) or atr <= 0 or amplitude < self.config.maturity_atr * atr:
            self.state = "ACTIVE_SWING"
            return copy.deepcopy(self._current_events)
        self.state = "STRUCTURAL_MATURITY"
        retracement = abs(float(row["close"]) - self.running["extreme_price"]) / amplitude if amplitude else 0.0
        if (side == "HIGH" and row["close"] >= self.running["extreme_price"]) or (side == "LOW" and row["close"] <= self.running["extreme_price"]):
            return copy.deepcopy(self._current_events)
        survival = (ts - self.running["extreme_available_ms"]) / 1000
        if self.candidate is None:
            self.candidate = {"candidate_id": len(self.candidates) + 1, "episode_id": self._episode["episode_id"],
                              "side": side, "candidate_ts_ms": ts, "ts_ms": ts,
                              **copy.deepcopy(self.running), "anchor_side": self.anchor["side"],
                              "anchor_price": self.anchor["price"], "anchor_ts_ms": self.anchor["ts_ms"],
                              "status": "FORMING", "score": 0.0, "score_is_probability": False,
                              "confirmation_ts_ms": None, "confirmation_price": None,
                              "invalidation_reason": None, "features": {}}
            self.candidate["stage_history"] = []
            self.candidates.append(self.candidate)
            if self._episode["first_candidate_id"] is None:
                self._episode["first_candidate_id"] = self.candidate["candidate_id"]
            self._event("CANDIDATE", ts, candidate_id=self.candidate["candidate_id"], side=side)
            self._note_stage("STRUCTURAL_MATURITY", ts, maturity_atr=amplitude/atr)
            self._note_stage("RUNNING_EXTREME", ts, self.running["extreme_available_ms"], extreme_price=self.running["extreme_price"])
            if self._running_features:
                self._observe_stages(self._running_features, ts, self.running["extreme_available_ms"])
        self._observe_stages(features, ts)
        missing = self._missing(features)
        if missing:
            waiting_features = {**features, "swing_amplitude": amplitude, "maturity_atr": amplitude/atr,
                                "retracement_fraction": retracement, "survival_seconds": survival}
            self.candidate.update(status="WAIT_MISSING_DATA", missing_features=missing, features=copy.deepcopy(waiting_features))
            if self.retain_trajectory:
                self.trajectory.append({"candidate_id": self.candidate["candidate_id"], "episode_id": self._episode["episode_id"],
                    "ts_ms": ts, "side": side, "score": None, "score_is_probability": False,
                    "state": "WAIT_MISSING_DATA", "missing_features": list(missing), "features": copy.deepcopy(waiting_features)})
            self._event("WAIT", ts, candidate_id=self.candidate["candidate_id"], reason="MISSING_FEATURES", missing_features=missing)
            return copy.deepcopy(self._current_events)
        score, components, acceptance = self._score(row, features, amplitude, atr, retracement, survival)
        self.state = "EVIDENCE_ACCUMULATION"
        flow = features.get("flow_imbalance_60s")
        if any(x["stage"] == "EARLY_CONTROL_TRANSFER" for x in self.candidate["stage_history"]):
            self.state = "EARLY_CONTROL_TRANSFER"
        candidate_features = {**features, "swing_amplitude": amplitude, "maturity_atr": amplitude / atr,
                              "retracement_fraction": retracement, "survival_seconds": survival,
                              "price_acceptance": acceptance, "score_components": components}
        self.candidate.update(score=score, status=self.state, features=copy.deepcopy(candidate_features))
        self._note_stage("EVIDENCE_ACCUMULATION", ts, score_kind="uncalibrated_heuristic")
        if self.retain_trajectory:
            self.trajectory.append({"candidate_id": self.candidate["candidate_id"], "episode_id": self._episode["episode_id"],
                                    "ts_ms": ts, "side": side, "score": score, "score_is_probability": False,
                                    "state": self.state, "features": copy.deepcopy(candidate_features)})
        old_sign = 1 if side == "HIGH" else -1
        effective_opposite = self.config.model_family == "A" or (
            (features.get("flow_imbalance_60s") or 0) * old_sign < 0 and
            (features.get("price_displacement_60s") or 0) * old_sign < 0)
        stages = {x["stage"] for x in self.candidate["stage_history"]}
        pattern_ready = not self.config.require_absorption or {"CLIMAX", "ABSORPTION", "EARLY_CONTROL_TRANSFER"} <= stages
        if score >= self.config.accept_score and survival >= self.config.min_survival_seconds and effective_opposite and pattern_ready:
            self._note_stage("CONFIRMED_LOCAL", ts, score=score)
            self.candidate.update(status="CONFIRMED_LOCAL", confirmation_ts_ms=ts, confirmation_price=float(row["close"]))
            accepted = copy.deepcopy(self.candidate)
            self.confirmed.append(accepted)
            self._episode.update(first_accepted_candidate_id=accepted["candidate_id"], end_ts_ms=ts)
            self._event("CONFIRMED_LOCAL", ts, **{k: v for k, v in accepted.items() if k != "ts_ms"})
            self.anchor = {"side": side, "price": accepted["extreme_price"], "ts_ms": accepted["extreme_available_ms"], "source": "CONFIRMED_LOCAL"}
            self.candidate = None
            self._running_features = None
            self._score_ts = None
            # Post-extreme opposite bar extrema may predate the confirmed extreme;
            # initialize new seek state at the known confirmation close only.
            self.running = {"extreme_price": float(row["close"]), "extreme_ts_ms": ts,
                            "extreme_interval_start_ms": ts, "extreme_interval_end_ms": ts,
                            "extreme_available_ms": ts}
            self._new_episode(ts)
        return copy.deepcopy(self._current_events)

    def snapshot(self):
        return {"config": asdict(self.config), "state": self.state, "seek_side": self.seek_side if self.anchor else None,
                "anchor": copy.deepcopy(self.anchor), "running": copy.deepcopy(self.running),
                "candidate": copy.deepcopy(self.candidate), "last_ts_ms": self.last_ts,
                "score_is_probability": False}
