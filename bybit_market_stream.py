"""Bybit V5 public linear WebSocket for Strategy 1 PAPER market data.

One venue for executed flow, marks and H1/M15/1m candles. Public only: no
authentication and no order placement. Fails closed on stale trade tape.
"""
import json
import time
import websocket

from exchange_trade_adapter import normalize_bybit_public_trade, validate_latency, to_legacy_observation

DEFAULT_URL = "wss://stream.bybit.com/v5/public/linear"


def _pair(symbol):
    return str(symbol) + "USDT"


def _legacy_candle(row):
    interval = str(row.get("interval") or "")
    mapped = {"60": "1h", "15": "15m", "1": "1m"}.get(interval)
    if not mapped:
        return None
    try:
        start = int(row["start"])
        end = int(row["end"])
        symbol = str(row["symbol"])
        if not symbol.endswith("USDT"):
            return None
        return {
            "s": symbol[:-4], "i": mapped, "t": start, "T": end,
            "o": str(row["open"]), "h": str(row["high"]), "l": str(row["low"]),
            "c": str(row["close"]), "v": str(row.get("volume") or "0"),
            "n": 0,
        }
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def run_bybit_stream(observations, stop, symbols_provider, report,
                     url=DEFAULT_URL, on_mids=None, on_candles=None,
                     candle_symbols=(), on_regime_candles=None,
                     regime_symbols=(), subscribe_trades=True):
    """Persistent Bybit linear stream with dynamic subscriptions and stale watchdog."""
    backoff = 1.0
    while not stop.is_set():
        ws = None
        try:
            selected = set(symbols_provider())
            candle_selected = set(candle_symbols() if callable(candle_symbols) else candle_symbols)
            regime_selected = set(regime_symbols)
            ws = websocket.create_connection(url, timeout=8, enable_multithread=True)
            ws.settimeout(2)

            def send(op, topics):
                topics = list(topics)
                for i in range(0, len(topics), 50):
                    ws.send(json.dumps({"op": op, "args": topics[i:i+50]}))

            if subscribe_trades:
                send("subscribe", ["publicTrade." + _pair(s) for s in sorted(selected)])
            if on_mids is not None:
                send("subscribe", ["tickers." + _pair(s) for s in sorted(selected)])
            if on_candles is not None:
                topics = []
                for s in sorted(candle_selected):
                    topics += ["kline.60." + _pair(s), "kline.15." + _pair(s)]
                send("subscribe", topics)
            if on_regime_candles is not None:
                send("subscribe", ["kline.1." + _pair(s) for s in sorted(regime_selected)])

            now = time.time()
            observations.mark_connected(now, selected)
            last_received = now
            last_ping = 0.0
            last_report = 0.0
            last_refresh = now
            last_trade_receive = now
            last_trade_exchange = 0.0
            accepted_trades = stale_trades = 0
            mids = {}
            backoff = 1.0

            while not stop.is_set():
                epoch = time.time()
                if epoch - last_ping >= 20:
                    ws.send(json.dumps({"op": "ping"}))
                    last_ping = epoch
                try:
                    raw = ws.recv()
                    if not raw:
                        raise RuntimeError("bybit_stream_closed")
                    message = json.loads(raw)
                    last_received = time.time()
                    observations.heartbeat(last_received)
                    topic = str(message.get("topic") or "")
                    if topic.startswith("publicTrade."):
                        batch = []
                        for row in message.get("data") or []:
                            trade = normalize_bybit_public_trade(row)
                            ok, _reason = validate_latency(trade, int(last_received * 1000), max_age_ms=15000)
                            if not ok:
                                stale_trades += 1
                                continue
                            batch.append(to_legacy_observation(trade))
                            last_trade_exchange = max(last_trade_exchange, trade.exchange_epoch_ms / 1000.0)
                        if batch:
                            observations.ingest_trades(batch, last_received)
                            accepted_trades += len(batch)
                            last_trade_receive = last_received
                    elif topic.startswith("tickers.") and on_mids is not None:
                        data = message.get("data") or {}
                        rows = data if isinstance(data, list) else [data]
                        changed = False
                        for row in rows:
                            pair = str(row.get("symbol") or "")
                            price = row.get("lastPrice")
                            if pair.endswith("USDT") and price not in (None, ""):
                                mids[pair[:-4]] = price
                                changed = True
                        if changed:
                            on_mids(dict(mids))
                    elif topic.startswith("kline."):
                        topic_pair = topic.rsplit(".", 1)[-1]
                        for row in message.get("data") or []:
                            row = dict(row)
                            row.setdefault("symbol", topic_pair)
                            candle = _legacy_candle(row)
                            if not candle:
                                continue
                            if candle["i"] == "1m" and on_regime_candles is not None:
                                on_regime_candles(candle)
                            elif on_candles is not None:
                                on_candles(candle)
                    elif message.get("op") == "subscribe" and message.get("success") is False:
                        raise RuntimeError("bybit_subscription_error:" + str(message.get("ret_msg") or "")[:120])
                except websocket.WebSocketTimeoutException:
                    if time.time() - last_received > 30:
                        raise RuntimeError("bybit_heartbeat_stale")

                epoch = time.time()
                # The socket being alive is not proof the executed tape is live.
                # Once warmed, reconnect if no accepted trade batch reaches us.
                if subscribe_trades and epoch - last_trade_receive > 30:
                    raise RuntimeError("bybit_trade_tape_stale")

                if epoch - last_refresh >= 5:
                    desired = set(symbols_provider())
                    if desired != selected:
                        removed, added = selected - desired, desired - selected
                        if subscribe_trades:
                            send("unsubscribe", ["publicTrade." + _pair(s) for s in sorted(removed)])
                            send("subscribe", ["publicTrade." + _pair(s) for s in sorted(added)])
                        if on_mids is not None:
                            send("unsubscribe", ["tickers." + _pair(s) for s in sorted(removed)])
                            send("subscribe", ["tickers." + _pair(s) for s in sorted(added)])
                        selected = desired
                        observations.set_subscriptions(desired, epoch)
                    if on_candles is not None:
                        desired_c = set(candle_symbols() if callable(candle_symbols) else candle_symbols)
                        removed, added = candle_selected - desired_c, desired_c - candle_selected
                        old_topics=[];new_topics=[]
                        for s in sorted(removed): old_topics += ["kline.60."+_pair(s),"kline.15."+_pair(s)]
                        for s in sorted(added): new_topics += ["kline.60."+_pair(s),"kline.15."+_pair(s)]
                        if old_topics: send("unsubscribe", old_topics)
                        if new_topics: send("subscribe", new_topics)
                        candle_selected = desired_c
                    last_refresh = epoch

                if epoch - last_report >= 5:
                    exchange_lag = (epoch - last_trade_exchange) if last_trade_exchange else None
                    report({
                        "ok": True, "mode": "bybit_v5_public_linear",
                        "symbols": len(selected), "heartbeat_age_seconds": round(epoch-last_received,3),
                        "last_trade_receive_age_seconds": round(epoch-last_trade_receive,3) if subscribe_trades else None,
                        "last_trade_exchange_lag_seconds": round(exchange_lag,3) if exchange_lag is not None else None,
                        "accepted_trades": accepted_trades, "stale_trades_rejected": stale_trades,
                        "stats": observations.stats(), "coverage": "bybit_linear", "error": None,
                    })
                    last_report = epoch
        except Exception as exc:
            observations.mark_disconnected()
            report({"ok": False, "mode": "bybit_v5_public_linear",
                    "error": type(exc).__name__ + ":" + str(exc)[:160],
                    "reconnect_backoff_seconds": backoff})
        finally:
            observations.mark_disconnected()
            if ws is not None:
                try: ws.close()
                except Exception: pass
        stop.wait(backoff)
        backoff = min(30.0, backoff * 2.0)
