from __future__ import annotations

import argparse
import gzip
import json
import math
import pickle
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from research.hype_full_micro_202607 import build_full_micro as base
from research.hype_full_micro_202607 import train_full_micro as frozen


DELAYS = (60, 180, 300)
LOOKBACK_MINUTES = 360


def dt(value: str) -> datetime:
    out = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if out.tzinfo is None:
        out = out.replace(tzinfo=timezone.utc)
    return out.astimezone(timezone.utc)


def causal_candidates(mins, start_ms: int, end_ms: int, lookback_minutes: int = LOOKBACK_MINUTES):
    """Create candidates using only information available at candidate time.

    A LOW candidate is a fresh low versus the preceding six completed hours.
    A HIGH candidate is the mirrored fresh high.  New same-side extremes
    immediately invalidate the previous candidate, matching live semantics.
    Strict labels are NOT used here.
    """
    out = []
    last_by_side = {}
    for i, row in enumerate(mins):
        st = int(row["start_ms"])
        if st < start_ms or st >= end_ms:
            continue
        prior = mins[max(0, i - lookback_minutes):i]
        if len(prior) < min(60, lookback_minutes):
            continue

        low = float(row["low"])
        high = float(row["high"])
        prior_low = min(float(x["low"]) for x in prior)
        prior_high = max(float(x["high"]) for x in prior)

        candidates = []
        if low < prior_low:
            candidates.append(("LOW", low, int(row.get("low_ts_ms", st))))
        if high > prior_high:
            candidates.append(("HIGH", high, int(row.get("high_ts_ms", st))))

        for side, px, ts in sorted(candidates, key=lambda z: z[2]):
            if ts < start_ms or ts >= end_ms:
                continue
            c = {
                "side": side,
                "extreme_price": px,
                "extreme_ts_ms": ts,
                "candidate_id": f"RECENT48-{side[0]}-{ts}",
                "invalidated_at_ms": None,
                "strict_true": False,
                "strict_label_id": None,
            }
            prev = last_by_side.get(side)
            if prev is not None and prev.get("invalidated_at_ms") is None:
                prev["invalidated_at_ms"] = ts
            last_by_side[side] = c
            out.append(c)
    return out


def annotate_truth(cands, labels):
    labs = [dict(x) for x in labels if bool(x.get("reference_finalized", True))]
    for c in cands:
        side = c["side"]
        ts = int(c["extreme_ts_ms"])
        px = float(c["extreme_price"])
        for lab in labs:
            if str(lab.get("side")) != side:
                continue
            left = int(lab["extreme_interval_start_ms"])
            right = int(lab.get("extreme_interval_end_ms", left))
            if left <= ts <= right and math.isclose(
                px, float(lab["extreme_price"]), rel_tol=1e-10, abs_tol=1e-8
            ):
                c["strict_true"] = True
                c["strict_label_id"] = int(lab["label_id"])
                break
    return cands


def candidate_records(cands, sec5, mins, end_ms: int):
    rows = []
    for c in cands:
        stop = min(
            end_ms,
            int(c["invalidated_at_ms"]) if c.get("invalidated_at_ms") is not None else end_ms,
        )
        for delay in DELAYS:
            t = int(c["extreme_ts_ms"]) + delay * 1000
            if t >= stop:
                break
            f = base.base_features(c, t, sec5, mins)
            rows.append(
                {
                    "symbol": "HYPE",
                    "candidate_id": c["candidate_id"],
                    "side": c["side"],
                    "candidate_ts_ms": int(c["extreme_ts_ms"]),
                    "snapshot_ts_ms": t,
                    "delay_s": delay,
                    "extreme_price": float(c["extreme_price"]),
                    "invalidated_at_ms": c.get("invalidated_at_ms"),
                    "strict_true": bool(c["strict_true"]),
                    "strict_label_id": c.get("strict_label_id"),
                    "features": f,
                }
            )
    return rows


def signal_price(row):
    f = row.get("features") or {}
    retr = float(f.get("retrace_bps", 0.0))
    cp = float(row["extreme_price"])
    return cp * (1.0 + retr / 10000.0) if row["side"] == "LOW" else cp * (1.0 - retr / 10000.0)


def score_frozen(rows, bundle, model_name="extra"):
    names = list(bundle["feature_names"])
    model = bundle["models"][model_name]
    threshold = float(bundle["report"]["models"][model_name]["threshold"])
    probs = model.predict_proba(frozen.matrix(rows, names))[:, 1] if rows else np.asarray([])
    scored = []
    for row, p in zip(rows, probs):
        z = dict(row)
        z["probability"] = float(p)
        z["threshold"] = threshold
        z["accepted"] = bool(float(p) >= threshold)
        z["signal_price"] = float(signal_price(row))
        scored.append(z)
    return scored, names, threshold


