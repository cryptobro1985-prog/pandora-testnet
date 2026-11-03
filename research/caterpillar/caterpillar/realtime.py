"""Bounded reorder/dedup ingress for Bybit's public linear trade stream."""
from __future__ import annotations

import heapq
import json
import math
import os
import ssl
import time
import urllib.parse

from .model import Trade
from .sources import SourceError, WS_URL


def parse_frame(frame, symbols, received_at):
    obj = json.loads(frame)
    if not isinstance(obj, dict):
        raise SourceError("Expected WebSocket object")
    topic = obj.get("topic", "")
    if not topic.startswith("publicTrade."):
        return [], obj
    market = topic.split(".", 1)[1]
    symbol = market.removesuffix("USDT")
    if symbol not in symbols or market != symbol+"USDT":
        raise SourceError("Unexpected public trade topic")
    rows = obj.get("data")
    if not isinstance(rows, list):
        raise SourceError("Trade frame data is not a list")
    result = []
    for row in rows:
        try:
            if row["s"] != market:
                raise ValueError("topic/data mismatch")
            trade = Trade(symbol, float(row["T"])/1000, float(row["p"]), float(row["v"]),
                          {"Buy": 1, "Sell": -1}[row["S"]], str(row["i"]), received_at)
            if not trade.valid():
                raise ValueError("invalid trade")
            result.append(trade)
        except (KeyError, ValueError, TypeError):
            raise SourceError("Malformed public trade row") from None
    return result, obj


class Ingress:
    def __init__(self, engine, reorder_seconds=2.0, max_lag_seconds=15.0, max_buffer=100000):
        if reorder_seconds < 0 or max_lag_seconds <= reorder_seconds or max_buffer < 1:
            raise ValueError("Invalid ingress bounds")
        self.engine = engine
        self.reorder = reorder_seconds
        self.max_lag = max_lag_seconds
        self.max_buffer = max_buffer
        self.heap = []
        self.counter = 0

    def push(self, t, now):
        if t.ts > now+1 or now-t.ts > self.max_lag:
            self.engine.quality(t.symbol, now, "stale_or_future_ingress", event_ts=t.ts)
            self.heap = [row for row in self.heap if row[2].symbol != t.symbol]
            heapq.heapify(self.heap)
            self.engine.gap(t.symbol, now, "unusable_ingress_gap")
            return
        if len(self.heap) >= self.max_buffer:
            self.disconnect(now, "ingress_overflow")
            raise SourceError("Bounded ingress overflow; warmup reset")
        self.counter += 1
        heapq.heappush(self.heap, (t.ts, self.counter, t))
        self.flush(now)

    def flush(self, now, final=False):
        watermark = math.inf if final else now-self.reorder
        while self.heap and self.heap[0][0] <= watermark:
            self.engine.on_trade(heapq.heappop(self.heap)[2])

    def disconnect(self, now, reason):
        # Buffered ticks may be incomplete across disconnect; don't turn them into decisions.
        self.heap.clear()
        for symbol in self.engine.states:
            self.engine.gap(symbol, now, reason)


def proxy_options(url=WS_URL):
    target = urllib.parse.urlparse(url)
    no_proxy = os.environ.get("NO_PROXY", os.environ.get("no_proxy", ""))
    excluded = [x.strip() for x in no_proxy.split(",") if x.strip()]
    if any(x == "*" or target.hostname == x.lstrip(".") or target.hostname.endswith("."+x.lstrip(".")) for x in excluded):
        return {"http_no_proxy": excluded}
    proxy = os.environ.get("HTTPS_PROXY", os.environ.get("https_proxy"))
    if not proxy:
        return {}
    parsed = urllib.parse.urlparse(proxy)
    if parsed.scheme != "http":
        raise SourceError("Only HTTP CONNECT proxy is supported; retain the platform route")
    options = {"http_proxy_host": parsed.hostname, "http_proxy_port": parsed.port or 80, "proxy_type": "http"}
    if parsed.username:
        options["http_proxy_auth"] = (urllib.parse.unquote(parsed.username), urllib.parse.unquote(parsed.password or ""))
    return options


def realtime(engine, duration=21600, reorder_seconds=2, max_lag_seconds=15):
    import websocket
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("duration must be positive")
    ingress = Ingress(engine, reorder_seconds, max_lag_seconds)
    deadline = time.monotonic()+duration
    connected = False
    reconnects = frames = 0
    failed = False
    while time.monotonic() < deadline:
        ws = None
        try:
            ws = websocket.create_connection(WS_URL, timeout=min(10, max(1, deadline-time.monotonic())),
                                             sslopt={"context": ssl.create_default_context()}, **proxy_options())
            ws.settimeout(1)
            ws.send(json.dumps({"op": "subscribe", "req_id": "caterpillar-trades",
                                "args": ["publicTrade."+s+"USDT" for s in engine.states]}))
            ack_deadline = time.monotonic()+10
            acked = False
            last_ping = time.monotonic()
            last_message = time.monotonic()
            connected = True
            while time.monotonic() < deadline:
                now = time.time()
                try:
                    frame = ws.recv()
                except websocket.WebSocketTimeoutException:
                    frame = None
                if frame == "" or frame == b"":
                    raise SourceError("Public WebSocket closed")
                if frame:
                    last_message = time.monotonic()
                    trades, obj = parse_frame(frame, engine.states, now)
                    frames += 1
                    if obj.get("op") == "subscribe":
                        if obj.get("success") is not True:
                            raise SourceError("Bybit rejected subscription")
                        acked = True
                    for t in trades:
                        ingress.push(t, now)
                ingress.flush(time.time())
                if not acked and time.monotonic() > ack_deadline:
                    raise SourceError("Subscription acknowledgement timeout")
                if time.monotonic()-last_message > 30:
                    raise SourceError("Public WebSocket heartbeat timeout")
                if time.monotonic()-last_ping > 20:
                    ws.send(json.dumps({"op": "ping"}))
                    last_ping = time.monotonic()
                    engine.output.flush()
        except (OSError, websocket.WebSocketException, SourceError, ValueError) as exc:
            # Exception type only: proxy exceptions can embed auth-bearing URLs.
            failed = True
            reconnects += 1
            ingress.disconnect(time.time(), "reconnect/"+type(exc).__name__)
            print(f"Public feed reconnect {reconnects}: {type(exc).__name__}", flush=True)
            remaining = deadline-time.monotonic()
            if remaining > 0:
                time.sleep(min(remaining, min(2**min(reconnects, 5), 30)))
        finally:
            if ws is not None:
                ws.close()
    ingress.flush(time.time(), final=True)
    accepted = sum(p.counts.get("accepted_trades", 0) for p in engine.profiles.values())
    engine.coverage.append({"source": WS_URL, "subscribed_symbols": list(engine.states), "duration_seconds": duration,
                            "connected_once": connected, "frames": frames, "reconnects": reconnects,
                            "accepted": accepted, "status": "observed_with_interruptions" if failed else "observed"})
    return "incomplete_coverage" if failed or not accepted or any(not p.counts.get("accepted_trades") for p in engine.profiles.values()) else "completed"
