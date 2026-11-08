from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd


def load_jsonl_gz(path: Path):
    with gzip.open(path, "rt") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_inputs(base_dir: Path, gap_dir: Path):
    candidates = load_jsonl_gz(gap_dir / "candidate_snapshots_enriched.jsonl.gz")
    minute = load_jsonl_gz(base_dir / "compact_1m.jsonl.gz")
    with gzip.open(base_dir / "labels.json.gz", "rt") as f:
        labels = json.load(f)
    strict = sorted(
        [x for x in labels["strict"] if x.get("reference_finalized")],
        key=lambda x: x["extreme_interval_start_ms"],
    )
    return candidates, pd.DataFrame(minute).sort_values("ts_ms").reset_index(drop=True), strict


def add_indicators(mdf: pd.DataFrame) -> pd.DataFrame:
    x = mdf.copy()
    x["ema12"] = x.close.ewm(span=12, adjust=False).mean()
    x["ema26"] = x.close.ewm(span=26, adjust=False).mean()
    x["macd"] = x.ema12 - x.ema26
    x["macd_signal"] = x.macd.ewm(span=9, adjust=False).mean()
    x["macd_hist_bps"] = (x.macd - x.macd_signal) / x.close * 10000
    buy3 = x.buy_notional.rolling(3).sum()
    sell3 = x.sell_notional.rolling(3).sum()
    x["flow3m"] = (buy3 - sell3) / (buy3 + sell3)
    for win, name in ((60, "60m"), (360, "6h")):
        lo = x.low.rolling(win, min_periods=1).min()
        hi = x.high.rolling(win, min_periods=1).max()
        x[f"pos_{name}"] = (x.close - lo) / (hi - lo).replace(0, np.nan)
    return x


def build_episodes(strict):
    episodes = []
    by_side = defaultdict(list)
    for i in range(len(strict) - 1):
        a, b = strict[i], strict[i + 1]
        e = dict(ep=i + 1, prev=a, target=b)
        episodes.append(e)
        by_side[b["side"]].append(e)
    return episodes, by_side


def assign_episode(ts_ms: int, side: str, by_side):
    for e in by_side[side]:
        a, b = e["prev"], e["target"]
        if a["extreme_interval_start_ms"] < ts_ms <= b["extreme_interval_end_ms"]:
            return e
    return None


def checkpoint_rows(minutes, delay0, mdf, mts, by_side, final_ids):
    rows = []
    for r in delay0:
        e = assign_episode(r["candidate_ts_ms"], r["side"], by_side)
        if not e:
            continue
        a = e["prev"]
        target_ms = r["candidate_ts_ms"] + minutes * 60 * 1000
        idx = np.searchsorted(mts, target_ms, side="right") - 1
        start = np.searchsorted(mts, r["candidate_ts_ms"], side="left")
        if idx < start or idx < 0:
            continue
        seg = mdf.iloc[start : idx + 1]
        if r["side"] == "LOW":
            survived = float(seg.low.min()) >= r["extreme_price"] - 1e-9
            retr = max(0.0, float(mdf.iloc[idx].close) / r["extreme_price"] - 1.0)
            edge60 = float(mdf.iloc[idx].pos_60m)
            edge6 = float(mdf.iloc[idx].pos_6h)
            macd = float(mdf.iloc[idx].macd_hist_bps)
            flow = float(mdf.iloc[idx].flow3m)
        else:
            survived = float(seg.high.max()) <= r["extreme_price"] + 1e-9
            retr = max(0.0, 1.0 - float(mdf.iloc[idx].close) / r["extreme_price"])
            edge60 = 1.0 - float(mdf.iloc[idx].pos_60m)
            edge6 = 1.0 - float(mdf.iloc[idx].pos_6h)
            macd = -float(mdf.iloc[idx].macd_hist_bps)
            flow = -float(mdf.iloc[idx].flow3m)
        swing = abs(r["extreme_price"] / a["extreme_price"] - 1.0)
        atr = r["features"].get("atr_h1_frac", 0.0) or 0.0
        rows.append(
            dict(
                ep=e["ep"],
                cid=r["candidate_id"],
                snap=target_ms,
                true=bool(r.get("strict_true") and r.get("strict_label_id") in final_ids),
                survived=survived,
                retrace=(retr / swing if swing else 0.0),
                retrace_bps=retr * 10000,
                edge60=edge60,
                edge6=edge6,
                macd=macd,
                flow=flow,
                maturity=(swing / atr if atr else 0.0),
            )
        )
    return pd.DataFrame(rows)


def first_signal_metrics(df: pd.DataFrame, mask: pd.Series):
    d = df.loc[mask].sort_values(["ep", "snap"])
    first = d.groupby("ep", as_index=False).first() if len(d) else d
    accepted = len(first)
    tp = int(first.true.sum()) if accepted else 0
    return dict(
        accepted=accepted,
        true_first=tp,
        false_first=accepted - tp,
        precision=(tp / accepted if accepted else 0.0),
        recall=(tp / 75.0),
    ), first