def first_by_candidate(scored):
    by = defaultdict(list)
    for row in scored:
        by[row["candidate_id"]].append(row)
    signals = []
    for cid, rows in by.items():
        accepted = [r for r in rows if r["accepted"]]
        if accepted:
            signals.append(min(accepted, key=lambda r: int(r["snapshot_ts_ms"])))
    return sorted(signals, key=lambda r: (int(r["snapshot_ts_ms"]), int(r["candidate_ts_ms"])))


def side_metrics(cands, signals, side):
    cs = [c for c in cands if c["side"] == side]
    ss = [s for s in signals if s["side"] == side]
    true_candidates = [c for c in cs if c["strict_true"]]
    tp = sum(bool(s["strict_true"]) for s in ss)
    fp = len(ss) - tp
    detected_ids = {int(s["strict_label_id"]) for s in ss if s.get("strict_label_id") is not None}
    true_ids = {int(c["strict_label_id"]) for c in true_candidates if c.get("strict_label_id") is not None}
    delays = [max(0.0, (int(s["snapshot_ts_ms"]) - int(s["candidate_ts_ms"])) / 1000.0)
              for s in ss if s["strict_true"]]
    dists = []
    for s in ss:
        if not s["strict_true"]:
            continue
        cp = float(s["extreme_price"])
        sp = float(s["signal_price"])
        d = (sp / cp - 1.0) * 10000.0 if side == "LOW" else (cp / sp - 1.0) * 10000.0
        dists.append(max(0.0, d))
    return {
        "candidates": len(cs),
        "true_candidates": len(true_candidates),
        "accepted": len(ss),
        "tp": tp,
        "fp": fp,
        "precision": tp / len(ss) if ss else None,
        "recall": len(detected_ids) / len(true_ids) if true_ids else None,
        "median_delay_s": float(np.median(delays)) if delays else None,
        "median_entry_distance_bps": float(np.median(dists)) if dists else None,
    }


def bars_between(sec5, start_ms, end_ms):
    return [b for b in sec5 if int(b.get("start_ms", 0)) >= start_ms and int(b.get("start_ms", 0)) < end_ms]


def trade_stats(side, entry, exit_px, bars):
    if side == "LOW":
        ret = (exit_px / entry - 1.0) * 100.0
        mfe = (max([float(b["high"]) for b in bars], default=entry) / entry - 1.0) * 100.0
        mae = (min([float(b["low"]) for b in bars], default=entry) / entry - 1.0) * 100.0
        direction = "LONG"
    else:
        ret = (entry / exit_px - 1.0) * 100.0
        mfe = (entry / min([float(b["low"]) for b in bars], default=entry) - 1.0) * 100.0
        mae = (entry / max([float(b["high"]) for b in bars], default=entry) - 1.0) * 100.0
        direction = "SHORT"
    return direction, ret, mfe, mae


def alternating_trade_path(signals, sec5, end_ms):
    if not signals:
        return []
    trades = []
    active = None
    for sig in signals:
        if active is None:
            active = sig
            continue
        if sig["side"] == active["side"]:
            continue
        st = int(active["snapshot_ts_ms"])
        en = int(sig["snapshot_ts_ms"])
        entry = float(active["signal_price"])
        exit_px = float(sig["signal_price"])
        direction, ret, mfe, mae = trade_stats(active["side"], entry, exit_px, bars_between(sec5, st, en))
        trades.append({
            "direction": direction,
            "entry_ts_ms": st,
            "entry_price": entry,
            "entry_probability": float(active["probability"]),
            "entry_true_local": bool(active["strict_true"]),
            "exit_ts_ms": en,
            "exit_price": exit_px,
            "exit_probability": float(sig["probability"]),
            "exit_true_local": bool(sig["strict_true"]),
            "price_return_pct": ret,
            "mfe_pct": mfe,
            "mae_pct": mae,
            "closed_by": "OPPOSITE_MODEL_SIGNAL",
        })
        active = sig

    if active is not None:
        candidates = [b for b in sec5 if int(b.get("start_ms", 0)) < end_ms]
        if candidates:
            last = candidates[-1]
            exit_px = float(last["close"])
            st = int(active["snapshot_ts_ms"])
            direction, ret, mfe, mae = trade_stats(active["side"], float(active["signal_price"]), exit_px, bars_between(sec5, st, end_ms))
            trades.append({
                "direction": direction,
                "entry_ts_ms": st,
                "entry_price": float(active["signal_price"]),
                "entry_probability": float(active["probability"]),
                "entry_true_local": bool(active["strict_true"]),
                "exit_ts_ms": end_ms,
                "exit_price": exit_px,
                "exit_probability": None,
                "exit_true_local": None,
                "price_return_pct": ret,
                "mfe_pct": mfe,
                "mae_pct": mae,
                "closed_by": "WINDOW_END",
            })
    return trades


