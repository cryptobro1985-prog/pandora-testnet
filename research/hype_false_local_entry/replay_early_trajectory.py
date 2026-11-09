"""Progressive, first-signal replay of the fixed HYPE strict M1 trajectories."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

import numpy as np

from research.hype_false_local_entry import early_trajectory_features as features
from research.hype_false_local_entry import first_signal_objective as objective

MASTER_SHA256 = "c9d588b5c78d0e72a3073ceb62c7fa100381ebf69df911b22a170171a2653975"
PERIODS = (
    "01_JUL12_AUG07_FULL_MICRO", "02_AUG08_SEP01", "03_SEP01_OCT01", "04_OCT04_NOV03",
)
CONTROL = "retrace_band_only"


def file_sha(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def rule_hashes(config):
    sources = [Path(__file__), Path(features.__file__), Path(objective.__file__)]
    source_sha256 = {p.name: file_sha(p) for p in sources}
    common = {
        "contract": config["id"],
        "band": config["distance_band_bps"],
        "source_sha256": source_sha256,
    }
    hashes = {}
    for side in features.SIDES:
        hashes[side] = {}
        for family in (CONTROL, *config["families_in_order"]):
            payload = dict(common, side=side, family=family, params=config["by_side"][side])
            raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            hashes[side][family] = hashlib.sha256(raw).hexdigest()
    return hashes, source_sha256


def matches_rule(row, config, family):
    params = config["by_side"][row["side"]]
    lo, hi = config["distance_band_bps"]
    if row["age_s"] not in params["ages_s"] or not lo <= row["retrace_bps"] <= hi:
        return False
    if family == CONTROL:
        return True
    if row["retrace_range60"] < params["min_range_recovery"] or not math.isfinite(row["retrace_range60"]):
        return False
    if not row["late_slope_bps_min"] > 0:
        return False
    if family == "efficiency_handoff":
        return (
            row["efficiency_slope"] > 0
            and row["late_new_eff"] > row["late_old_eff"]
            and row["late_old_eff"] < row["pre_old_eff"]
        )
    if family == "old_side_absorption":
        return (
            row["old_side_failed_extension"]
            and row["positive_bar_share"] >= params["min_positive_bar_share"]
            and row["retained_close_retrace"] >= params["min_retained_close_retrace"]
        )
    raise ValueError(f"unknown hypothesis: {family}")


def market_signals(tape, config, active):
    """The rule has no reference label, phase, or episode identifiers."""
    accepted = {side: {name: [] for name in (CONTROL, *active[side])}
                for side in features.SIDES}
    seen = set()
    row_counts = Counter()
    for row in features.trajectories(tape):
        side = row["side"]
        if not active[side]:
            continue
        row_counts[side, row["age_s"]] += 1
        for family, signals in accepted[side].items():
            key = (family, row["candidate_id"])
            if key not in seen and matches_rule(row, config, family):
                signals.append(row)
                seen.add(key)
    return accepted, {side: {str(age): row_counts[side, age] for age in features.AGES_S}
                      for side in features.SIDES}


def scoring_scope(tape, labels):
    finalized = objective.finalized_labels(labels)
    episodes = objective.build_episodes(finalized[:-1])
    windows = [(features.ready_at(tape.start[i]), int(tape.end[j - 1]))
               for i, j in features.segments(tape)]
    eligible = {
        ep.ep for ep in episodes
        if any(start <= ep.start_ms and int(finalized[ep.ep + 1]["extreme_interval_start_ms"]) < end
               for start, end in windows)
    }
    return finalized, episodes, eligible


def distribution(values):
    if not values:
        return None
    return {"median": float(np.median(values)), "p90": float(np.quantile(values, 0.90)),
            "worst": max(values)}


def evaluate_side(tape, labels, side, signals, scope):
    finalized, episodes, eligible = scope
    target_by_minute = {
        (lab["side"], int(lab["extreme_interval_start_ms"])): lab for lab in finalized
    }
    by_id = {int(lab["label_id"]): lab for lab in finalized}
    details = {}
    tagged = []
    for row in signals:
        minute = row["candidate_ts_ms"] // features.MINUTE * features.MINUTE
        lab = target_by_minute.get((side, minute))
        true = bool(lab and math.isclose(row["price"], lab["extreme_price"],
                                         rel_tol=1e-10, abs_tol=1e-8))
        tagged.append(dict(row, accepted=True, terminal_true=true,
                           terminal_label_id=lab["label_id"] if true else None))
        details[row["candidate_id"], row["signal_ts_ms"]] = row

    first = objective.summarize_actionable_first_signals(
        tagged, labels, true_key="terminal_true", label_id_key="terminal_label_id",
    )
    records = []
    distances, latencies, continuations = [], [], []
    for item in first["first_signals"]:
        if item["episode"] not in eligible:
            continue
        row = details[item["candidate_id"], item["signal_ts_ms"]]
        target = by_id[item["target_label_id"]]
        terminal_price = float(target["extreme_price"])
        target_i = int(np.searchsorted(tape.start, target["extreme_interval_start_ms"]))
        terminal_ts = int((tape.low_ts if side == "LOW" else tape.high_ts)[target_i])
        record = dict(item, age_s=row["age_s"], candidate_price=row["price"],
                      signal_price=row["signal_price"], terminal_price=terminal_price,
                      terminal_ts_ms=terminal_ts, retrace_from_candidate_bps=row["retrace_bps"])
        if item["true_first"]:
            distance = abs(row["signal_price"] / terminal_price - 1) * 10_000
            latency = (row["signal_ts_ms"] - terminal_ts) / 1000
            distances.append(distance)
            latencies.append(latency)
            record.update(true_distance_bps=distance, true_latency_s=latency)
        else:
            sign = 1 if side == "LOW" else -1
            continuation = max(0.0, -sign * (terminal_price / row["price"] - 1) * 10_000)
            continuations.append(continuation)
            before_terminal = row["signal_ts_ms"] <= terminal_ts
            record.update(
                false_candidate_continuation_bps=continuation,
                false_signal_adverse_to_terminal_bps=(
                    max(0.0, -sign * (terminal_price / row["signal_price"] - 1) * 10_000)
                    if before_terminal else None
                ),
            )
        records.append(record)

    n = sum(ep.ep in eligible and ep.target_side == side for ep in episodes)
    tp = len(distances)
    m = {
        "episodes": n, "accepted_first": len(records), "true_first": tp,
        "false_first": len(records) - tp,
        "precision": tp / len(records) if records else None,
        "recall": tp / n if n else None,
        "coverage": len(records) / n if n else None,
        "true_distance_bps": distribution(distances),
        "true_latency_s": distribution(latencies),
        "false_candidate_continuation_bps": distribution(continuations),
        "first_signals": records,
    }
    m["paper_gate"] = objective.promotion_gate(dict(m, precision=m["precision"] or 0,
                                                   recall=m["recall"] or 0))
    return m


def gate(metrics, control, thresholds):
    m = metrics
    precision = m["precision"] or 0
    recall = m["recall"] or 0
    checks = {
        "episodes": m["episodes"] >= thresholds["episodes"],
        "true_first": m["true_first"] >= thresholds["true_first"],
        "precision": precision >= thresholds["precision"],
        "recall": recall >= thresholds["recall"],
        "precision_gain": control["precision"] is not None
        and precision - control["precision"] >= thresholds["precision_gain"],
    }
    return {"passed": all(checks.values()), "checks": checks}


def score_period(archive, period, config, active, hashes):
    with archive.open(f"{period}/compact_1m.jsonl.gz") as compressed:
        with gzip.open(compressed, "rt", encoding="utf-8") as stream:
            tape = features.tape_from_rows(map(json.loads, stream))
    signals, counts = market_signals(tape, config, active)
    with archive.open(f"{period}/labels.json.gz") as compressed:
        with gzip.open(compressed, "rt", encoding="utf-8") as stream:
            labels = json.load(stream)["strict"]
    scope = scoring_scope(tape, labels)
    finalized, episodes, eligible = scope
    results = {}
    survivors = {side: [] for side in features.SIDES}
    phase = "development" if period == PERIODS[0] else "chronological_transfer"
    for side in features.SIDES:
        side_result = {
            "strict_finalized_labels": sum(lab["side"] == side for lab in finalized),
            "actionable_episodes_before_tape_quality": sum(ep.target_side == side for ep in episodes),
            "excluded_tape_quality": [ep.target_label_id for ep in episodes
                                      if ep.target_side == side and ep.ep not in eligible],
            "candidate_rows_by_age_s": counts[side],
            "rules": {},
        }
        results[side] = side_result
        if not active[side]:
            continue
        for family, events in signals[side].items():
            m = evaluate_side(tape, labels, side, events, scope)
            m["rule_sha256"] = hashes[side][family]
            if family != CONTROL:
                threshold_key = "development_gate" if phase == "development" else "transfer_gate"
                m["screen"] = gate(m, side_result["rules"][CONTROL], config[threshold_key])
                if m["screen"]["passed"]:
                    survivors[side].append(family)
            side_result["rules"][family] = m
    return {"phase": phase, "period": period, "tape_rows": len(tape.start),
            "by_side": results, "survivors": survivors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--period", choices=PERIODS, required=True)
    parser.add_argument("--prior", type=Path, help="Immediately preceding period's result")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.rules.read_text())
    hashes, sources = rule_hashes(config)
    archive_hash = file_sha(args.master)
    if archive_hash != MASTER_SHA256:
        parser.error("historical master SHA-256 mismatch")
    period_index = PERIODS.index(args.period)
    if period_index:
        if args.prior is None:
            parser.error("transfer requires the preceding period's frozen result")
        prior = json.loads(args.prior.read_text())
        if (prior["period"] != PERIODS[period_index - 1] or prior["rule_hashes"] != hashes
                or prior["master_sha256"] != archive_hash or prior["config"] != config):
            parser.error("prior result differs in period, data, or frozen rules")
        active = prior["survivors"]
        if not any(active.values()):
            parser.error("no survivors eligible for chronological transfer")
    else:
        if args.prior is not None:
            parser.error("development must be the first score")
        active = {side: config["families_in_order"] for side in features.SIDES}
    with ZipFile(args.master) as archive:
        result = score_period(archive, args.period, config, active, hashes)
    result.update(config=config, rule_hashes=hashes, source_sha256=sources,
                  master_sha256=archive_hash, real_orders=False)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    for side, side_result in result["by_side"].items():
        for name, m in side_result["rules"].items():
            print(side, name, *(m[k] for k in ("episodes", "true_first", "false_first", "precision",
                                               "recall", "true_distance_bps")), m.get("screen", ""))


if __name__ == "__main__":
    main()
