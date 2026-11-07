"""Frozen champion/challenger forward evidence; no in-sample auto-promotion."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

H = 3_600_000


@dataclass
class ForwardEvidence:
    challenger_id: str
    training_cutoff_ms: int
    embargo_ms: int = 9 * H
    minimum_groups: int = 32
    minimum_positives_per_side: int = 8
    maximum_groups: int = 64
    rows: dict = field(default_factory=dict)
    # Distinct decisions inside one hour are not independent experiments.
    seen_events: set = field(default_factory=set)

    def register(self, pending):
        """Preselect evaluation decisions at prediction time, before outcomes."""
        if pending.challenger_id != self.challenger_id or pending.stage != 300:
            return False
        hour = pending.extreme_ts_ms // H * H
        if min(hour, pending.prediction_ts_ms) < self.training_cutoff_ms + self.embargo_ms:
            return False
        key = f"{pending.side}:{hour}"
        if key in self.seen_events:
            return False
        hours = sorted({row["hour_ms"] for row in self.rows.values()})
        if len(hours) >= self.maximum_groups and hour not in hours:
            return False
        if hours and hour != hours[-1] and hour < hours[-1] + self.embargo_ms:
            return False
        self.seen_events.add(key)
        # First chronological proposal is chosen, never the best eventual one.
        self.rows[key] = {
            "hour_ms": hour, "side": pending.side, "label": None,
            "label_id": pending.label_id, "censored": False,
            "champion": float(pending.champion_probability),
            "challenger": float(pending.challenger_probability),
            "champion_threshold": float(pending.champion_threshold),
            "challenger_threshold": float(pending.challenger_threshold),
            "prediction_ts_ms": pending.prediction_ts_ms,
        }
        return True

    def observe(self, pending, label):
        key = f"{pending.side}:{pending.extreme_ts_ms // H * H}"
        row = self.rows.get(key)
        if not row or row["label_id"] != pending.label_id:
            return False
        if row["label"] is not None or row["censored"]:
            return False
        row["label"] = None if label is None else bool(label)
        row["censored"] = label is None
        return True

    @staticmethod
    def _metrics(rows, model):
        tp = fp = fn = 0
        for row in rows:
            predicted = row[model] >= row[model + "_threshold"]
            tp += int(predicted and row["label"])
            fp += int(predicted and not row["label"])
            fn += int(not predicted and row["label"])
        return {"precision": tp / (tp + fp) if tp + fp else 0.0,
                "recall": tp / (tp + fn) if tp + fn else 0.0,
                "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0,
                "tp": tp, "fp": fp, "fn": fn}

    def decision(self):
        rows = [row for row in self.rows.values() if row["label"] is not None]
        blocks = {}
        for row in rows:
            # Preselected event hours are >= nine hours apart. LOW and HIGH at
            # one hour belong to a single paired statistical group.
            key = row["hour_ms"]
            improvement = ((row["champion"] - row["label"]) ** 2
                           - (row["challenger"] - row["label"]) ** 2)
            blocks.setdefault(key, []).append(improvement)
        means = [statistics.mean(values) for values in blocks.values()]
        result = {"promote": False, "challenger_id": self.challenger_id,
                  "event_count": len(rows), "independent_time_blocks": len(means),
                  "registered_predictions": len(self.rows),
                  "censored_predictions": sum(row["censored"] for row in self.rows.values()),
                  "training_cutoff_ms": self.training_cutoff_ms, "embargo_ms": self.embargo_ms}
        if len({row["hour_ms"] for row in self.rows.values()}) < self.maximum_groups:
            return {**result, "reason": "COLLECTING_FIXED_FORWARD_COHORT"}
        if any(row["label"] is None and not row["censored"] for row in self.rows.values()):
            return {**result, "reason": "WAITING_COHORT_LABEL_MATURITY"}
        if len(means) < self.minimum_groups:
            return {**result, "reason": "INSUFFICIENT_INDEPENDENT_FORWARD_BLOCKS"}
        side_metrics = {}
        for side in ("LOW", "HIGH"):
            sample = [row for row in rows if row["side"] == side]
            if sum(row["label"] for row in sample) < self.minimum_positives_per_side or not any(not row["label"] for row in sample):
                return {**result, "reason": f"INSUFFICIENT_{side}_FORWARD_LABELS"}
            baseline, proposed = self._metrics(sample, "champion"), self._metrics(sample, "challenger")
            side_metrics[side] = {"champion": baseline, "challenger": proposed}
            if proposed["f1"] < baseline["f1"] or proposed["recall"] < baseline["recall"] - 0.02:
                return {**result, "side_metrics": side_metrics, "reason": f"{side}_F1_OR_RECALL_REGRESSION"}
        improvement = statistics.mean(means)
        error = statistics.stdev(means) / math.sqrt(len(means)) if len(means) > 1 else float("inf")
        # 2.1 is a conservative finite-sample paired normal approximation.
        lower = improvement - 2.1 * error
        return {**result, "side_metrics": side_metrics, "brier_improvement": improvement,
                "brier_improvement_lower_95_approx": lower,
                "promote": lower > 0.005,
                "reason": "FORWARD_GATE_PASSED" if lower > 0.005 else "NO_RELIABLE_PAIRED_IMPROVEMENT"}
