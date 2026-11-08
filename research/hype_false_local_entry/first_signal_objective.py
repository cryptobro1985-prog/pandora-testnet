"""First-signal objective for HYPE broad INTERNAL locals.

The trading failure we care about is NOT "how many individual candidates were
classified correctly".  It is "which accepted candidate fired FIRST inside the
active LOW->HIGH / HIGH->LOW swing".

This module is intentionally model-agnostic.  It can score rule engines, ML
probabilities, or live-forward logs, while keeping the teacher/evaluation layer
strictly offline.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional


@dataclass(frozen=True)
class SwingEpisode:
    ep: int
    previous_label_id: int
    target_label_id: int
    target_side: str
    start_ms: int
    end_ms: int


def finalized_labels(labels: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = [dict(x) for x in labels if bool(x.get("reference_finalized", True))]
    out.sort(key=lambda x: int(x["extreme_interval_start_ms"]))
    return out


def build_episodes(labels: Iterable[Mapping[str, Any]]) -> list[SwingEpisode]:
    """Build alternating completed swings from finalized teacher labels."""
    rows = finalized_labels(labels)
    episodes: list[SwingEpisode] = []
    for i, (prev, target) in enumerate(zip(rows, rows[1:]), 1):
        if prev["side"] == target["side"]:
            raise ValueError("teacher labels are not alternating")
        start = int(prev["extreme_interval_start_ms"])
        end = int(target.get("extreme_interval_end_ms", target["extreme_interval_start_ms"]))
        if end <= start:
            raise ValueError("non-positive swing interval")
        episodes.append(
            SwingEpisode(
                ep=i,
                previous_label_id=int(prev["label_id"]),
                target_label_id=int(target["label_id"]),
                target_side=str(target["side"]),
                start_ms=start,
                end_ms=end,
            )
        )
    return episodes


def assign_episode(ts_ms: int, side: str, episodes: Iterable[SwingEpisode]) -> Optional[SwingEpisode]:
    ts_ms = int(ts_ms)
    side = str(side)
    for ep in episodes:
        if ep.target_side == side and ep.start_ms < ts_ms <= ep.end_ms:
            return ep
    return None


def summarize_first_signals(
    records: Iterable[Mapping[str, Any]],
    labels: Iterable[Mapping[str, Any]],
    *,
    accepted: Callable[[Mapping[str, Any]], bool] | None = None,
    timestamp_key: str = "signal_ts_ms",
    candidate_timestamp_key: str = "candidate_ts_ms",
    true_key: str = "internal_true",
    label_id_key: str = "internal_label_id",
) -> dict[str, Any]:
    """Score the FIRST accepted signal in every completed swing.

    A later true candidate does not erase an earlier false signal.  That is the
    key difference from candidate-level precision and is the metric required by
    a flip/reversal system.
    """
    episodes = build_episodes(labels)
    by_ep: dict[int, list[tuple[int, Mapping[str, Any], SwingEpisode]]] = defaultdict(list)
    accepted = accepted or (lambda r: bool(r.get("accepted")))

    for row in records:
        candidate_ts = int(row.get(candidate_timestamp_key, row.get(timestamp_key, 0)) or 0)
        ep = assign_episode(candidate_ts, str(row.get("side")), episodes)
        if ep is None or not accepted(row):
            continue
        signal_ts = int(row.get(timestamp_key, candidate_ts) or candidate_ts)
        by_ep[ep.ep].append((signal_ts, row, ep))

    first_rows = []
    true_first = false_first = 0
    low_tp = low_fp = high_tp = high_fp = 0
    delays_ms = []

    for ep in episodes:
        rows = sorted(by_ep.get(ep.ep, []), key=lambda z: (z[0], int(z[1].get(candidate_timestamp_key, z[0]))))
        if not rows:
            continue
        signal_ts, row, _ = rows[0]
        is_true = bool(row.get(true_key)) and int(row.get(label_id_key) or -1) == ep.target_label_id
        if is_true:
            true_first += 1
            delays_ms.append(max(0, signal_ts - int(row.get(candidate_timestamp_key, signal_ts))))
            if ep.target_side == "LOW":
                low_tp += 1
            else:
                high_tp += 1
        else:
            false_first += 1
            if ep.target_side == "LOW":
                low_fp += 1
            else:
                high_fp += 1
        first_rows.append(
            {
                "episode": ep.ep,
                "target_label_id": ep.target_label_id,
                "target_side": ep.target_side,
                "signal_ts_ms": signal_ts,
                "candidate_id": row.get("candidate_id"),
                "candidate_ts_ms": int(row.get(candidate_timestamp_key, signal_ts)),
                "true_first": is_true,
            }
        )

    accepted_n = true_first + false_first
    total = len(episodes)
    precision = true_first / accepted_n if accepted_n else 0.0
    recall = true_first / total if total else 0.0
    false_first_rate = false_first / accepted_n if accepted_n else None
    sorted_delay = sorted(delays_ms)
    median_delay = None
    if sorted_delay:
        n = len(sorted_delay)
        median_delay = (
            float(sorted_delay[n // 2])
            if n % 2
            else (sorted_delay[n // 2 - 1] + sorted_delay[n // 2]) / 2.0
        )

    return {
        "episodes": total,
        "accepted_first": accepted_n,
        "true_first": true_first,
        "false_first": false_first,
        "no_signal": total - accepted_n,
        "precision": precision,
        "recall": recall,
        "false_first_rate": false_first_rate,
        "median_true_signal_delay_s": None if median_delay is None else median_delay / 1000.0,
        "by_side": {
            "LOW": {"true_first": low_tp, "false_first": low_fp},
            "HIGH": {"true_first": high_tp, "false_first": high_fp},
        },
        "first_signals": first_rows,
    }


def promotion_gate(metrics: Mapping[str, Any], *, min_precision: float = 0.80,
                   min_recall: float = 0.40, min_true_first: int = 10,
                   min_episodes: int = 20) -> dict[str, Any]:
    """Conservative research gate; passing still authorizes PAPER/FORWARD only."""
    checks = {
        "episodes": int(metrics.get("episodes", 0)) >= min_episodes,
        "precision": float(metrics.get("precision", 0.0)) >= min_precision,
        "recall": float(metrics.get("recall", 0.0)) >= min_recall,
        "true_first": int(metrics.get("true_first", 0)) >= min_true_first,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "requirements": {
            "min_precision": min_precision,
            "min_recall": min_recall,
            "min_true_first": min_true_first,
            "min_episodes": min_episodes,
        },
        "authorization": "PAPER_FORWARD_ONLY",
    }
