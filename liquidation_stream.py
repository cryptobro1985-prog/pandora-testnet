"""Observed Binance USD-M liquidation snapshots; incomplete venue coverage.

Only the last filled quantity is counted. The published stream contains at most
one order per symbol per second, so these are observed lower-bound samples,
never a complete liquidation tape or a global heatmap.
"""
from collections import deque
import hashlib
import json
import math
import threading
import time
import websocket
from momentum_scanner import horizon_return

URL = "wss://fstream.binance.com/market/ws/!forceOrder@arr"


class LiquidationTape:
    def __init__(self):
        self.lock = threading.RLock()
        self.rows = deque(maxlen=20_000)
        self.seen = {}
        self.connected = False
        self.received = None
        self.accepted = 0

    def reset(self, connected=False):
        with self.lock:
            self.rows.clear(); self.seen.clear()
            self.connected = connected; self.received = None

    def ingest(self, message, received_at):
        message = message.get("data", message) if isinstance(message, dict) else message
        messages = message if isinstance(message, list) else [message]
        accepted = 0
        with self.lock:
            for item in messages:
                try:
                    if item.get("e") != "forceOrder":
                        continue
                    order = item["o"]
                    if str(order.get("st", 1)) != "1" or order.get("X") not in ("FILLED", "PARTIALLY_FILLED"):
                        continue
                    symbol = str(order["s"])
                    if not symbol.endswith("USDT") or order["S"] not in ("SELL", "BUY"):
                        continue
                    stamp = float(order["T"]) / 1000
                    price, quantity = float(order["ap"]), float(order["l"])
                    if not all(math.isfinite(v) for v in (stamp, price, quantity)) or min(price, quantity) <= 0:
                        continue
                    if not -1 <= received_at - stamp <= 10:
                        continue
                    key = (symbol, order["S"], order["T"], order["ap"], order.get("z"), order["l"])
                    if key in self.seen:
                        continue
                    self.seen[key] = received_at
                    side = -1 if order["S"] == "SELL" else 1
                    self.rows.append({"symbol": symbol[:-4], "side": side, "t": stamp,
                                      "notional": price * quantity, "price": price})
                    self.received = received_at; accepted += 1
                except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
                    continue
            self.seen = {key: t for key, t in self.seen.items() if received_at-t <= 120}
            self.accepted += accepted
        return accepted

    def snapshot(self, epoch):
        with self.lock:
            if not self.connected:
                return []
            groups = {}
            for row in self.rows:
                if 0 <= epoch-row["t"] <= 60:
                    groups.setdefault(row["symbol"], []).append(dict(row))
            out = []
            for symbol, rows in groups.items():
                total = sum(r["notional"] for r in rows)
                for side in (-1, 1):
                    selected = [r for r in rows if r["side"] == side]
                    if not selected:
                        continue
                    amount = sum(r["notional"] for r in selected)
                    latest = max(r["t"] for r in selected)
                    ident = hashlib.sha256((symbol+str(side)+str(latest)).encode()).hexdigest()[:24]
                    out.append({"symbol": symbol, "side": side, "events": len(selected),
                                "notional_usd": amount, "dominance": amount/total,
                                "last_event_age_seconds": epoch-latest, "cluster_id": "cascade:"+ident,
                                "source": "binance_usdm_force_order_snapshot", "coverage": "partial_venue_snapshots"})
            return out


def cascade_candidates(tape, prices, history, contexts, books, epoch, regime):
    qualified = []; rejections = {}
    for event in tape:
        symbol = event["symbol"]; side = event["side"]
        ctx = contexts.get(symbol, {}); book = books.get(symbol)
        reason = None
        floor = {"BTC": 500_000, "ETH": 250_000, "SOL": 100_000}.get(symbol, 50_000)
        if symbol not in prices:reason = "cascade_no_hyperliquid_market"
        elif event["last_event_age_seconds"] > 10:reason = "cascade_stale_events"
        elif event["events"] < 2 or event["dominance"] < .75 or event["notional_usd"] < floor:reason = "cascade_not_material"
        elif not ctx.get("trade_data_fresh") or not 0 <= epoch-float(ctx.get("epoch",0)) <= 15:reason = "cascade_missing_local_flow"
        elif int(regime.get("side") or 0) not in (0, side):reason = "cascade_opposite_market"
        elif not book or not book.get("bid_depth_complete") or not book.get("ask_depth_complete"):reason = "cascade_missing_complete_book"
        elif not 0 <= epoch-float(book.get("epoch",0)) <= 5 or book.get("spread_bps",999) > 12:reason = "cascade_stale_or_wide_book"
        if not reason:
            r15 = horizon_return(history.get(symbol,[]),epoch,15,prices[symbol])
            r60 = horizon_return(history.get(symbol,[]),epoch,60,prices[symbol])
            flow = float(ctx.get("flow_imbalance") or 0)
            burst = float(ctx.get("volume_burst_ratio") or 0)
            z = float(ctx.get("volume_rate_z") or 0)
            if r15 is None or r60 is None or side*r15 < .00035 or side*r60 < .0007:reason = "cascade_local_price_not_aligned"
            elif side*flow < .18 or side*float(book["imbalance"]) < .06:reason = "cascade_local_pressure_not_aligned"
            elif burst < 1.3 and z < 1.5:reason = "cascade_local_participation_not_abnormal"
        if reason:
            rejections[reason] = rejections.get(reason,0)+1;continue
        qualified.append({**event,"score":min(100,82+min(12,event["notional_usd"]/floor*3)+min(6,side*flow*10)),
                          "entry_route":"confirmed_cross_venue_cascade","observed_at_epoch":epoch,
                          "victim_side":"long" if side < 0 else "short", "liquidation_price":prices[symbol],
                          "r15":r15,"r60":r60,"flow_imbalance":flow,"orderbook_imbalance":book["imbalance"],
                          "volume_burst_ratio":burst,"volume_rate_z":z,"distance_pct":0.0,
                          "threshold_policy":"cascade_research_v1_not_calibrated"})
    return qualified,rejections


def run(tape, stop, report):
    while not stop.is_set():
        ws = None
        try:
            ws = websocket.create_connection(URL,timeout=8,enable_multithread=True);ws.settimeout(2)
            tape.reset(True);last_ping=last_report=0;last_received=time.time()
            while not stop.is_set():
                epoch=time.time()
                if epoch-last_ping>=10:ws.ping();last_ping=epoch
                try:
                    opcode,data=ws.recv_data(control_frame=True);last_received=time.time()
                    if opcode==websocket.ABNF.OPCODE_CLOSE:raise RuntimeError("liquidation_socket_closed")
                    if opcode in (websocket.ABNF.OPCODE_TEXT,websocket.ABNF.OPCODE_BINARY):tape.ingest(json.loads(data),last_received)
                except websocket.WebSocketTimeoutException:
                    if time.time()-last_received>40:raise RuntimeError("liquidation_transport_heartbeat_stale")
                if time.time()-last_report>=5:
                    report({"ok":True,"mode":"binance_force_order_snapshot","accepted_since_start":tape.accepted,
                            "active_cascades":len(tape.snapshot(time.time())),"coverage":"partial_binance_usdm_not_global",
                            "transport_age_seconds":time.time()-last_received,"error":None});last_report=time.time()
        except Exception as exc:
            report({"ok":False,"mode":"binance_force_order_snapshot","error":type(exc).__name__+":"+str(exc)[:150]})
        finally:
            tape.reset(False)
            if ws is not None:
                try:ws.close()
                except Exception:pass
        stop.wait(3)
