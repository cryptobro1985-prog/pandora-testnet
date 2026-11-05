from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict, deque
from typing import Any

import requests
import websocket
from flask import Flask, jsonify, request

app = Flask(__name__)
BASES = (
    "https://api.bybit.com",
    "https://api.bytick.com",
    "https://api.bybit.kz",
    "https://api.bybit.ae",
    "https://api.bybit.eu",
)
LINEAR_WS = os.getenv("BYBIT_LINEAR_WS", "wss://stream.bybit.com/v5/public/linear")
UNDERLYINGS = tuple(
    x.strip().upper()
    for x in os.getenv("OPTIONS_UNDERLYINGS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")
    if x.strip()
)
_session = requests.Session()
_session.headers.update({"User-Agent": "PANDORA-Bybit-Options-Relay/0.1", "Accept": "application/json"})
_lock = threading.RLock()
trades = defaultdict(lambda: deque(maxlen=6000))
liquidations = defaultdict(lambda: deque(maxlen=3000))
latest_ticker: dict[str, dict[str, Any]] = {}
ws_status = {"connected": False, "last_message_ms": 0, "last_error": None, "reconnects": 0}


def request_json(path: str, params: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    errors = []
    for base in BASES:
        try:
            r = _session.get(base + path, params=params or {}, timeout=10)
            if r.status_code != 200:
                errors.append({"base": base, "status": r.status_code, "body": r.text[:120]})
                continue
            obj = r.json()
            if obj.get("retCode") not in (0, None):
                errors.append({"base": base, "retCode": obj.get("retCode"), "retMsg": obj.get("retMsg")})
                continue
            return obj, base
        except Exception as exc:
            errors.append({"base": base, "error": repr(exc)})
    raise RuntimeError(str(errors))


def _rows(obj: dict[str, Any]) -> list[dict[str, Any]]:
    return obj.get("result", {}).get("list", []) or []


def _prune(symbol: str, now_ms: int) -> None:
    cutoff = now_ms - 5 * 60_000
    with _lock:
        while trades[symbol] and int(trades[symbol][0].get("T", 0)) < cutoff:
            trades[symbol].popleft()
        while liquidations[symbol] and int(liquidations[symbol][0].get("T", 0)) < cutoff:
            liquidations[symbol].popleft()


def on_ws_open(ws):
    args = []
    for s in UNDERLYINGS:
        args.extend([f"publicTrade.{s}", f"allLiquidation.{s}", f"tickers.{s}"])
    ws.send(json.dumps({"op": "subscribe", "args": args}))
    with _lock:
        ws_status.update(connected=True, last_error=None)


def on_ws_message(ws, raw):
    try:
        msg = json.loads(raw)
        topic = str(msg.get("topic", ""))
        data = msg.get("data")
        now_ms = int(time.time() * 1000)
        with _lock:
            ws_status["last_message_ms"] = now_ms
            if topic.startswith("publicTrade."):
                symbol = topic.rsplit(".", 1)[-1]
                for row in data if isinstance(data, list) else [data]:
                    if row:
                        trades[symbol].append(row)
            elif topic.startswith("allLiquidation."):
                symbol = topic.rsplit(".", 1)[-1]
                for row in data if isinstance(data, list) else [data]:
                    if row:
                        liquidations[symbol].append(row)
            elif topic.startswith("tickers."):
                symbol = topic.rsplit(".", 1)[-1]
                if isinstance(data, list):
                    if data:
                        latest_ticker[symbol] = data[0]
                elif isinstance(data, dict):
                    latest_ticker.setdefault(symbol, {}).update(data)
        for s in UNDERLYINGS:
            _prune(s, now_ms)
    except Exception as exc:
        with _lock:
            ws_status["last_error"] = repr(exc)


def on_ws_error(ws, error):
    with _lock:
        ws_status.update(connected=False, last_error=repr(error))


def on_ws_close(ws, code, reason):
    with _lock:
        ws_status.update(connected=False, last_error=f"close:{code}:{reason}")


def ws_worker():
    while True:
        try:
            with _lock:
                ws_status["reconnects"] += 1
            ws = websocket.WebSocketApp(
                LINEAR_WS,
                on_open=on_ws_open,
                on_message=on_ws_message,
                on_error=on_ws_error,
                on_close=on_ws_close,
            )
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as exc:
            with _lock:
                ws_status.update(connected=False, last_error=repr(exc))
        time.sleep(2)


threading.Thread(target=ws_worker, daemon=True, name="bybit-linear-ws").start()


@app.get("/health")
def health():
    try:
        obj, source = request_json("/v5/market/time")
        with _lock:
            status = dict(ws_status)
        return jsonify({
            "ok": True, "research_only": True, "server_time": obj.get("time"),
            "rest_source": source, "ws": status, "underlyings": UNDERLYINGS,
        })
    except Exception as exc:
        return jsonify({"ok": False, "research_only": True, "error": repr(exc)}), 503


@app.get("/options/instruments")
def option_instruments():
    base = request.args.get("baseCoin", "All")
    cursor = ""
    all_rows = []
    source = None
    for _ in range(20):
        params = {"category": "option", "baseCoin": base, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        obj, source = request_json("/v5/market/instruments-info", params)
        result = obj.get("result", {})
        all_rows.extend(result.get("list", []) or [])
        cursor = result.get("nextPageCursor") or ""
        if not cursor:
            break
    return jsonify({"ok": True, "list": all_rows, "source": source, "count": len(all_rows)})


@app.get("/options/tickers")
def option_tickers():
    base = request.args.get("baseCoin", "BTC").upper()
    obj, source = request_json("/v5/market/tickers", {"category": "option", "baseCoin": base})
    return jsonify({"ok": True, "list": _rows(obj), "source": source, "api_time": obj.get("time")})


@app.get("/options/orderbook")
def option_orderbook():
    symbol = request.args.get("symbol", "")
    if not symbol:
        return jsonify({"ok": False, "error": "symbol required"}), 400
    limit = min(25, max(1, int(request.args.get("limit", "25"))))
    obj, source = request_json(
        "/v5/market/orderbook",
        {"category": "option", "symbol": symbol, "limit": limit},
    )
    return jsonify({"ok": True, "result": obj.get("result", {}), "source": source, "api_time": obj.get("time")})


@app.get("/underlying/context")
def underlying_context():
    symbol = request.args.get("symbol", "").upper()
    if symbol not in UNDERLYINGS:
        return jsonify({"ok": False, "error": "unsupported symbol"}), 400
    recent_obj, src1 = request_json(
        "/v5/market/recent-trade",
        {"category": "linear", "symbol": symbol, "limit": 200},
    )
    book_obj, src2 = request_json(
        "/v5/market/orderbook",
        {"category": "linear", "symbol": symbol, "limit": 50},
    )
    oi_obj, src3 = request_json(
        "/v5/market/open-interest",
        {"category": "linear", "symbol": symbol, "intervalTime": "5min", "limit": 2},
    )
    ticker_obj, src4 = request_json(
        "/v5/market/tickers",
        {"category": "linear", "symbol": symbol},
    )
    with _lock:
        ws_t = dict(latest_ticker.get(symbol, {}))
        liq = list(liquidations[symbol])
        tr = list(trades[symbol])
        ws = dict(ws_status)
    ticker_rows = _rows(ticker_obj)
    ticker = ws_t or (ticker_rows[0] if ticker_rows else {})
    return jsonify({
        "ok": True, "research_only": True, "symbol": symbol,
        "ts_ms": int(time.time() * 1000),
        "recent_trades": _rows(recent_obj),
        "ws_recent_trades": tr,
        "liquidations": liq,
        "orderbook": book_obj.get("result", {}),
        "open_interest_5m": _rows(oi_obj),
        "ticker": ticker,
        "sources": {"recent": src1, "book": src2, "oi": src3, "ticker": src4},
        "ws": ws,
    })