def largest_high_to_low_leg(labels, signals):
    labs = [dict(x) for x in labels if bool(x.get("reference_finalized", True))]
    labs.sort(key=lambda x: int(x["extreme_interval_start_ms"]))
    best = None
    for a, b in zip(labs, labs[1:]):
        if a["side"] != "HIGH" or b["side"] != "LOW":
            continue
        hp, lp = float(a["extreme_price"]), float(b["extreme_price"])
        drop = (hp / lp - 1.0) * 100.0
        row = {
            "high_label_id": int(a["label_id"]),
            "high_ts_ms": int(a["extreme_interval_start_ms"]),
            "high_price": hp,
            "low_label_id": int(b["label_id"]),
            "low_ts_ms": int(b["extreme_interval_start_ms"]),
            "low_price": lp,
            "oracle_drop_pct": drop,
        }
        hs = [s for s in signals if s.get("strict_label_id") == int(a["label_id"])]
        ls = [s for s in signals if s.get("strict_label_id") == int(b["label_id"])]
        if hs:
            x = min(hs, key=lambda z: int(z["snapshot_ts_ms"]))
            row["high_detection"] = {
                "signal_ts_ms": int(x["snapshot_ts_ms"]),
                "signal_price": float(x["signal_price"]),
                "delay_s": (int(x["snapshot_ts_ms"]) - int(x["candidate_ts_ms"])) / 1000.0,
                "probability": float(x["probability"]),
            }
        if ls:
            x = min(ls, key=lambda z: int(z["snapshot_ts_ms"]))
            row["low_detection"] = {
                "signal_ts_ms": int(x["snapshot_ts_ms"]),
                "signal_price": float(x["signal_price"]),
                "delay_s": (int(x["snapshot_ts_ms"]) - int(x["candidate_ts_ms"])) / 1000.0,
                "probability": float(x["probability"]),
            }
        if hs and ls:
            ep = float(row["high_detection"]["signal_price"])
            xp = float(row["low_detection"]["signal_price"])
            cap = (ep / xp - 1.0) * 100.0
            row["captured_short_pct"] = cap
            row["captured_fraction_of_oracle"] = cap / drop if drop > 0 else None
        if best is None or drop > best["oracle_drop_pct"]:
            best = row
    return best


