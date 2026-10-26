"""A bounded public-trade socket; callbacks keep application state isolated."""
import json
import time
import websocket


def run_trade_stream(observations, stop, symbols_provider, report, url, on_mids=None, on_candles=None, candle_symbols=(), on_candle_history=None):
    while not stop.is_set():
        ws = None
        try:
            selected = set(symbols_provider())
            ws = websocket.create_connection(url, timeout=5, enable_multithread=True)
            ws.settimeout(2)
            for symbol in sorted(selected):
                ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "trades", "coin": symbol}}))
            if on_mids is not None:
                ws.send(json.dumps({"method":"subscribe","subscription":{"type":"allMids"}}))
            if on_candles is not None:
                for symbol in sorted(candle_symbols):
                    for interval in ("1h", "15m"):
                        ws.send(json.dumps({"method":"subscribe","subscription":{"type":"candle","coin":symbol,"interval":interval}}))
            history_ids=set()
            if on_candle_history is not None:
                end_ms=int(time.time()*1000)
                for symbol in sorted(candle_symbols):
                    for interval,hours in (("1h",120),("15m",12)):
                        ident=1000000+len(history_ids);history_ids.add(ident)
                        ws.send(json.dumps({"method":"post","id":ident,"request":{"type":"info","payload":{
                            "type":"candleSnapshot","req":{"coin":symbol,"interval":interval,
                            "startTime":end_ms-hours*3600000,"endTime":end_ms}}}}))
            observations.mark_connected(time.time(), selected)
            last_ping = last_report = 0
            last_refresh = last_received = time.time()
            while not stop.is_set():
                epoch = time.time()
                if epoch-last_ping >= 5:
                    ws.send('{"method":"ping"}')
                    last_ping = epoch
                try:
                    raw = ws.recv()
                    if not raw:
                        raise RuntimeError("exchange_stream_closed")
                    message = json.loads(raw)
                    last_received = time.time()
                    observations.heartbeat(last_received)
                    if message.get("channel") == "trades":
                        observations.ingest_trades(message.get("data", []), last_received)
                    elif message.get("channel") == "allMids" and on_mids is not None:
                        data=message.get("data") or {}
                        on_mids(data.get("mids",{}))
                    elif message.get("channel") == "candle" and on_candles is not None:
                        on_candles(message.get("data"))
                    elif message.get("channel") == "post" and on_candle_history is not None:
                        reply=message.get("data") or {}
                        if reply.get("id") in history_ids:
                            history_ids.discard(reply["id"])
                            response=reply.get("response") or {}
                            payload=response.get("payload") or {}
                            if response.get("type")=="info" and isinstance(payload,dict) and payload.get("type")=="candleSnapshot" and isinstance(payload.get("data"),list):
                                on_candle_history(payload["data"])
                    elif message.get("channel") == "error":
                        raise RuntimeError("exchange_subscription_error")
                except websocket.WebSocketTimeoutException:
                    if time.time()-last_received > 12:
                        raise RuntimeError("exchange_stream_heartbeat_stale")
                epoch = time.time()
                if epoch-last_refresh >= 5:
                    desired = set(symbols_provider())
                    for method, symbols in (("unsubscribe", selected-desired), ("subscribe", desired-selected)):
                        for symbol in sorted(symbols):
                            ws.send(json.dumps({"method": method, "subscription": {"type": "trades", "coin": symbol}}))
                    observations.set_subscriptions(desired, epoch)
                    selected, last_refresh = desired, epoch
                if epoch-last_report >= 5:
                    report({"ok": True, "mode": "exchange_websocket_trades", "symbols": len(selected),
                            "heartbeat_age_seconds": epoch-last_received, "warmup_seconds": 60,
                            "stats": observations.stats(), "coverage": "hyperliquid_only", "error": None})
                    last_report = epoch
        except Exception as exc:
            observations.mark_disconnected()
            report({"ok": False, "mode": "exchange_websocket_trades",
                    "error": type(exc).__name__+":"+str(exc)[:120]})
        finally:
            observations.mark_disconnected()
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
        stop.wait(3)
