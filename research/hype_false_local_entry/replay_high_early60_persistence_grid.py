#!/usr/bin/env python3
"""HIGH-only EARLY60 persistence grid over four HYPE historical regimes.

Research/paper only. LOW and the frozen HARD120 primary are unchanged.
The experiment asks whether a HIGH candidate can be accepted at +60m when:
- it is a surviving 6h trailing HIGH;
- EARLY60 base evidence is strong (retrace >=80 bps, retrace/pre-move >=0.60,
  first-15m seller-dominated flow >=0.20, >=100 trades);
- seller pressure is still present in the final 15m before +60m;
- optionally the +60m retrace still retains enough of the maximum reversal
  excursion observed since the candidate.

If the early rule does not fire, the current frozen HARD120 + HIGH Flow V2
stack remains the fallback. Labels are used only after signal generation.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from research.hype_false_local_entry.replay_hard120_30d import (
    read_jsonl_gz, read_json_gz, generate_candidates, pre_move_180_bps, more_extreme,
)
from research.hype_false_local_entry.replay_hard120_plus_high_flow import (
    raw_checkpoint, flow15,
)
from research.hype_false_local_entry.high_flow_shadow_v2 import (
    qualifies as high_flow_v2_qualifies,
)
from research.hype_local_v5.labels import structural_labels

EARLY_AGE_MS = 60 * 60_000
EARLY_MIN_RETRACE_BPS = 80.0
EARLY_MIN_FRACTION = 0.60
EARLY_MIN_REV_FLOW_FIRST15 = 0.20
EARLY_MIN_TRADE_COUNT_FIRST15 = 100

LAST15_THRESHOLDS = (-0.10, 0.00, 0.05, 0.10, 0.15, 0.20)
PERSISTENCE_THRESHOLDS = (0.00, 0.50, 0.60, 0.70, 0.80)


def _window_flow(rows: list[dict[str, Any]]) -> tuple[float | None, int]:
    buy = sum(float(r.get("buy_notional") or 0.0) for r in rows)
    sell = sum(float(r.get("sell_notional") or 0.0) for r in rows)
    trades = sum(int(r.get("trade_count") or 0) for r in rows)
    den = buy + sell
    if den <= 0:
        return None, trades
    return (buy - sell) / den, trades


def _sample60(candidate: dict[str, Any], end_ms: int, bars: list[dict[str, Any]]) -> dict[str, Any] | None:
    target = int(candidate["extreme_ts_ms"]) + EARLY_AGE_MS
    sample = None
    for r in bars:
        e = int(r["bar_end_ms"])
        if e < target or e >= int(end_ms):
            continue
        close = float(r["close"])
        if close <= 0:
            continue
        if sample is None or e < sample["signal_ts_ms"]:
            sample = {"signal_ts_ms": e, "mark_price": close, "bar_start_ms": int(r["start_ms"])}
    return sample


def _early_metrics(candidate: dict[str, Any], end_ms: int, bars: list[dict[str, Any]],
                   starts: dict[int, int]) -> dict[str, Any] | None:
    if str(candidate["side"]) != "HIGH":
        return None
    sample = _sample60(candidate, end_ms, bars)
    if sample is None:
        return None
    idx = starts.get(int(candidate["bar_start_ms"]))
    sidx = starts.get(int(sample["bar_start_ms"]))
    if idx is None or sidx is None or sidx <= idx:
        return None

    first = bars[idx + 1: idx + 16]
    if len(first) != 15:
        return None
    expected = int(bars[idx]["bar_end_ms"])
    for r in first:
        if int(r["start_ms"]) != expected or bool(r.get("gap", False)):
            return None
        expected = int(r["bar_end_ms"])

    path = bars[idx + 1: sidx + 1]
    if not path:
        return None
    last = path[-15:] if len(path) >= 15 else path
    first_raw, first_trades = _window_flow(first)
    last_raw, last_trades = _window_flow(last)
    if first_raw is None or last_raw is None:
        return None

    p = float(candidate["extreme_price"])
    mark = float(sample["mark_price"])
    retrace_bps = (p / mark - 1.0) * 10_000.0 if p > 0 and mark > 0 else 0.0
    pre = max(0.0, float(candidate["pre_move_180_bps"]))
    frac = retrace_bps / pre if pre > 0 else 0.0

    min_low = min(float(r["low"]) for r in path)
    max_reversal_bps = max(0.0, (p / min_low - 1.0) * 10_000.0) if min_low > 0 else 0.0
    persistence = retrace_bps / max(max_reversal_bps, 1e-12)
    persistence = max(0.0, min(1.0, persistence))

    return {
        **sample,
        "retrace_bps": retrace_bps,
        "retrace_fraction_pre_180": frac,
        "first15_raw_flow": float(first_raw),
        "first15_reversal_flow": float(-first_raw),
        "first15_trade_count": int(first_trades),
        "last15_raw_flow": float(last_raw),
        "last15_reversal_flow": float(-last_raw),
        "last15_trade_count": int(last_trades),
        "max_reversal_bps": max_reversal_bps,
        "reversal_persistence": persistence,
    }


def _early_qualifies(m: dict[str, Any], last15_min: float, persistence_min: float) -> bool:
    return bool(
        float(m["retrace_bps"]) >= EARLY_MIN_RETRACE_BPS
        and float(m["retrace_fraction_pre_180"]) >= EARLY_MIN_FRACTION
        and float(m["first15_reversal_flow"]) >= EARLY_MIN_REV_FLOW_FIRST15
        and int(m["first15_trade_count"]) >= EARLY_MIN_TRADE_COUNT_FIRST15
        and float(m["last15_reversal_flow"]) >= float(last15_min)
        and float(m["reversal_persistence"]) >= float(persistence_min)
    )


def _hard_decision(candidate: dict[str, Any], cp: dict[str, Any],
                   bars: list[dict[str, Any]], starts: dict[int, int]) -> tuple[str | None, dict[str, Any] | None]:
    retr = float(cp["retrace_bps"])
    frac = float(cp["retrace_fraction_pre_180"])
    if retr >= 40.0 and frac >= 0.45:
        return "PRIMARY", None
    if str(candidate["side"]) != "HIGH":
        return None, None
    f = flow15(candidate, bars, starts)
    if f is None:
        return None, None
    ok, detail = high_flow_v2_qualifies(
        side="HIGH",
        primary_emitted=False,
        expected_side_ok=True,
        checkpoint_fresh=True,
        retrace_bps=retr,
        retrace_fraction_pre_180=frac,
        flow_15=float(f["flow_15"]),
        trade_count=int(f["trade_count"]),
    )
    return ("HIGH_FLOW_V2", {**f, "detail": detail}) if ok else (None, f)


def replay(compact: Path, labels_gz: Path, *, derive_internal: bool,
           last15_min: float, persistence_min: float) -> dict[str, Any]:
    bars = read_jsonl_gz(compact)
    starts = {int(b["start_ms"]): i for i, b in enumerate(bars)}
    candidates = []
    for e in generate_candidates(bars):
        if 360 not in e["lookbacks_m"]:
            continue
        idx = starts[e["bar_start_ms"]]
        pm = pre_move_180_bps(e["side"], float(e["extreme_price"]), idx, bars)
        if pm <= 0:
            continue
        z = dict(e)
        z["pre_move_180_bps"] = pm
        candidates.append(z)

    doc = read_json_gz(labels_gz)
    internal = doc.get("internal") or []
    source = "artifact_internal"
    if not internal and derive_internal:
        internal, _ = structural_labels(bars, lookback=3, lookahead=1)
        source = "derived_from_compact_m1_L3_K1"
    labels = sorted(
        (dict(x) for x in internal if bool(x.get("reference_finalized"))),
        key=lambda x: int(x["extreme_interval_start_ms"]),
    )

    rows = []
    for j in range(1, len(labels) - 1):
        prev, target, nxt = labels[j - 1], labels[j], labels[j + 1]
        if str(target["side"]) != "HIGH":
            continue
        start = int(prev["extreme_interval_start_ms"])
        target_end = int(target["extreme_interval_end_ms"])
        deadline = int(nxt["extreme_interval_start_ms"])
        evs = sorted(
            (
                e for e in candidates
                if e["side"] == "HIGH" and start < int(e["extreme_ts_ms"]) <= target_end
            ),
            key=lambda e: (int(e["extreme_ts_ms"]), int(e["signal_ts_ms"])),
        )

        current = None
        signals = []

        def evaluate(cand: dict[str, Any] | None, end_ms: int) -> None:
            if cand is None:
                return
            em = _early_metrics(cand, end_ms, bars, starts)
            if em is not None and _early_qualifies(em, last15_min, persistence_min):
                signals.append((int(em["signal_ts_ms"]), cand, em, "EARLY60_PERSIST", None))

            cp = raw_checkpoint(cand, end_ms, bars)
            if cp is None:
                return
            kind, flow = _hard_decision(cand, cp, bars, starts)
            if kind:
                signals.append((int(cp["signal_ts_ms"]), cand, cp, kind, flow))

        for e in evs:
            if current is None:
                current = e
                continue
            if not more_extreme("HIGH", float(e["extreme_price"]), float(current["extreme_price"])):
                continue
            evaluate(current, int(e["extreme_ts_ms"]))
            current = e
        evaluate(current, deadline)

        if not signals:
            rows.append({"episode": j, "accepted": False})
            continue

        signals.sort(key=lambda z: (z[0], 0 if z[3] == "EARLY60_PERSIST" else 1))
        _, cand, sig, kind, flow = signals[0]
        true = (
            int(target["extreme_interval_start_ms"])
            <= int(cand["extreme_ts_ms"])
            <= int(target["extreme_interval_end_ms"])
        )

        row = {
            "episode": j,
            "accepted": True,
            "true_first": bool(true),
            "kind": kind,
            "candidate_ts_ms": int(cand["extreme_ts_ms"]),
            "signal_ts_ms": int(sig["signal_ts_ms"]),
            "retrace_bps": float(sig["retrace_bps"]),
            "retrace_fraction_pre_180": float(sig["retrace_fraction_pre_180"]),
        }
        if kind == "EARLY60_PERSIST":
            row.update({
                "first15_reversal_flow": float(sig["first15_reversal_flow"]),
                "last15_reversal_flow": float(sig["last15_reversal_flow"]),
                "reversal_persistence": float(sig["reversal_persistence"]),
            })
        if true:
            target_price = float(target["extreme_price"])
            mark = float(sig["mark_price"])
            row["entry_distance_pct"] = abs(mark / target_price - 1.0) * 100.0
        rows.append(row)

    accepted = [x for x in rows if x.get("accepted")]
    tp = sum(bool(x.get("true_first")) for x in accepted)
    fp = len(accepted) - tp
    true_rows = [x for x in accepted if x.get("true_first")]
    early = [x for x in accepted if x.get("kind") == "EARLY60_PERSIST"]
    return {
        "label_source": source,
        "episodes": len(rows),
        "accepted_first": len(accepted),
        "true_first": tp,
        "false_first": fp,
        "precision": tp / len(accepted) if accepted else 0.0,
        "recall": tp / len(rows) if rows else 0.0,
        "median_entry_distance_pct": (
            statistics.median(float(x["entry_distance_pct"]) for x in true_rows)
            if true_rows else None
        ),
        "early_signals": len(early),
        "early_true": sum(bool(x.get("true_first")) for x in early),
        "early_false": sum(not bool(x.get("true_first")) for x in early),
        "early_median_distance_pct": (
            statistics.median(float(x["entry_distance_pct"]) for x in early if x.get("true_first"))
            if any(x.get("true_first") for x in early) else None
        ),
        "episode_rows": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", action="append", nargs=4, metavar=("NAME", "COMPACT", "LABELS", "DERIVE"))
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if not args.period:
        raise SystemExit("at least one --period NAME COMPACT LABELS DERIVE is required")

    periods = []
    for name, compact, labels, derive in args.period:
        periods.append((name, Path(compact), Path(labels), derive.lower() in {"1", "true", "yes"}))

    grid = []
    for last15_min in LAST15_THRESHOLDS:
        for persistence_min in PERSISTENCE_THRESHOLDS:
            by_period = {}
            for name, compact, labels, derive in periods:
                by_period[name] = replay(
                    compact,
                    labels,
                    derive_internal=derive,
                    last15_min=last15_min,
                    persistence_min=persistence_min,
                )
            min_precision = min(v["precision"] for v in by_period.values())
            min_recall = min(v["recall"] for v in by_period.values())
            early_true = sum(v["early_true"] for v in by_period.values())
            early_false = sum(v["early_false"] for v in by_period.values())
            weighted_tp = sum(v["true_first"] for v in by_period.values())
            weighted_fp = sum(v["false_first"] for v in by_period.values())
            pooled_precision = weighted_tp / max(1, weighted_tp + weighted_fp)
            distance_values = [
                v["median_entry_distance_pct"]
                for v in by_period.values()
                if v["median_entry_distance_pct"] is not None
            ]
            grid.append({
                "last15_min_reversal_flow": last15_min,
                "min_reversal_persistence": persistence_min,
                "min_period_precision": min_precision,
                "min_period_recall": min_recall,
                "pooled_precision": pooled_precision,
                "early_true": early_true,
                "early_false": early_false,
                "mean_period_median_distance_pct": (
                    statistics.mean(distance_values) if distance_values else None
                ),
                "by_period": {
                    k: {x: y for x, y in v.items() if x != "episode_rows"}
                    for k, v in by_period.items()
                },
            })

    eligible = [
        x for x in grid
        if x["min_period_precision"] >= 0.80
        and x["min_period_recall"] >= 0.40
        and x["early_true"] > 0
    ]
    eligible.sort(
        key=lambda x: (
            x["mean_period_median_distance_pct"] if x["mean_period_median_distance_pct"] is not None else 999.0,
            -x["early_true"],
            x["early_false"],
            -x["pooled_precision"],
        )
    )
    preferred = eligible[0] if eligible else None

    out = {
        "title": "HYPE HIGH EARLY60 persistence four-period development grid",
        "mode": "RESEARCH_PAPER_ONLY",
        "real_orders": False,
        "low_logic_changed": False,
        "hard120_primary_changed": False,
        "base_early60": {
            "age_minutes": 60,
            "min_retrace_bps": EARLY_MIN_RETRACE_BPS,
            "min_retrace_fraction_pre_180": EARLY_MIN_FRACTION,
            "min_first15_reversal_flow": EARLY_MIN_REV_FLOW_FIRST15,
            "min_first15_trade_count": EARLY_MIN_TRADE_COUNT_FIRST15,
        },
        "selection_warning": "All four historical regimes are now development data. Any preferred rule requires new terminal-forward validation.",
        "preferred": preferred,
        "grid": grid,
    }
    args.output.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("HIGH_EARLY60_PERSISTENCE=" + json.dumps({
        "preferred": preferred,
        "eligible_count": len(eligible),
    }, separators=(",", ":"), ensure_ascii=False))


if __name__ == "__main__":
    main()
