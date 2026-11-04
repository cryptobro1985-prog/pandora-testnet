#!/usr/bin/env python3
"""
HYPE H1 Local Engine v5 research.

Research only. No order placement.

Historical:
- 1m HYPEUSDT linear klines from Bybit V5
- 5m open interest from Bybit V5
- causal H1 structural candidates + OI change features

Historical ticks:
- public Bybit trade archive -> 1m aggressive BUY/SELL notional and trade velocity

Live:
- publicTrade.HYPEUSDT
- allLiquidation.HYPEUSDT
- orderbook.50.HYPEUSDT
- 30s open-interest polling
- 1-second microstructure feature snapshots

The live capture is intentionally separate from historical labels so that book/liquidation
features can be evaluated out-of-sample without pretending they existed in the 30d archive.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import gzip
import io
import json
import math
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import requests

BASE = "https://api.bybit.com"
WS = "wss://stream.bybit.com/v5/public/linear"
SYMBOL = "HYPEUSDT"
UA = "pandora-hype-local-v5-research/1.0"


def ms(d: dt.datetime) -> int:
    return int(d.timestamp() * 1000)


def utc_date(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)


def request_json(path: str, params: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    r = requests.get(BASE + path, params=params, timeout=timeout, headers={"User-Agent": UA})
    r.raise_for_status()
    obj = r.json()
    if obj.get("retCode") != 0:
        raise RuntimeError(f"Bybit error {obj.get('retCode')}: {obj.get('retMsg')}")
    return obj


def fetch_klines(start_ms: int, end_ms: int) -> list[dict[str, float]]:
    out: dict[int, dict[str, float]] = {}
    cursor_end = end_ms
    while cursor_end >= start_ms:
        obj = request_json("/v5/market/kline", {
            "category": "linear", "symbol": SYMBOL, "interval": "1",
            "start": start_ms, "end": cursor_end, "limit": 1000,
        })
        rows = obj["result"]["list"]
        if not rows:
            break
        oldest = cursor_end
        for r in rows:
            t = int(r[0])
            if start_ms <= t <= end_ms:
                out[t] = {
                    "ts": t, "open": float(r[1]), "high": float(r[2]),
                    "low": float(r[3]), "close": float(r[4]),
                    "volume": float(r[5]), "turnover": float(r[6]),
                }
            oldest = min(oldest, t)
        if oldest <= start_ms or oldest >= cursor_end:
            break
        cursor_end = oldest - 1
        time.sleep(0.04)
    return [out[k] for k in sorted(out)]


def fetch_oi(start_ms: int, end_ms: int) -> list[dict[str, float]]:
    out: dict[int, dict[str, float]] = {}
    cursor_end = end_ms
    while cursor_end >= start_ms:
        obj = request_json("/v5/market/open-interest", {
            "category": "linear", "symbol": SYMBOL, "intervalTime": "5min",
            "startTime": start_ms, "endTime": cursor_end, "limit": 200,
        })
        rows = obj["result"]["list"]
        if not rows:
            break
        oldest = cursor_end
        for r in rows:
            t = int(r["timestamp"])
            if start_ms <= t <= end_ms:
                out[t] = {"ts": t, "open_interest": float(r["openInterest"])}
            oldest = min(oldest, t)
        if oldest <= start_ms or oldest >= cursor_end:
            break
        cursor_end = oldest - 1
        time.sleep(0.04)
    return [out[k] for k in sorted(out)]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def aggregate_h1(mins: list[dict[str, float]]) -> list[dict[str, float]]:
    b: dict[int, dict[str, float]] = {}
    for x in mins:
        k = (int(x["ts"]) // 3_600_000) * 3_600_000
        if k not in b:
            b[k] = {"ts": k, "open": x["open"], "high": x["high"], "low": x["low"],
                    "close": x["close"], "volume": x["volume"], "turnover": x["turnover"]}
        else:
            z = b[k]
            z["high"] = max(z["high"], x["high"])
            z["low"] = min(z["low"], x["low"])
            z["close"] = x["close"]
            z["volume"] += x["volume"]
            z["turnover"] += x["turnover"]
    return [b[k] for k in sorted(b)]


def nearest_oi(oi: list[dict[str, float]], t: int) -> float | None:
    # monotonic binary search without third-party deps
    lo, hi = 0, len(oi)
    while lo < hi:
        mid = (lo + hi) // 2
        if int(oi[mid]["ts"]) <= t:
            lo = mid + 1
        else:
            hi = mid
    i = lo - 1
    return None if i < 0 else float(oi[i]["open_interest"])


def historical(start: str, end: str, outdir: Path) -> None:
    s = utc_date(start)
    e = utc_date(end) + dt.timedelta(days=1) - dt.timedelta(milliseconds=1)
    print(f"[historical] {start}..{end}", flush=True)
    mins = fetch_klines(ms(s), ms(e))
    oi = fetch_oi(ms(s), ms(e))
    print(f"[historical] minutes={len(mins)} oi5m={len(oi)}", flush=True)
    write_csv(outdir / "HYPE_1m.csv", mins)
    write_csv(outdir / "HYPE_oi_5m.csv", oi)

    h1 = aggregate_h1(mins)
    # ATR14 on H1
    trs: list[float] = []
    for i, x in enumerate(h1):
        pc = h1[i-1]["close"] if i else x["open"]
        tr = max(x["high"] - x["low"], abs(x["high"] - pc), abs(x["low"] - pc))
        trs.append(tr)
        x["atr14_pct"] = (
            sum(trs[max(0, i-13):i+1]) / len(trs[max(0, i-13):i+1]) / x["close"] * 100
        )

    candidates: list[dict[str, Any]] = []
    L = 6
    for i in range(L, len(h1)):
        x = h1[i]
        prev = h1[i-L:i]
        is_high = x["high"] > max(z["high"] for z in prev)
        is_low = x["low"] < min(z["low"] for z in prev)
        if not (is_high or is_low):
            continue
        for side, px, ok in (("HIGH", x["high"], is_high), ("LOW", x["low"], is_low)):
            if not ok:
                continue
            oi_now = nearest_oi(oi, int(x["ts"]) + 3_599_999)
            oi_1h = nearest_oi(oi, int(x["ts"]) - 1)
            oi_3h = nearest_oi(oi, int(x["ts"]) - 2*3_600_000 - 1)
            def pct(a, b):
                return None if a is None or b in (None, 0) else (a/b - 1) * 100
            range_pct = (x["high"]/x["low"] - 1) * 100 if x["low"] else 0
            move3 = (x["close"]/h1[max(0, i-3)]["close"] - 1) * 100 if i >= 3 else 0
            # Offline diagnostic labels only: future 2h continuation versus reversal.
            fut = h1[i+1:min(len(h1), i+3)]
            if side == "HIGH":
                future_extension = max([z["high"] for z in fut], default=px) / px - 1
                future_reversal = px / min([z["low"] for z in fut], default=px) - 1
            else:
                future_extension = px / min([z["low"] for z in fut], default=px) - 1
                future_reversal = max([z["high"] for z in fut], default=px) / px - 1
            candidates.append({
                "ts": int(x["ts"]), "side": side, "extreme": px,
                "h1_range_pct": range_pct, "atr14_pct": x["atr14_pct"],
                "move3h_pct": move3, "oi": oi_now,
                "oi_change_1h_pct": pct(oi_now, oi_1h),
                "oi_change_3h_pct": pct(oi_now, oi_3h),
                "future_extension_2h_pct": future_extension * 100,
                "future_reversal_2h_pct": future_reversal * 100,
            })
    write_csv(outdir / "HYPE_h1_structural_oi_candidates.csv", candidates)
    summary = {
        "symbol": SYMBOL, "start": start, "end": end,
        "minutes": len(mins), "h1_bars": len(h1), "oi_points_5m": len(oi),
        "structural_candidates": len(candidates), "lookback_h1": L,
        "notes": [
            "OI is historical and public via Bybit V5.",
            "future_* columns are offline diagnostic labels and MUST NOT be used by a causal live signal.",
            "Historical orderbook and all-liquidation streams are not assumed backfillable; collected forward in live mode.",
        ],
    }
    (outdir / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("HISTORICAL_SUMMARY " + json.dumps(summary), flush=True)


def archive_day(day: dt.date, out: dict[int, dict[str, float]]) -> tuple[int, int]:
    url = f"https://public.bybit.com/trading/{SYMBOL}/{SYMBOL}{day.isoformat()}.csv.gz"
    r = requests.get(url, stream=True, timeout=60, headers={"User-Agent": UA})
    if r.status_code == 404:
        print(f"[ticks] 404 {day}", flush=True)
        return 0, 0
    r.raise_for_status()
    n = 0
    try:
        gz = gzip.GzipFile(fileobj=r.raw)
        txt = io.TextIOWrapper(gz, encoding="utf-8", newline="")
        reader = csv.DictReader(txt)
        for row in reader:
            try:
                t_raw = row.get("timestamp") or row.get("time") or row.get("execTime")
                t = float(t_raw)
                t_ms = int(t if t > 1e12 else t * 1000)
                minute = (t_ms // 60_000) * 60_000
                side = (row.get("side") or "").lower()
                price = float(row.get("price") or 0)
                size = float(row.get("size") or row.get("qty") or 0)
                notional = price * size
                z = out.setdefault(minute, {
                    "ts": minute, "buy_notional": 0.0, "sell_notional": 0.0,
                    "buy_trades": 0, "sell_trades": 0, "large_buy_notional": 0.0,
                    "large_sell_notional": 0.0, "trades": 0,
                })
                if side == "buy":
                    z["buy_notional"] += notional
                    z["buy_trades"] += 1
                    if notional >= 50_000:
                        z["large_buy_notional"] += notional
                elif side == "sell":
                    z["sell_notional"] += notional
                    z["sell_trades"] += 1
                    if notional >= 50_000:
                        z["large_sell_notional"] += notional
                z["trades"] += 1
                n += 1
            except Exception:
                continue
    finally:
        r.close()
    return n, len(out)


def historical_ticks(start: str, end: str, outdir: Path) -> None:
    d = utc_date(start).date()
    stop = utc_date(end).date()
    agg: dict[int, dict[str, float]] = {}
    raw = 0
    days = 0
    while d <= stop:
        n, _ = archive_day(d, agg)
        raw += n
        days += 1
        print(f"[ticks] {d} raw={n:,} cumulative={raw:,}", flush=True)
        d += dt.timedelta(days=1)
    rows = [agg[k] for k in sorted(agg)]
    for z in rows:
        den = z["buy_notional"] + z["sell_notional"]
        z["flow_imbalance"] = 0.0 if den == 0 else (z["buy_notional"] - z["sell_notional"]) / den
        tden = z["buy_trades"] + z["sell_trades"]
        z["trade_imbalance"] = 0.0 if tden == 0 else (z["buy_trades"] - z["sell_trades"]) / tden
    write_csv(outdir / f"HYPE_ticks_1m_{start}_{end}.csv", rows)
    summary = {"symbol": SYMBOL, "start": start, "end": end, "days_requested": days,
               "raw_trades": raw, "minute_rows": len(rows)}
    (outdir / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("TICK_SUMMARY " + json.dumps(summary), flush=True)


class LiveState:
    def __init__(self):
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.trades = deque()
        self.liqs = deque()
        self.oi = None
        self.oi_prev = None
        self.oi_ts = None
        self.churn = defaultdict(float)
        self.messages = defaultdict(int)

    @staticmethod
    def update_book_side(book: dict[float, float], changes: list[list[str]], label: str, churn):
        for p0, q0 in changes:
            p, q = float(p0), float(q0)
            old = book.get(p, 0.0)
            if q == 0:
                if old:
                    churn[label + "_cancel_notional"] += p * old
                book.pop(p, None)
            else:
                if q > old:
                    churn[label + "_add_notional"] += p * (q-old)
                elif q < old:
                    churn[label + "_cancel_notional"] += p * (old-q)
                book[p] = q

    def on_book(self, msg):
        data = msg.get("data") or {}
        if msg.get("type") == "snapshot":
            self.bids = {float(p): float(q) for p, q in data.get("b", [])}
            self.asks = {float(p): float(q) for p, q in data.get("a", [])}
        else:
            self.update_book_side(self.bids, data.get("b", []), "bid", self.churn)
            self.update_book_side(self.asks, data.get("a", []), "ask", self.churn)
        self.messages["book"] += 1

    def on_trade(self, msg):
        now = time.time()
        for x in msg.get("data") or []:
            p = float(x.get("p", 0)); v = float(x.get("v", 0)); side = x.get("S")
            self.trades.append((now, side, p*v))
        self.messages["trade"] += 1

    def on_liq(self, msg):
        now = time.time()
        for x in msg.get("data") or []:
            p = float(x.get("p", 0)); v = float(x.get("v", 0)); side = x.get("S")
            self.liqs.append((now, side, p*v))
        self.messages["liq"] += 1

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        while self.trades and self.trades[0][0] < now-60:
            self.trades.popleft()
        while self.liqs and self.liqs[0][0] < now-60:
            self.liqs.popleft()

        bids = sorted(self.bids.items(), reverse=True)
        asks = sorted(self.asks.items())
        best_bid = bids[0][0] if bids else None
        best_ask = asks[0][0] if asks else None
        mid = None if best_bid is None or best_ask is None else (best_bid+best_ask)/2

        def depth(rows, n):
            return sum(p*q for p, q in rows[:n])
        def flow(sec):
            b = sum(n for t,s,n in self.trades if t >= now-sec and s == "Buy")
            a = sum(n for t,s,n in self.trades if t >= now-sec and s == "Sell")
            den = b+a
            return b, a, 0.0 if not den else (b-a)/den
        def liq(sec):
            # Bybit docs: S=Buy means a long position was liquidated.
            lng = sum(n for t,s,n in self.liqs if t >= now-sec and s == "Buy")
            sht = sum(n for t,s,n in self.liqs if t >= now-sec and s == "Sell")
            return lng, sht

        b5,a5 = depth(bids,5),depth(asks,5)
        b25,a25 = depth(bids,25),depth(asks,25)
        f5=flow(5); f15=flow(15); f60=flow(60)
        l60=liq(60)
        oi_delta = None if self.oi is None or self.oi_prev in (None,0) else (self.oi/self.oi_prev-1)*100
        z = {
            "ts_ms": int(now*1000), "best_bid": best_bid, "best_ask": best_ask, "mid": mid,
            "spread_bps": None if not mid else (best_ask-best_bid)/mid*10000,
            "book_imbalance_5": 0 if b5+a5 == 0 else (b5-a5)/(b5+a5),
            "book_imbalance_25": 0 if b25+a25 == 0 else (b25-a25)/(b25+a25),
            "bid_depth_5": b5, "ask_depth_5": a5, "bid_depth_25": b25, "ask_depth_25": a25,
            "flow_imbalance_5s": f5[2], "flow_imbalance_15s": f15[2], "flow_imbalance_60s": f60[2],
            "buy_notional_60s": f60[0], "sell_notional_60s": f60[1],
            "long_liq_notional_60s": l60[0], "short_liq_notional_60s": l60[1],
            "open_interest": self.oi, "oi_change_since_prev_poll_pct": oi_delta,
            **dict(self.churn),
        }
        self.churn.clear()
        return z


def get_latest_oi() -> float | None:
    now = int(time.time()*1000)
    obj = request_json("/v5/market/open-interest", {
        "category":"linear", "symbol":SYMBOL, "intervalTime":"5min",
        "endTime":now, "limit":1
    })
    rows = obj["result"]["list"]
    return float(rows[0]["openInterest"]) if rows else None


async def live(minutes: int, outdir: Path) -> None:
    import websockets
    outdir.mkdir(parents=True, exist_ok=True)
    state = LiveState()
    feat = (outdir / "HYPE_live_microstructure_1s.jsonl").open("w", encoding="utf-8")
    raw_liq = (outdir / "HYPE_live_liquidations.jsonl").open("w", encoding="utf-8")
    end_at = time.time() + minutes*60
    next_snap = 0.0
    next_oi = 0.0
    try:
        async with websockets.connect(WS, ping_interval=20, ping_timeout=20, max_size=8_000_000) as ws:
            await ws.send(json.dumps({"op":"subscribe","args":[
                f"publicTrade.{SYMBOL}",
                f"allLiquidation.{SYMBOL}",
                f"orderbook.50.{SYMBOL}",
            ]}))
            while time.time() < end_at:
                now = time.time()
                if now >= next_oi:
                    try:
                        state.oi_prev = state.oi
                        state.oi = await asyncio.to_thread(get_latest_oi)
                        state.oi_ts = int(now*1000)
                    except Exception as exc:
                        print(f"[live] OI poll failed: {exc}", flush=True)
                    next_oi = now + 30
                timeout = max(0.05, min(1.0, next_snap-now if next_snap > now else 0.05))
                try:
                    txt = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    msg = json.loads(txt)
                    topic = msg.get("topic","")
                    if topic.startswith("orderbook."):
                        state.on_book(msg)
                    elif topic.startswith("publicTrade."):
                        state.on_trade(msg)
                    elif topic.startswith("allLiquidation."):
                        state.on_liq(msg)
                        raw_liq.write(json.dumps(msg, separators=(",",":"))+"\n")
                except asyncio.TimeoutError:
                    pass
                now = time.time()
                if now >= next_snap:
                    feat.write(json.dumps(state.snapshot(), separators=(",",":"))+"\n")
                    feat.flush()
                    next_snap = math.floor(now) + 1
    finally:
        feat.close()
        raw_liq.close()
    summary = {
        "symbol": SYMBOL, "minutes_requested": minutes,
        "messages": dict(state.messages),
        "output": ["HYPE_live_microstructure_1s.jsonl","HYPE_live_liquidations.jsonl"],
        "contains": [
            "L50 orderbook depth/imbalance", "book add/cancel churn",
            "executed trade flow 5s/15s/60s", "allLiquidation stream",
            "open interest polled every 30s",
        ],
    }
    (outdir / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("LIVE_SUMMARY " + json.dumps(summary), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["historical","historical_ticks","live"], required=True)
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--minutes", type=int, default=20)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.mode == "historical":
        historical(args.start, args.end, args.output)
    elif args.mode == "historical_ticks":
        historical_ticks(args.start, args.end, args.output)
    else:
        asyncio.run(live(args.minutes, args.output))


if __name__ == "__main__":
    main()
