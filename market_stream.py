"""A bounded public-trade socket; callbacks keep application state isolated."""
import json
import time
import websocket


def run_trade_stream(observations, stop, symbols_provider, report, url, on_mids=None, on_candles=None, candle_symbols=(), on_candle_history=None, regime_symbols=(), on_regime_candles=None, subscribe_trades=True):
    while not stop.is_set():
        ws = None
        try:
            selected = set(symbols_provider())
            ws = websocket.create_connection(url, timeout=5, enable_multithread=True)
            ws.settimeout(2)
            if subscribe_trades:
                for symbol in sorted(selected):
                    ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "trades", "coin": symbol}}))
            if on_mids is not None:
                ws.send(json.dumps({"method":"subscribe","subscription":{"type":"allMids"}}))
            if on_candles is not None:
                for symbol in sorted(candle_symbols):
                    for interval in ("1h", "15m"):
                        ws.send(json.dumps({"method":"subscribe","subscription":{"type":"candle","coin":symbol,"interval":interval}}))
            if on_regime_candles is not None:
                for symbol in sorted(regime_symbols):
                    ws.send(json.dumps({"method":"subscribe","subscription":{"type":"candle","coin":symbol,"interval":"1m"}}))
            # History bootstrap is owned by the app's paced REST worker after
            # engine lease takeover. Websocket is live-stream only; this avoids
            # unreliable info-post replies and duplicate startup rate-limit load.
            history_queue=[]
            history_inflight={}
            history_completed=history_errors=0
            observations.mark_connected(time.time(), selected)
            last_ping = last_report = 0
            last_history_send = time.time()
            history_start_after = last_history_send + 5.0
            last_refresh = last_received = time.time()
            while not stop.is_set():
                epoch = time.time()
                if epoch-last_ping >= 5:
                    ws.send('{"method":"ping"}')
                    last_ping = epoch
                # Keep at most four history requests in flight and space new posts.
                # Failed/timeout snapshots are retried on the same websocket.
                if history_queue and epoch>=history_start_after and len(history_inflight)<1 and epoch-last_history_send>=1.00:
                    route,payload,attempts=history_queue.pop(0)
                    ident=history_seq;history_seq+=1
                    ws.send(json.dumps({"method":"post","id":ident,"request":{"type":"info","payload":payload}}))
                    history_inflight[ident]=(route,payload,attempts,epoch)
                    last_history_send=epoch
                for ident,item in list(history_inflight.items()):
                    route,payload,attempts,sent_at=item
                    if epoch-sent_at>15:
                        history_inflight.pop(ident,None);history_errors+=1
                        if attempts<6:history_queue.append((route,payload,attempts+1))
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
                    elif message.get("channel") == "candle":
                        data=message.get("data") or {}
                        if data.get("i")=="1m" and on_regime_candles is not None:
                            on_regime_candles(data)
                        elif on_candles is not None:
                            on_candles(data)
                    elif message.get("channel") == "post":
                        reply=message.get("data") or {}
                        item=history_inflight.pop(reply.get("id"),None)
                        if item is not None:
                            route,request_payload,attempts,_sent_at=item
                            response=reply.get("response") or {}
                            payload=response.get("payload") or {}
                            ok=(response.get("type")=="info" and isinstance(payload,dict)
                                and payload.get("type")=="candleSnapshot" and isinstance(payload.get("data"),list))
                            if ok:
                                callback=on_regime_candles if route=="regime" else on_candle_history
                                if callback is not None:callback(payload["data"])
                                history_completed+=1
                            else:
                                history_errors+=1
                                if attempts<6:history_queue.append((route,request_payload,attempts+1))
                    elif message.get("channel") == "error":
                        raise RuntimeError("exchange_subscription_error")
                except websocket.WebSocketTimeoutException:
                    if time.time()-last_received > 12:
                        raise RuntimeError("exchange_stream_heartbeat_stale")
                epoch = time.time()
                if epoch-last_refresh >= 5:
                    desired = set(symbols_provider())
                    if subscribe_trades:
                        for method, symbols in (("unsubscribe", selected-desired), ("subscribe", desired-selected)):
                            for symbol in sorted(symbols):
                                ws.send(json.dumps({"method": method, "subscription": {"type": "trades", "coin": symbol}}))
                    observations.set_subscriptions(desired, epoch)
                    selected, last_refresh = desired, epoch
                if epoch-last_report >= 5:
                    report({"ok": True, "mode": "exchange_websocket_trades", "symbols": len(selected),
                            "heartbeat_age_seconds": epoch-last_received, "warmup_seconds": 60,
                            "history_pending":len(history_queue)+len(history_inflight),
                            "history_completed":history_completed,"history_errors":history_errors,
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
