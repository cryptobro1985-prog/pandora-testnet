from __future__ import annotations

import argparse
import gzip
import json
import os
import time
from pathlib import Path
from typing import Any

import requests

from .scoring import build_candidates, candidate_to_signal, depth_metrics
from .ws_cache import LinearPublicWS


def load_config(path: str | None = None) -> dict[str, Any]:
    p = Path(path or os.getenv("OPTIONS_CONFIG", Path(__file__).with_name("config.json")))
    return json.loads(p.read_text())


class Relay:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "PANDORA-Bybit-Options-Research/0.1"})

    def get(self, path: str, **params: Any) -> Any:
        r = self.s.get(self.base + path, params=params, timeout=20)
        r.raise_for_status()
        obj = r.json()
        if isinstance(obj, dict) and obj.get("ok") is False:
            raise RuntimeError(obj)
        return obj

    def instruments(self) -> list[dict[str, Any]]:
        return self.get("/options/instruments", baseCoin="All").get("list", [])

    def tickers(self, base: str) -> list[dict[str, Any]]:
        return self.get("/options/tickers", baseCoin=base).get("list", [])

    def option_book(self, symbol: str) -> dict[str, Any]:
        return self.get("/options/orderbook", symbol=symbol, limit=25)

    def underlying(self, symbol: str) -> dict[str, Any]:
        return self.get("/underlying/context", symbol=symbol)


def append_jsonl_gz(path: Path, row: dict[str, Any]) -> None:
    with gzip.open(path, "at", encoding="utf-8") as fh:
        fh.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration-seconds", type=int, default=int(os.getenv("DURATION_SECONDS", "300")))
    ap.add_argument("--output", default=os.getenv("OPTIONS_OUTPUT", "options_research_out"))
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    cfg = load_config(args.config)
    if not cfg.get("paper_only", True):
        raise RuntimeError("Research collector refuses non-paper configuration")
    relay_url = os.getenv("OPTIONS_RELAY_URL", "").strip()
    if not relay_url:
        raise RuntimeError("OPTIONS_RELAY_URL is required")
    relay = Relay(relay_url)
    ws = LinearPublicWS(list(cfg["linear_symbols"].values())).start()
    ws_live_at_start = ws.wait_live(15.0)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    started_ms = int(time.time() * 1000)
    deadline = time.monotonic() + max(5, args.duration_seconds)
    instruments_raw = relay.instruments()
    allowed = set(cfg["underlyings"])
    instruments = {
        str(x.get("symbol")): x for x in instruments_raw
        if str(x.get("baseCoin")) in allowed and str(x.get("status")) in {"Trading", "Delivering"}
    }
    availability = sorted({str(x.get("baseCoin")) for x in instruments.values()})
    (out / "RUN_MANIFEST.json").write_text(json.dumps({
        "started_ms": started_ms,
        "relay": relay_url,
        "underlyings_requested": cfg["underlyings"],
        "underlyings_with_options": availability,
        "instrument_count": len(instruments),
        "paper_only": True,
        "allow_naked_short": False,
        "direct_public_ws": True,
        "ws_live_at_start": ws_live_at_start,
        "config": cfg,
    }, indent=2, sort_keys=True))

    contexts: dict[str, dict[str, Any]] = {}
    last_surface = 0.0
    last_signal: dict[str, float] = {}
    signal_count = scan_count = errors = 0

    while time.monotonic() < deadline:
        loop_started = time.monotonic()
        now_ms = int(time.time() * 1000)
        for base in cfg["underlyings"]:
            if base not in availability:
                continue
            linear = cfg["linear_symbols"].get(base)
            try:
                contexts[base] = relay.underlying(linear)
                direct = ws.snapshot(linear)
                if direct["ws_recent_trades"]:
                    contexts[base]["ws_recent_trades"] = direct["ws_recent_trades"]
                if direct["liquidations"]:
                    contexts[base]["liquidations"] = direct["liquidations"]
                contexts[base]["direct_ws_status"] = direct["ws_status"]
            except Exception as exc:
                errors += 1
                append_jsonl_gz(out / "errors.jsonl.gz", {"ts_ms": now_ms, "stage": "underlying", "base": base, "error": repr(exc)})
                continue
            try:
                tickers = relay.tickers(base)
            except Exception as exc:
                errors += 1
                append_jsonl_gz(out / "errors.jsonl.gz", {"ts_ms": now_ms, "stage": "tickers", "base": base, "error": repr(exc)})
                continue

            if time.monotonic() - last_surface >= cfg["surface_interval_seconds"]:
                append_jsonl_gz(out / "surfaces.jsonl.gz", {
                    "ts_ms": now_ms, "base": base, "context": contexts[base], "tickers": tickers,
                })

            cands = build_candidates(
                tickers, instruments, contexts[base], now_ms,
                float(cfg["min_dte_hours"]), float(cfg["max_dte_hours"]),
                float(cfg["max_spread_fraction"]),
            )[: int(cfg["candidate_limit_per_underlying"])]

            append_jsonl_gz(out / "candidates.jsonl.gz", {
                "ts_ms": now_ms, "base": base,
                "top": [
                    {"symbol": c.symbol, "score": c.score, "side": c.side,
                     "dte_hours": c.dte_hours, "strike": c.strike, "underlying": c.underlying,
                     "bid": c.bid, "ask": c.ask, "mark_iv": c.mark_iv,
                     "gamma": c.gamma, "theta": c.theta}
                    for c in cands[:20]
                ],
            })

            for c in cands[: int(cfg["orderbook_refine_limit"])]:
                if c.score < float(cfg["signal_threshold"]):
                    continue
                if now_ms / 1000.0 - last_signal.get(c.symbol, 0.0) < float(cfg["signal_cooldown_seconds"]):
                    continue
                depth = {}
                try:
                    book = relay.option_book(c.symbol)
                    depth = depth_metrics(book, c.ask or c.mark)
                except Exception as exc:
                    errors += 1
                    append_jsonl_gz(out / "errors.jsonl.gz", {"ts_ms": now_ms, "stage": "option_book", "symbol": c.symbol, "error": repr(exc)})
                append_jsonl_gz(out / "signals.jsonl.gz", candidate_to_signal(c, depth, now_ms))
                last_signal[c.symbol] = now_ms / 1000.0
                signal_count += 1
            scan_count += 1

        if time.monotonic() - last_surface >= cfg["surface_interval_seconds"]:
            last_surface = time.monotonic()
        elapsed = time.monotonic() - loop_started
        time.sleep(max(0.1, float(cfg["scan_interval_seconds"]) - elapsed))

    ended_ms = int(time.time() * 1000)
    ws_final = ws.status()
    ws.stop()
    summary = {
        "started_ms": started_ms, "ended_ms": ended_ms,
        "duration_seconds": (ended_ms - started_ms) / 1000.0,
        "instrument_count": len(instruments), "underlyings_with_options": availability,
        "scan_count": scan_count, "signal_count": signal_count, "errors": errors,
        "paper_only": True,
        "direct_ws_connected_ever": bool(ws_final["connected_ever"]),
        "direct_ws_messages": int(ws_final["message_count"]),
        "direct_ws_trade_events": int(ws_final["trade_events"]),
        "direct_ws_liquidation_events": int(ws_final["liquidation_events"]),
        "direct_ws_reconnects": int(ws_final["reconnects"]),
        "direct_ws_last_error": ws_final["last_error"],
    }
    (out / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
