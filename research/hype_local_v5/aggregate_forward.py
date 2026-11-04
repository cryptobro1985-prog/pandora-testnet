#!/usr/bin/env python3
"""Build a compact, non-overlapping research manifest from HYPE forward captures."""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
from statistics import median


def finite(x):
    return isinstance(x, (int, float)) and math.isfinite(x)


def read_jsonl(path):
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def segment_summary(seg: Path):
    micro = read_jsonl(seg / "HYPE_live_microstructure_1s.jsonl")
    frames = read_jsonl(seg / "HYPE_live_raw_frames.jsonl")
    context = read_jsonl(seg / "HYPE_structural_context_1m.jsonl")

    mids = [x.get("mid") for x in micro if finite(x.get("mid"))]
    ois = [x.get("open_interest") for x in micro if finite(x.get("open_interest"))]
    imb = [x.get("flow_imbalance_60s") for x in micro if finite(x.get("flow_imbalance_60s"))]
    valid_book = sum(1 for x in micro if x.get("book_valid") is True)
    flow_cov = sum(1 for x in micro if finite(x.get("flow_imbalance_60s")))
    oi_cov = sum(1 for x in micro if finite(x.get("open_interest")))

    buy = sell = 0.0
    long_liq = short_liq = 0.0
    trades = liqs = 0
    for rec in frames:
        raw = rec.get("raw_text")
        try:
            msg = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            continue
        if not isinstance(msg, dict):
            continue
        topic = msg.get("topic", "")
        data = msg.get("data") or []
        if topic.startswith("publicTrade."):
            for x in data:
                try:
                    n = float(x["p"]) * float(x["v"])
                    if x.get("S") == "Buy":
                        buy += n
                    elif x.get("S") == "Sell":
                        sell += n
                    trades += 1
                except Exception:
                    pass
        elif topic.startswith("allLiquidation."):
            for x in data:
                try:
                    n = float(x["p"]) * float(x["v"])
                    # Bybit liquidation stream semantics used by the collector:
                    # S=Buy -> long liquidation; S=Sell -> short liquidation.
                    if x.get("S") == "Buy":
                        long_liq += n
                    elif x.get("S") == "Sell":
                        short_liq += n
                    liqs += 1
                except Exception:
                    pass

    ts = [x.get("ts_ms") for x in micro if isinstance(x.get("ts_ms"), int)]
    duration_s = 0 if len(ts) < 2 else max(ts) / 1000 - min(ts) / 1000
    latest_ctx = next((x for x in reversed(context) if "error" not in x), None)
    return {
        "segment": seg.name,
        "micro_snapshots": len(micro),
        "observed_duration_seconds": duration_s,
        "book_valid_fraction": None if not micro else valid_book / len(micro),
        "flow60_coverage_fraction": None if not micro else flow_cov / len(micro),
        "oi_coverage_fraction": None if not micro else oi_cov / len(micro),
        "mid_min": min(mids) if mids else None,
        "mid_max": max(mids) if mids else None,
        "flow_imbalance_60s_median": median(imb) if imb else None,
        "executed_buy_notional": buy,
        "executed_sell_notional": sell,
        "executed_trade_count": trades,
        "long_liquidation_notional": long_liq,
        "short_liquidation_notional": short_liq,
        "liquidation_event_count": liqs,
        "oi_first": ois[0] if ois else None,
        "oi_last": ois[-1] if ois else None,
        "latest_structural_context": latest_ctx,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    candidates = sorted({p.parent for p in args.root.rglob("HYPE_live_microstructure_1s.jsonl")})
    summaries = [segment_summary(p) for p in candidates]

    def s(key):
        return sum((x.get(key) or 0) for x in summaries)
    mids_min = [x["mid_min"] for x in summaries if finite(x.get("mid_min"))]
    mids_max = [x["mid_max"] for x in summaries if finite(x.get("mid_max"))]
    aggregate = {
        "research_only": True,
        "segments_found": len(summaries),
        "observed_duration_seconds": s("observed_duration_seconds"),
        "micro_snapshots": s("micro_snapshots"),
        "executed_buy_notional": s("executed_buy_notional"),
        "executed_sell_notional": s("executed_sell_notional"),
        "executed_trade_count": s("executed_trade_count"),
        "long_liquidation_notional": s("long_liquidation_notional"),
        "short_liquidation_notional": s("short_liquidation_notional"),
        "liquidation_event_count": s("liquidation_event_count"),
        "mid_min": min(mids_min) if mids_min else None,
        "mid_max": max(mids_max) if mids_max else None,
        "segments": summaries,
        "ready_for_agents": bool(summaries),
        "next_analysis": [
            "reconstruct frozen v6 structural state causally from M1/M3/M5/H1 context",
            "align candidate/extreme times to raw trade/book/OI/liquidation evidence",
            "compare true terminal locals with prior false attempts inside the same active swing",
            "evaluate 3m/5m new-side price efficiency and persistence without OOS retuning"
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(aggregate, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(aggregate), flush=True)


if __name__ == "__main__":
    main()
