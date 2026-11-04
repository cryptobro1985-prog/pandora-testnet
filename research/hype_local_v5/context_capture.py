#!/usr/bin/env python3
"""Research-only companion capture for HYPE local analysis.

Captures the higher-timeframe/impulse context missing from the raw microstructure
collector. No trading, no private endpoints, no order placement.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import requests

BASES = (
    "https://api.bybit.com",
    "https://api.bytick.com",
    "https://api.bybit.kz",
    "https://api.bybit.ae",
    "https://api.bybit.eu",
)
SYMBOL = "HYPEUSDT"


def request_json(path: str, params: dict[str, Any]) -> dict[str, Any]:
    last = None
    for base in BASES:
        try:
            r = requests.get(base + path, params=params, timeout=10)
            r.raise_for_status()
            obj = r.json()
            if obj.get("retCode") not in (0, None):
                raise RuntimeError(f"Bybit error {obj.get('retCode')}: {obj.get('retMsg')}")
            return obj
        except Exception as exc:
            last = exc
    raise RuntimeError(f"all Bybit REST endpoints failed: {last}")


def fetch_klines(interval: str, limit: int) -> list[dict[str, Any]]:
    obj = request_json("/v5/market/kline", {
        "category": "linear", "symbol": SYMBOL, "interval": interval, "limit": limit
    })
    rows = []
    for r in reversed(obj.get("result", {}).get("list", [])):
        # Bybit: start, open, high, low, close, volume, turnover
        if len(r) < 7:
            continue
        rows.append({
            "start_ms": int(r[0]),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": float(r[5]),
            "turnover": float(r[6]),
            "interval": interval,
        })
    return rows


def fetch_ticker() -> dict[str, Any]:
    obj = request_json("/v5/market/tickers", {"category": "linear", "symbol": SYMBOL})
    rows = obj.get("result", {}).get("list", [])
    return rows[0] if rows else {}


def num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def structural_snapshot(candles: dict[str, list[dict[str, Any]]], ticker: dict[str, Any]) -> dict[str, Any]:
    m1 = candles.get("1", [])
    h1 = candles.get("60", [])
    def bounds(rows, n):
        z = rows[-n:] if n and len(rows) >= n else rows
        if not z:
            return None, None
        return min(x["low"] for x in z), max(x["high"] for x in z)
    lo_60m, hi_60m = bounds(m1, 60)
    lo_360m, hi_360m = bounds(m1, 360)
    lo_24h, hi_24h = bounds(h1, 24)
    last = m1[-1] if m1 else {}
    return {
        "ts_ms": int(time.time() * 1000),
        "symbol": SYMBOL,
        "last_m1": last,
        "rolling_60m_low": lo_60m,
        "rolling_60m_high": hi_60m,
        "rolling_6h_low": lo_360m,
        "rolling_6h_high": hi_360m,
        "rolling_24h_low": lo_24h,
        "rolling_24h_high": hi_24h,
        "last_price": num(ticker.get("lastPrice")),
        "mark_price": num(ticker.get("markPrice")),
        "index_price": num(ticker.get("indexPrice")),
        "open_interest": num(ticker.get("openInterest")),
        "funding_rate": num(ticker.get("fundingRate")),
        "turnover_24h": num(ticker.get("turnover24h")),
        "volume_24h": num(ticker.get("volume24h")),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--poll-seconds", type=int, default=60)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    raw = (args.output / "HYPE_market_context.jsonl").open("a", encoding="utf-8")
    state = (args.output / "HYPE_structural_context_1m.jsonl").open("a", encoding="utf-8")
    start = time.time()
    end = start + args.minutes * 60
    polls = 0
    errors = 0
    first = True
    last_error = None
    try:
        while time.time() < end:
            t0 = time.time()
            try:
                limits = {"1": 480 if first else 8, "3": 240 if first else 8,
                          "5": 180 if first else 8, "60": 72 if first else 4}
                candles = {k: fetch_klines(k, v) for k, v in limits.items()}
                ticker = fetch_ticker()
                record = {
                    "received_ts_ms": int(time.time() * 1000),
                    "symbol": SYMBOL,
                    "initial_backfill": first,
                    "candles": candles,
                    "ticker": ticker,
                }
                raw.write(json.dumps(record, separators=(",", ":")) + "\n")
                raw.flush()
                state.write(json.dumps(structural_snapshot(candles, ticker), separators=(",", ":")) + "\n")
                state.flush()
                polls += 1
                first = False
            except Exception as exc:
                errors += 1
                last_error = repr(exc)
                err = {"ts_ms": int(time.time() * 1000), "error": last_error}
                state.write(json.dumps(err, separators=(",", ":")) + "\n")
                state.flush()
            sleep_for = max(1.0, args.poll_seconds - (time.time() - t0))
            time.sleep(min(sleep_for, max(0.0, end - time.time())))
    finally:
        raw.close()
        state.close()

    summary = {
        "research_only": True,
        "symbol": SYMBOL,
        "minutes_requested": args.minutes,
        "started_ts_ms": int(start * 1000),
        "ended_ts_ms": int(time.time() * 1000),
        "poll_seconds": args.poll_seconds,
        "successful_polls": polls,
        "errors": errors,
        "last_error": last_error,
        "captured_intervals": ["1", "3", "5", "60"],
        "initial_history": {"M1": 480, "M3": 240, "M5": 180, "H1": 72},
        "purpose": "causal HYPE v6 context: M1/M3/M5/H1 structure + ticker/mark/index/OI/funding; no trading",
    }
    (args.output / "CONTEXT_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("CONTEXT_SUMMARY " + json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