def quarter_metrics(first: pd.DataFrame):
    out = []
    for lo, hi in ((1, 19), (20, 38), (39, 56), (57, 75)):
        x = first[(first.ep >= lo) & (first.ep <= hi)]
        n = len(x)
        tp = int(x.true.sum()) if n else 0
        out.append(
            dict(
                episodes=f"{lo}-{hi}",
                accepted=n,
                true_first=tp,
                false_first=n - tp,
                precision=(tp / n if n else None),
                recall=tp / (hi - lo + 1),
            )
        )
    return out


def true_local_capture(minutes: int, strict, delay0, mdf, mts):
    by_label = {
        r.get("strict_label_id"): r
        for r in delay0
        if r.get("strict_true") and r.get("strict_label_id") is not None
    }
    vals = []
    for i, lab in enumerate(strict[:-1]):
        r = by_label.get(lab["label_id"])
        if not r:
            continue
        nxt = strict[i + 1]
        t = r["candidate_ts_ms"] + minutes * 60 * 1000
        idx = np.searchsorted(mts, t, side="right") - 1
        if idx < 0:
            continue
        p = float(mdf.iloc[idx].close)
        full = abs(nxt["extreme_price"] / lab["extreme_price"] - 1.0)
        if lab["side"] == "LOW":
            dist = max(0.0, p / lab["extreme_price"] - 1.0)
            remaining = max(0.0, nxt["extreme_price"] / p - 1.0)
        else:
            dist = max(0.0, 1.0 - p / lab["extreme_price"])
            remaining = max(0.0, 1.0 - nxt["extreme_price"] / p)
        vals.append((dist, remaining / full if full else np.nan, full))
    a = np.asarray(vals, dtype=float)
    return dict(
        n=len(a),
        median_entry_distance_pct=float(np.nanmedian(a[:, 0]) * 100),
        median_remaining_swing_fraction=float(np.nanmedian(a[:, 1])),
        median_full_swing_pct=float(np.nanmedian(a[:, 2]) * 100),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-dir", required=True)
    ap.add_argument("--gap-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    candidates, mdf, strict = load_inputs(Path(args.base_dir), Path(args.gap_dir))
    mdf = add_indicators(mdf)
    mts = mdf.ts_ms.to_numpy()
    final_ids = {x["label_id"] for x in strict}
    _, by_side = build_episodes(strict)
    delay0 = [r for r in candidates if r["delay_s"] == 0]

    c10 = checkpoint_rows(10, delay0, mdf, mts, by_side, final_ids)
    c30 = checkpoint_rows(30, delay0, mdf, mts, by_side, final_ids)
    c60 = checkpoint_rows(60, delay0, mdf, mts, by_side, final_ids)

    false10 = c10[c10.survived & ~c10.true]
    true10 = c10[c10.survived & c10.true]

    confirmed30 = (
        c30.survived
        & (c30.maturity >= 3.0)
        & (c30.retrace >= 0.12)
        & (c30.edge60 >= 0.30)
        & (c30.edge6 >= 0.20)
        & (c30.macd >= -1.0)
        & (c30.flow >= -0.10)
    )
    m30, f30 = first_signal_metrics(c30, confirmed30)

    hard60 = (
        c60.survived
        & (c60.maturity >= 3.5)
        & (c60.retrace >= 0.15)
        & (c60.edge60 >= 0.20)
        & (c60.edge6 >= 0.12)
        & (c60.macd >= -3.0)
        & (c60.flow >= 0.10)
    )
    m60, f60 = first_signal_metrics(c60, hard60)

    ultra60 = (
        c60.survived
        & (c60.maturity >= 4.5)
        & (c60.retrace >= 0.15)
        & (c60.edge60 >= 0.45)
        & (c60.edge6 >= 0.10)
        & (c60.macd >= -1.0)
        & (c60.flow >= 0.15)
    )
    mu, fu = first_signal_metrics(c60, ultra60)

    result = {
        "status": "paper_ready_not_live_ready",
        "reference_finalized_locals": len(strict),
        "complete_swings": len(strict) - 1,
        "early_probe_10m": {
            "true_candidates_surviving": int(len(true10)),
            "false_candidates_surviving": int(len(false10)),
            "false_probe_retrace_bps_median": float(false10.retrace_bps.median()),
            "false_probe_retrace_bps_p90": float(false10.retrace_bps.quantile(.9)),
            "tradeoff": true_local_capture(10, strict, delay0, mdf, mts),
        },
        "confirmed_30m": {
            **m30,
            "quarters": quarter_metrics(f30),
            "tradeoff": true_local_capture(30, strict, delay0, mdf, mts),
        },
        "hard_60m": {
            **m60,
            "quarters": quarter_metrics(f60),
            "tradeoff": true_local_capture(60, strict, delay0, mdf, mts),
        },
        "ultra_60m_in_sample_only": {**mu, "quarters": quarter_metrics(fu)},
        "warnings": [
            "ULTRA gate was selected after inspecting the same 30D sample; 9/9 is not an untouched OOS guarantee.",
            "Historical full L50/liquidation coverage is incomplete and is not fabricated.",
            "Real orders remain disabled; this is a paper/research engine.",
        ],
    }
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
