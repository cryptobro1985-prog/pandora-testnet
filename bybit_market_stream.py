"""Bybit V5 public linear WebSocket for Strategy 1 PAPER market data.

# Strategy 1 live transport: stale-tape recovery/reconnect is intentionally fail-closed.

One venue for executed flow, marks and H1/M15/1m candles. Public only: no
authentication and no order placement. Fails closed on stale trade tape.
"""
import json
import time
import websocket
import urllib.parse
import urllib.request

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


def _recover_recent_trades(symbols, observations, max_age_seconds=120):
    """Best-effort REST gap recovery before a stale shard is recycled."""
    recovered = 0
    now = time.time()
    for symbol in symbols:
        try:
            query = urllib.parse.urlencode({
                "category": "linear", "symbol": _pair(symbol), "limit": 200,
            })
            req = urllib.request.Request(
                "https://api.bybit.com/v5/market/recent-trade?" + query,
                headers={"User-Agent": "pandora-paper/1.0"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            rows = ((payload.get("result") or {}).get("list") or [])
            batch = []
            seen = set()
            for row in reversed(rows):
                trade = normalize_bybit_public_trade(row)
                age = now - (trade.exchange_epoch_ms / 1000.0)
                if age < 0 or age > max_age_seconds:
                    continue
                key = (
                    getattr(trade, "symbol", None),
                    getattr(trade, "trade_id", None),
                    trade.exchange_epoch_ms,
                    getattr(trade, "price", None),
                    getattr(trade, "size", None),
                    getattr(trade, "side", None),
                )
                if key in seen:
                    continue
                seen.add(key)
                batch.append(to_legacy_observation(trade))
            if batch:
                observations.ingest_trades(batch, time.time())
                recovered += len(batch)
        except Exception:
            continue
    return recovered

def run_bybit_stream(observations, stop, symbols_provider, report,
                     url=DEFAULT_URL, on_mids=None, on_candles=None,
                     candle_symbols=(), on_regime_candles=None,
                     regime_symbols=(), subscribe_trades=True,
                     symbol_filter=None, candle_filter=None, on_trade_mids=None, worker_name="primary"):
    """Persistent Bybit linear stream with dynamic subscriptions and stale watchdog."""
    backoff = 1.0
    while not stop.is_set():
        ws = None
        try:
            selected = set(symbols_provider())
            if symbol_filter is not None:
                selected = {s for s in selected if symbol_filter(s)}
            candle_selected = set(candle_symbols() if callable(candle_symbols) else candle_symbols)
            if candle_filter is not None:
                candle_selected = {s for s in candle_selected if candle_filter(s)}
            regime_selected = set(regime_symbols)
            ws = websocket.create_connection(url, timeout=8, enable_multithread=True)
            ws.settimeout(2)

            def send(op, topics):
                topics = list(topics)
                for i in range(0, len(topics), 50):
                    ws.send(json.dumps({"op": op, "args": topics[i:i+50]}))

            if subscribe_trades:
                # Subscribe first, then require an explicit successful Bybit ACK before
                # treating this socket as a usable executed-trade source.
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
            observations.mark_connected(now, selected, owner=worker_name)
            last_received = now
            last_ping = 0.0
            last_report = 0.0
            last_refresh = now
            last_trade_receive = now
            last_trade_exchange = 0.0
            accepted_trades = stale_trades = 0
            per_symbol_receive = {s: 0.0 for s in selected}
            per_symbol_exchange = {s: 0.0 for s in selected}
            sequence_by_symbol = {}
            sequence_gaps = 0
            trade_topics_confirmed = not subscribe_trades
            subscription_ack_deadline = now + 12.0
            trade_warmup_deadline = now + 45.0
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
                        trade_topics_confirmed = True
                        batch = []
                        for row in message.get("data") or []:
                            trade = normalize_bybit_public_trade(row)
                            ok, _reason = validate_latency(trade, int(last_received * 1000), max_age_ms=15000)
                            if not ok:
                                stale_trades += 1
                                continue
                            batch.append(to_legacy_observation(trade))
                            sym = str(getattr(trade, "symbol", "") or row.get("s") or "")
                            if sym.endswith("USDT"): sym = sym[:-4]
                            exch = trade.exchange_epoch_ms / 1000.0
                            last_trade_exchange = max(last_trade_exchange, exch)
                            if sym:
                                per_symbol_receive[sym] = last_received
                                per_symbol_exchange[sym] = exch
                                try:
                                    seq = int(row.get("seq"))
                                    prev = sequence_by_symbol.get(sym)
                                    if prev is not None and seq < prev:
                                        sequence_gaps += 1
                                    sequence_by_symbol[sym] = max(seq, prev or seq)
                                except (TypeError, ValueError):
                                    pass
                        if batch:
                            observations.ingest_trades(batch, last_received)
                            accepted_trades += len(batch)
                            last_trade_receive = last_received
                            if on_trade_mids is not None:
                                trade_mids = {}
                                for item in batch:
                                    try: trade_mids[str(item["coin"])] = float(item["px"])
                                    except (KeyError, TypeError, ValueError): pass
                                if trade_mids: on_trade_mids(trade_mids)
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
                    elif message.get("op") == "subscribe":
                        if message.get("success") is False:
                            raise RuntimeError("bybit_subscription_error:" + str(message.get("ret_msg") or "")[:120])
                        if subscribe_trades and message.get("success") is True:
                            trade_topics_confirmed = True
                except websocket.WebSocketTimeoutException:
                    if time.time() - last_received > 30:
                        raise RuntimeError("bybit_heartbeat_stale")

                epoch = time.time()
                # The socket being alive is not proof that Bybit accepted our trade topics.
                # Fail fast on a missing subscription ACK instead of leaving Strategy 1
                # indefinitely in READY_FOR_EXECUTED_FLOW with an apparently live socket.
                if subscribe_trades and epoch >= subscription_ack_deadline and not trade_topics_confirmed:
                    raise RuntimeError("bybit_trade_subscription_ack_timeout")
                # A live heartbeat is not enough: Bybit can leave a shard draining an
                # old/replayed publicTrade backlog. Quiet symbols are fine, but repeated stale
                # trade rows while no execution has been accepted means the tape is unusable.
                # Recover the recent tail best-effort, then recycle only this shard so Strategy 1
                # can rebuild fresh executed-flow without resetting the rest of the runtime.
                if subscribe_trades and stale_trades and epoch - last_trade_receive > 30:
                    recovered = _recover_recent_trades(selected, observations, max_age_seconds=120)
                    if recovered:
                        last_trade_receive = epoch
                    else:
                        raise RuntimeError("bybit_trade_tape_stale_reconnect")

                if epoch - last_refresh >= 5:
                    desired = set(symbols_provider())
                    if symbol_filter is not None:
                        desired = {s for s in desired if symbol_filter(s)}
                    if desired != selected:
                        removed, added = selected - desired, desired - selected
                        if subscribe_trades:
                            send("unsubscribe", ["publicTrade." + _pair(s) for s in sorted(removed)])
                            send("subscribe", ["publicTrade." + _pair(s) for s in sorted(added)])
                        if on_mids is not None:
                            send("unsubscribe", ["tickers." + _pair(s) for s in sorted(removed)])
                            send("subscribe", ["tickers." + _pair(s) for s in sorted(added)])
                        selected = desired
                        for s in desired:
                            per_symbol_receive.setdefault(s, 0.0)
                            per_symbol_exchange.setdefault(s, 0.0)
                        for s in list(per_symbol_receive):
                            if s not in desired:
                                per_symbol_receive.pop(s, None); per_symbol_exchange.pop(s, None)
                                sequence_by_symbol.pop(s, None)
                        observations.set_subscriptions(desired, epoch, owner=worker_name)
                    if on_candles is not None:
                        desired_c = set(candle_symbols() if callable(candle_symbols) else candle_symbols)
                        if candle_filter is not None:
                            desired_c = {s for s in desired_c if candle_filter(s)}
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
                    symbol_health = {}
                    for s in sorted(selected):
                        recv = per_symbol_receive.get(s) or 0.0
                        exch = per_symbol_exchange.get(s) or 0.0
                        symbol_health[s] = {
                            "receive_age_seconds": round(epoch-recv,3) if recv else None,
                            "exchange_lag_seconds": round(epoch-exch,3) if exch else None,
                            "fresh_15s": bool(recv and exch and epoch-recv <= 15 and epoch-exch <= 15),
                        }
                    fresh_symbols = sum(1 for v in symbol_health.values() if v["fresh_15s"])
                    report({
                        "ok": True, "mode": "bybit_v5_public_linear", "worker": worker_name,
                        "symbols": len(selected), "heartbeat_age_seconds": round(epoch-last_received,3),
                        "last_trade_receive_age_seconds": round(epoch-last_trade_receive,3) if subscribe_trades else None,
                        "last_trade_exchange_lag_seconds": round(exchange_lag,3) if exchange_lag is not None else None,
                        "accepted_trades": accepted_trades, "stale_trades_rejected": stale_trades,
                        "subscription_confirmed": trade_topics_confirmed,
                        "fresh_symbols_15s": fresh_symbols,
                        "symbol_health": symbol_health,
                        "sequence_regressions": sequence_gaps,
                        "stats": observations.stats(), "coverage": "bybit_linear", "error": None,
                    })
                    last_report = epoch
        except Exception as exc:
            observations.mark_disconnected(owner=worker_name)
            report({"ok": False, "mode": "bybit_v5_public_linear", "worker": worker_name,
                    "error": type(exc).__name__ + ":" + str(exc)[:160],
                    "reconnect_backoff_seconds": backoff})
        finally:
            observations.mark_disconnected(owner=worker_name)
            if ws is not None:
                try: ws.close()
                except Exception: pass
        stop.wait(backoff)
        backoff = min(30.0, backoff * 2.0)