def jsonable_signal(row):
    return {
        "candidate_id": row["candidate_id"],
        "side": row["side"],
        "candidate_ts_ms": int(row["candidate_ts_ms"]),
        "signal_ts_ms": int(row["snapshot_ts_ms"]),
        "delay_s": int(row["delay_s"]),
        "extreme_price": float(row["extreme_price"]),
        "signal_price": float(row["signal_price"]),
        "probability": float(row["probability"]),
        "threshold": float(row["threshold"]),
        "strict_true": bool(row["strict_true"]),
        "strict_label_id": row.get("strict_label_id"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--model", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.cache.mkdir(parents=True, exist_ok=True)

    start = dt(args.start)
    end = dt(args.end)
    if end <= start:
        raise ValueError("end must be after start")
    start_ms, end_ms = base.ms(start), base.ms(end)

    # Reuse the audited source/replay implementation but change only the replay window.
    base.START = start
    base.END = end
    src = base.Source(args.cache, None if not __import__("os").getenv("CRYPTOHFTDATA_API_KEY") else __import__("os").getenv("CRYPTOHFTDATA_API_KEY"))

    # Fast path: trades need 24h warm-up for the 24h causal state.\n    workers=max(8, int(__import__("os").getenv("HYPE_DOWNLOAD_WORKERS", "32")))\n    base.prefetch_hours(src, start - timedelta(hours=24), end, ("trades",), workers=workers)
    sec5, mins, schemas = base.load_trades(src)
    if not mins:
        raise RuntimeError("no HYPE trade history downloaded")

    strict, strict_exc = base.structural_labels(mins, lookback=6, lookahead=2)
    cands = causal_candidates(mins, start_ms, end_ms)
    annotate_truth(cands, strict)
    records = candidate_records(cands, sec5, mins, end_ms)
    if not records:
        raise RuntimeError("no causal candidate snapshots in replay window")

    # Rich causal state. Prefetch all non-trade streams in one concurrent batch.
    # Only one hour of pre-window state is required for book/scalar carry; the
    # 24h structural warm-up is already supplied by trades above.
    base.prefetch_hours(
        src,
        start - timedelta(hours=1),
        end,
        ("orderbook", "liquidations", "open_interest", "mark_price", "ticker"),
        workers=workers,
    )

    ratio_rows = base.fetch_account_ratio()
    records = base.attach_account_ratio(records, ratio_rows)
    records = base.enrich(src, records, schemas)

    with args.model.open("rb") as fh:
        bundle = pickle.load(fh)
    scored, feature_names, threshold = score_frozen(records, bundle, "extra")
    signals = first_by_candidate(scored)

    by_side = {s: side_metrics(cands, signals, s) for s in ("LOW", "HIGH")}
    trades = alternating_trade_path(signals, sec5, end_ms)
    completed = [t for t in trades if t["closed_by"] == "OPPOSITE_MODEL_SIGNAL"]
    raw_compound = 1.0
    for t in completed:
        raw_compound *= 1.0 + float(t["price_return_pct"]) / 100.0

    strict_in_window = [
        x for x in strict
        if start_ms <= int(x["extreme_interval_start_ms"]) < end_ms
        and bool(x.get("reference_finalized", True))
    ]
    largest_drop = largest_high_to_low_leg(strict_in_window, signals)

    report = {
        "version": "HYPE-RECENT48-FROZEN-JULAUG-CAUSAL-REPLAY-v1",
        "research_only": True,
        "real_orders": False,
        "window_utc": [start.isoformat(), end.isoformat()],
        "window_hours": (end - start).total_seconds() / 3600.0,
        "data": {
            "source": "CryptoHFTData Bybit hourly Parquet/Zstd + Bybit account-ratio REST when available",
            "downloaded_files": int(src.downloads),
            "downloaded_bytes": int(src.bytes),
            "source_file_counts": dict(src.counts),
            "missing_files_count": len(src.missing),
            "account_ratio_rows": len(ratio_rows),
            "minute_rows": len([r for r in mins if start_ms <= int(r["start_ms"]) < end_ms]),
            "sec5_rows": len([r for r in sec5 if start_ms <= int(r["start_ms"]) < end_ms]),
        },
        "leakage_contract": {
            "candidate_generation": "causal rolling 6h fresh extreme; no strict labels",
            "features": "only values timestamped at or before snapshot_ts_ms",
            "frozen_model_source": "Jul12-Aug07 model artifact run 42376949791",
            "model_refit_on_recent_48h": False,
            "threshold_retuned_on_recent_48h": False,
            "teacher_use": "after-the-fact scoring only",
            "decision_delays_s": list(DELAYS),
        },
        "frozen_model": {
            "version": bundle.get("report", {}).get("version"),
            "model": "extra",
            "threshold": threshold,
            "feature_count": len(feature_names),
            "historical_report": bundle.get("report"),
        },
        "strict_teacher_after_fact": {
            "labels_in_window": len(strict_in_window),
            "low": sum(x["side"] == "LOW" for x in strict_in_window),
            "high": sum(x["side"] == "HIGH" for x in strict_in_window),
            "labels": strict_in_window,
            "exclusions": strict_exc,
        },
        "candidate_replay": {
            "candidates": len(cands),
            "snapshots": len(records),
            "accepted_candidate_signals": len(signals),
            "by_side": by_side,
            "signals": [jsonable_signal(x) for x in signals],
        },
        "largest_high_to_low_leg": largest_drop,
        "paper_trade_path": {
            "alternating_model_signals_only": True,
            "same_side_repeat_signals_ignored_while_position_open": True,
            "trades": trades,
            "completed_trades": len(completed),
            "raw_1x_compound_return_pct": (raw_compound - 1.0) * 100.0 if completed else None,
            "fees_funding_slippage": "not included",
            "leverage": "not applied; inspect MAE before considering leveraged scenarios",
        },
    }

    out = args.output / "RECENT_48H_FROZEN_REPLAY.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    with gzip.open(args.output / "RECENT_48H_CAUSAL_SCORED.jsonl.gz", "wt", encoding="utf-8", compresslevel=9) as fh:
        for r in scored:
            z = dict(r)
            z["features"] = r.get("features") or {}
            fh.write(json.dumps(z, separators=(",", ":"), allow_nan=False) + "\n")

    base.write_jsonl_gz(
        args.output / "RECENT_48H_COMPACT_1M.jsonl.gz",
        [r for r in mins if start_ms <= int(r["start_ms"]) < end_ms],
    )

    print("RECENT48_RESULT=" + json.dumps({
        "window": report["window_utc"],
        "strict_labels": report["strict_teacher_after_fact"]["labels_in_window"],
        "signals": len(signals),
        "by_side": by_side,
        "largest_drop": largest_drop,
        "trades": trades,
        "raw_1x_compound_return_pct": report["paper_trade_path"]["raw_1x_compound_return_pct"],
        "source_file_counts": dict(src.counts),
        "missing_files_count": len(src.missing),
    }, separators=(",", ":"), ensure_ascii=False))


if __name__ == "__main__":
    main()
