from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque
from typing import Any

import websocket


LINEAR_WS = "wss://stream.bybit.com/v5/public/linear"


class LinearPublicWS:
    """Public Bybit linear stream cache. No authentication and no order endpoints."""

    def __init__(self, symbols: list[str], retention_ms: int = 5 * 60_000):
        self.symbols = tuple(dict.fromkeys(x.upper() for x in symbols))
        self.retention_ms = retention_ms
        self.trades = defaultdict(lambda: deque(maxlen=12000))
        self.liquidations = defaultdict(lambda: deque(maxlen=6000))
        self.tickers: dict[str, dict[str, Any]] = {}
        self.lock = threading.RLock()
        self.connected = False
        self.connected_ever = False
        self.last_message_ms = 0
        self.message_count = 0
        self.trade_events = 0
        self.liquidation_events = 0
        self.reconnects = 0
        self.last_error: str | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="options-linear-public-ws")

    def start(self) -> "LinearPublicWS":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _on_open(self, ws) -> None:
        args: list[str] = []
        for symbol in self.symbols:
            args.extend([
                f"publicTrade.{symbol}",
                f"allLiquidation.{symbol}",
                f"tickers.{symbol}",
            ])
        ws.send(json.dumps({"op": "subscribe", "args": args}))
        with self.lock:
            self.connected = True
            self.connected_ever = True
            self.last_error = None

    def _on_message(self, ws, raw: str) -> None:
        try:
            message = json.loads(raw)
            topic = str(message.get("topic", ""))
            data = message.get("data")
            now_ms = int(time.time() * 1000)
            with self.lock:
                self.last_message_ms = now_ms
                self.message_count += 1
                if topic.startswith("publicTrade."):
                    symbol = topic.rsplit(".", 1)[-1]
                    for row in data if isinstance(data, list) else [data]:
                        if row:
                            self.trades[symbol].append(row)
                            self.trade_events += 1
                elif topic.startswith("allLiquidation."):
                    symbol = topic.rsplit(".", 1)[-1]
                    for row in data if isinstance(data, list) else [data]:
                        if row:
                            self.liquidations[symbol].append(row)
                            self.liquidation_events += 1
                elif topic.startswith("tickers."):
                    symbol = topic.rsplit(".", 1)[-1]
                    if isinstance(data, list):
                        if data:
                            self.tickers.setdefault(symbol, {}).update(data[0])
                    elif isinstance(data, dict):
                        self.tickers.setdefault(symbol, {}).update(data)
                self._prune_locked(now_ms)
        except Exception as exc:
            with self.lock:
                self.last_error = repr(exc)

    def _on_error(self, ws, error: Any) -> None:
        with self.lock:
            self.connected = False
            self.last_error = repr(error)

    def _on_close(self, ws, code: Any, reason: Any) -> None:
        with self.lock:
            self.connected = False
            self.last_error = f"close:{code}:{reason}"

    def _prune_locked(self, now_ms: int) -> None:
        cutoff = now_ms - self.retention_ms
        for symbol in self.symbols:
            while self.trades[symbol] and int(self.trades[symbol][0].get("T", 0)) < cutoff:
                self.trades[symbol].popleft()
            while self.liquidations[symbol] and int(self.liquidations[symbol][0].get("T", 0)) < cutoff:
                self.liquidations[symbol].popleft()

    def _run(self) -> None:
        while not self._stop.is_set():
            with self.lock:
                self.reconnects += 1
            try:
                app = websocket.WebSocketApp(
                    LINEAR_WS,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                app.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as exc:
                with self.lock:
                    self.connected = False
                    self.last_error = repr(exc)
            if not self._stop.is_set():
                time.sleep(2)

    def wait_live(self, timeout_seconds: float = 15.0) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            with self.lock:
                if self.connected and self.last_message_ms > 0:
                    return True
            time.sleep(0.25)
        return False

    def snapshot(self, symbol: str) -> dict[str, Any]:
        symbol = symbol.upper()
        now_ms = int(time.time() * 1000)
        with self.lock:
            self._prune_locked(now_ms)
            return {
                "ws_recent_trades": list(self.trades[symbol]),
                "liquidations": list(self.liquidations[symbol]),
                "ws_ticker": dict(self.tickers.get(symbol, {})),
                "ws_status": self.status(),
            }

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "connected": self.connected,
                "connected_ever": self.connected_ever,
                "last_message_ms": self.last_message_ms,
                "message_count": self.message_count,
                "trade_events": self.trade_events,
                "liquidation_events": self.liquidation_events,
                "reconnects": self.reconnects,
                "last_error": self.last_error,
            }
