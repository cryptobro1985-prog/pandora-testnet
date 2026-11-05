from __future__ import annotations

import json
import math
import os
import threading
import time
from dataclasses import asdict
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from flask import Flask, jsonify, request

from research.bybit_options.scoring import build_candidates, underlying_features, depth_metrics, clamp
from research.bybit_options.feature_plane_116 import build_feature_plane_116
from research.bybit_options.agent_ensemble import evaluate_agents
from research.bybit_options.ws_cache import LinearPublicWS
from research.bybit_options import telegram_webhook_runtime as twr

app = Flask(__name__)

RELAY = os.getenv("OPTIONS_RELAY_URL", "https://pandora-bybit-options-relay.onrender.com").rstrip("/")
UNDERLYINGS = tuple(x.strip().upper() for x in os.getenv("OPTIONS_UNDERLYINGS", "BTC,ETH,SOL,HYPE").split(",") if x.strip())
LINEAR = {"BTC":"BTCUSDT","ETH":"ETHUSDT","SOL":"SOLUSDT","HYPE":"HYPEUSDT"}
SCAN_SECONDS = max(2.0, float(os.getenv("LIVE_SCAN_SECONDS", "5")))
ENTRY_THRESHOLD = float(os.getenv("LIVE_ENTRY_THRESHOLD", "0.60"))
INVALIDATE_THRESHOLD = float(os.getenv("LIVE_INVALIDATE_THRESHOLD", "0.47"))
X2_MULTIPLE = float(os.getenv("LIVE_X2_MULTIPLE", "2.0"))
HOLD_ABOVE_X2_SCORE = float(os.getenv("LIVE_HOLD_ABOVE_X2_SCORE", "0.82"))
TRAIL_MFE_FRACTION = float(os.getenv("LIVE_TRAIL_MFE_FRACTION", "0.75"))
MIN_PROTECTED_X_AFTER_X2 = float(os.getenv("LIVE_MIN_PROTECTED_X_AFTER_X2", "1.55"))
COOLDOWN_SECONDS = int(os.getenv("LIVE_SIGNAL_COOLDOWN_SECONDS", "900"))
DEPTH_REFINE_TOP = int(os.getenv("LIVE_DEPTH_REFINE_TOP", "6"))
MAX_EXEC_SPREAD_FRACTION = float(os.getenv("LIVE_MAX_EXEC_SPREAD_FRACTION", "0.12"))
MIN_EXIT_DEPTH_BALANCE = float(os.getenv("LIVE_MIN_EXIT_DEPTH_BALANCE", "0.20"))

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TG_PAIR_CODE = os.getenv("TELEGRAM_PAIR_CODE", "").strip()
ALERT_BRIDGE_URL = os.getenv("OPTIONS_ALERT_BRIDGE_URL", "").strip()
ALERT_BRIDGE_SECRET = os.getenv("OPTIONS_ALERT_SECRET", "").strip()
telegram_chat_id = TG_CHAT_ID

session = requests.Session()
session.headers.update({"User-Agent":"PANDORA-Options-Live-Decision/0.1"})
lock = threading.RLock()

state: dict[str, Any] = {
    "started_ms": int(time.time()*1000),
    "last_scan_ms": 0,
    "last_error": None,
    "scan_count": 0,
    "telegram_configured": bool((ALERT_BRIDGE_URL and ALERT_BRIDGE_SECRET) or (TG_TOKEN and telegram_chat_id)),
    "last_alert_delivery": None,
    "active": {},
    "last_events": [],
    "last_candidates": {},
    "behavior_samples": [],
    "entry_confirmation": {},
}
cooldown: dict[str, float] = {}
ws = LinearPublicWS([LINEAR[x] for x in UNDERLYINGS if x in LINEAR]).start()


def self_keepalive_worker() -> None:
    """Keep the free Render web service awake without another user automation."""
    url = os.getenv("RENDER_EXTERNAL_URL", "https://pandora-options-live-signal.onrender.com").rstrip("/") + "/health"
    interval = max(300.0, float(os.getenv("OPTIONS_SELF_KEEPALIVE_SECONDS", "480")))
    # Let gunicorn finish booting before the first public round-trip.
    time.sleep(60.0)
    while True:
        try:
            session.get(url, timeout=20)
        except Exception as exc:
            print(json.dumps({"kind":"SELF_KEEPALIVE_ERROR","error":repr(exc)}), flush=True)
        time.sleep(interval)


threading.Thread(target=self_keepalive_worker, daemon=True, name="options-self-keepalive").start()


def get_json(path: str, **params: Any) -> dict[str, Any]:
    r = session.get(RELAY + path, params=params, timeout=15)
    r.raise_for_status()
    obj = r.json()
    if obj.get("ok") is False:
        raise RuntimeError(obj)
    return obj


def tg_send(text: str, kind: str = "ALERT") -> int:
    if ALERT_BRIDGE_URL and ALERT_BRIDGE_SECRET:
        r = session.post(
            ALERT_BRIDGE_URL,
            json={"kind": kind, "text": text},
            headers={"X-Options-Alert-Secret": ALERT_BRIDGE_SECRET},
            timeout=12,
        )
        r.raise_for_status()
        payload = r.json()
        sent = int(payload.get("sent", 0))
        with lock:
            state["last_alert_delivery"] = {
                "ts_ms": int(time.time() * 1000),
                "transport": "existing_bot_webhook",
                "sent": sent,
                "failed": int(payload.get("failed", 0)),
                "subscribers": int(payload.get("subscribers", 0)),
            }
        print(json.dumps({"kind": "TELEGRAM_BRIDGE_DELIVERY", **state["last_alert_delivery"]}), flush=True)
        return sent
    if not (TG_TOKEN and telegram_chat_id):
        return 0
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    r = session.post(url, json={
        "chat_id": telegram_chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }, timeout=12)
    r.raise_for_status()
    with lock:
        state["last_alert_delivery"] = {
            "ts_ms": int(time.time() * 1000),
            "transport": "direct_sendMessage",
            "sent": 1,
            "failed": 0,
            "subscribers": 1,
        }
    return 1



def telegram_identity_probe() -> None:
    if not TG_TOKEN:
        print(json.dumps({"kind":"TELEGRAM_IDENTITY","configured":False}), flush=True)
        return
    try:
        base=f"https://api.telegram.org/bot{TG_TOKEN}"
        me=session.get(base+"/getMe",timeout=10)
        hook=session.get(base+"/getWebhookInfo",timeout=10)
        me.raise_for_status(); hook.raise_for_status()
        m=me.json().get("result",{})
        h=hook.json().get("result",{})
        print(json.dumps({
            "kind":"TELEGRAM_IDENTITY",
            "configured":True,
            "username":m.get("username"),
            "bot_id":m.get("id"),
            "webhook_url":h.get("url"),
            "pending_update_count":h.get("pending_update_count"),
            "last_error_message":h.get("last_error_message"),
        }, ensure_ascii=False), flush=True)
    except Exception as exc:
        print(json.dumps({"kind":"TELEGRAM_IDENTITY_ERROR","error":repr(exc)}), flush=True)


def telegram_pair_loop() -> None:
    global telegram_chat_id
    if twr.SECRET:
        return
    if ALERT_BRIDGE_URL and ALERT_BRIDGE_SECRET:
        return
    if not TG_TOKEN or telegram_chat_id:
        return
    offset = 0
    base = f"https://api.telegram.org/bot{TG_TOKEN}"
    while not telegram_chat_id:
        try:
            r = session.get(base + "/getUpdates", params={"offset":offset,"timeout":20}, timeout=25)
            r.raise_for_status()
            obj = r.json()
            for update in obj.get("result", []):
                offset = max(offset, int(update.get("update_id",0))+1)
                msg = update.get("message") or update.get("edited_message") or {}
                chat = msg.get("chat") or {}
                text = str(msg.get("text") or "").strip()
                private_chat = str(chat.get("type") or "private") == "private"
                pair_ok = bool(
                    private_chat
                    and chat.get("id") is not None
                    and (
                        (TG_PAIR_CODE and text == f"/pair {TG_PAIR_CODE}")
                        or (not TG_PAIR_CODE and text.startswith("/start"))
                    )
                )
                if pair_ok:
                    telegram_chat_id = str(chat["id"])
                    with lock:
                        state["telegram_configured"] = True
                    print(json.dumps({"kind":"TELEGRAM_PAIR_ACCEPTED","chat_id":telegram_chat_id}), flush=True)
                    try:
                        tg_send("✅ <b>PANDORA OPTIONS connected</b>\nLive BUY/HOLD/SELL alerts are now enabled for this chat.", kind="STARTUP")
                    except Exception as exc:
                        print(json.dumps({"kind":"TELEGRAM_PAIR_SEND_ERROR","error":repr(exc)}), flush=True)
                    return
        except Exception as exc:
            print(json.dumps({"kind":"TELEGRAM_PAIR_ERROR","error":repr(exc)}), flush=True)
            time.sleep(5)


def emit(kind: str, payload: dict[str, Any]) -> None:
    event = {"ts_ms": int(time.time()*1000), "kind": kind, **payload}
    with lock:
        state["last_events"].append(event)
        state["last_events"] = state["last_events"][-80:]
    print(json.dumps(event, sort_keys=True), flush=True)
    try:
        tg_send(format_event(event), kind=kind)
    except Exception as exc:
        with lock:
            state["last_error"] = f"telegram:{exc!r}"


def fmt_money(x: Any) -> str:
    try:
        return f"{float(x):.8g}"
    except Exception:
        return "—"


def format_event(e: dict[str, Any]) -> str:
    kind=e["kind"]
    base=str(e.get("base") or str(e.get("symbol","")).split("-",1)[0] or "—")
    option_type=str(e.get("option_type") or ("CALL" if "-C-" in str(e.get("symbol","")) else "PUT" if "-P-" in str(e.get("symbol","")) else "OPTION"))
    if kind=="ENTRY":
        return (
            f"🟢 <b>{base} {fmt_money(e['strike'])} — КУПИТЬ {option_type}</b>\n"
            f"Цена {base} сейчас: <b>{fmt_money(e['underlying'])} USDT</b>\n"
            f"Страйк: <b>{fmt_money(e['strike'])}</b>\n"
            f"Цена самого опциона: <b>{fmt_money(e['entry_ask'])} USDT</b>\n"
            f"Что делать: <b>КУПИТЬ {option_type}</b> по цене не хуже {fmt_money(e['entry_ask'])}.\n"
            f"До экспирации: {e['dte_hours']:.1f} ч\n"
            f"Ждать следующий сигнал: <b>ДЕРЖАТЬ</b> или <b>ПРОДАТЬ</b>.\n"
            f"⚠️ Если фактическая цена покупки заметно выше указанной, результат будет отличаться."
        )
    if kind=="X2_HOLD":
        return (
            f"🟣 <b>ДЕРЖАТЬ {option_type}</b>\n"
            f"Токен: <b>{base}</b>\n"
            f"Вход: {fmt_money(e['entry_ask'])} USDT\n"
            f"Продать сейчас можно примерно по: <b>{fmt_money(e['bid'])} USDT</b> (BID)\n"
            f"Результат сейчас: <b>{(e['multiple']-1)*100:+.1f}%</b> ({e['multiple']:.2f}x)\n"
            f"Решение: <b>НЕ ПРОДАВАТЬ — ДЕРЖАТЬ</b>"
        )
    if kind in {"TAKE_PROFIT","EXIT"}:
        reason="забрать прибыль" if kind=="TAKE_PROFIT" else "сигнал больше не подтверждён"
        return (
            f"🔴 <b>{base} — ПРОДАТЬ {option_type}</b>\n"
            f"Страйк: <b>{fmt_money(e.get('strike'))}</b>\n"
            f"Вход системы: {fmt_money(e['entry_ask'])} USDT\n"
            f"Продать сейчас по: <b>{fmt_money(e['bid'])} USDT</b> (BID)\n"
            f"Результат от системного входа: <b>{e['return_pct']:+.1f}%</b>\n"
            f"Действие: <b>ПРОДАТЬ {option_type}</b>\n"
            f"Причина: {reason}"
        )
    if kind=="HOLD":
        return (
            f"🟡 <b>ДЕРЖАТЬ {option_type}</b>\n"
            f"Токен: <b>{base}</b>\n"
            f"Вход: {fmt_money(e.get('entry_ask'))} USDT\n"
            f"BID сейчас: <b>{fmt_money(e.get('bid'))} USDT</b>\n"
            f"Результат сейчас: <b>{(e['multiple']-1)*100:+.1f}%</b>\n"
            f"Действие: <b>ДЕРЖАТЬ</b>"
        )
    return f"<b>{kind}</b>\n<code>{json.dumps(e, ensure_ascii=False)}</code>"


def load_instruments() -> dict[str, dict[str, Any]]:
    rows = get_json("/options/instruments", baseCoin="All").get("list", [])
    return {str(x.get("symbol")):x for x in rows if str(x.get("baseCoin")) in set(UNDERLYINGS)}


def option_depth(symbol: str, reference_price: float) -> dict[str, float]:
    book = get_json("/options/orderbook", symbol=symbol, limit=25)
    data = book.get("result", {})
    bids = data.get("b") or []
    asks = data.get("a") or []
    best_bid = float(bids[0][0]) if bids else 0.0
    best_ask = float(asks[0][0]) if asks else 0.0
    mid = (best_bid + best_ask) / 2.0 if best_bid > 0 and best_ask > 0 else max(best_bid, best_ask)
    spread_fraction = ((best_ask - best_bid) / mid) if mid > 0 and best_bid > 0 and best_ask > 0 else 1.0
    m = depth_metrics(data, reference_price or mid, band=0.01)
    bid_depth = float(m.get("bid_qty_1pct", 0.0))
    ask_depth = float(m.get("ask_qty_1pct", 0.0))
    depth_balance = min(bid_depth, ask_depth) / max(bid_depth, ask_depth, 1e-12)
    exitability = bid_depth / max(bid_depth + ask_depth, 1e-12)
    spread_score = clamp(1.0 - spread_fraction / max(MAX_EXEC_SPREAD_FRACTION, 1e-9), 0.0, 1.0)
    liquidity_score = clamp(0.55 * depth_balance + 0.30 * exitability + 0.15 * spread_score, 0.0, 1.0)
    return {
        **m,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_fraction": spread_fraction,
        "depth_balance": depth_balance,
        "exitability": exitability,
        "liquidity_score": liquidity_score,
    }


def refine_with_depth(cands: list[Any], context: dict[str, Any]) -> tuple[list[Any], dict[str, dict[str, float]]]:
    depth_by_symbol: dict[str, dict[str, float]] = {}
    rough_floor = max(0.58, ENTRY_THRESHOLD - 0.16)
    rough_pool = [x for x in cands if x.ask > 0 and x.score >= rough_floor]
    score_slots = max(2, DEPTH_REFINE_TOP // 2)
    price_slots_each = max(1, (DEPTH_REFINE_TOP - score_slots) // 2)
    selected_map = {x.symbol: x for x in cands[:score_slots]}
    for side in ("CALL", "PUT"):
        cheap = sorted(
            (x for x in rough_pool if x.side == side),
            key=lambda x: (x.ask, -x.score),
        )[:price_slots_each]
        for x in cheap:
            selected_map[x.symbol] = x
    if len(selected_map) < DEPTH_REFINE_TOP:
        for x in cands:
            selected_map.setdefault(x.symbol, x)
            if len(selected_map) >= DEPTH_REFINE_TOP:
                break
    selected = list(selected_map.values())[:DEPTH_REFINE_TOP]
    if selected:
        with ThreadPoolExecutor(max_workers=min(len(selected), DEPTH_REFINE_TOP), thread_name_prefix="option-depth") as pool:
            future_map = {pool.submit(option_depth, x.symbol, x.ask or x.mark): x for x in selected}
            for future in as_completed(future_map):
                cand = future_map[future]
                try:
                    d = future.result()
                    depth_by_symbol[cand.symbol] = d
                    cand.components["option_depth_liquidity"] = d["liquidity_score"]
                    cand.components["option_depth_balance"] = d["depth_balance"]
                    cand.components["option_exitability"] = d["exitability"]
                    cand.components["option_exec_spread"] = d["spread_fraction"]
                    cand.components["option_best_ask"] = d["best_ask"]
                    cand.components["option_best_bid"] = d["best_bid"]
                    spread_penalty = clamp(d["spread_fraction"] / max(MAX_EXEC_SPREAD_FRACTION, 1e-9), 0.0, 1.0)
                    cand.score = clamp(
                        0.88 * float(cand.score) + 0.12 * d["liquidity_score"] - 0.10 * spread_penalty,
                        0.0, 1.0,
                    )
                except Exception:
                    depth_by_symbol[cand.symbol] = {"error": 1.0}
                    cand.score = max(0.0, float(cand.score) - 0.15)
                    cand.components["option_depth_error"] = 1.0

    cheapest_by_side: dict[str, float] = {}
    for side in ("CALL", "PUT"):
        asks = []
        for cand in selected:
            d = depth_by_symbol.get(cand.symbol, {})
            ask = float(d.get("best_ask", 0.0))
            if (
                cand.side == side and ask > 0
                and float(d.get("spread_fraction", 1.0)) <= MAX_EXEC_SPREAD_FRACTION
                and float(d.get("depth_balance", 0.0)) >= MIN_EXIT_DEPTH_BALANCE
            ):
                asks.append(ask)
        cheapest_by_side[side] = min(asks) if asks else 0.0

    now_ms = int(time.time() * 1000)
    for cand in selected:
        d = depth_by_symbol.get(cand.symbol, {})
        if d.get("error") or not d:
            continue
        plane = build_feature_plane_116(context, cand, d, now_ms)
        decision = evaluate_agents(cand, plane, d, cheapest_by_side.get(cand.side, 0.0))
        cand.components["feature_count"] = float(plane["count"])
        cand.components["agent_consensus"] = float(decision.consensus)
        cand.components["agent_quorum"] = float(decision.quorum)
        cand.components["agent_approved"] = 1.0 if decision.approved else 0.0
        for name, vote in decision.votes.items():
            cand.components["agent_" + name] = float(vote)
        cand.score = clamp(0.68 * float(cand.score) + 0.32 * decision.consensus, 0.0, 1.0)

    return sorted(
        cands,
        key=lambda x: (
            int(x.components.get("feature_count", 0.0) == 116.0),
            int(x.components.get("agent_approved", 0.0) >= 1.0),
            float(x.components.get("agent_consensus", 0.0)),
            float(x.score),
        ),
        reverse=True,
    ), depth_by_symbol

def candidate_now(base: str, instruments: dict[str, dict[str, Any]]) -> tuple[list[Any], dict[str, Any]]:
    linear = LINEAR[base]
    ctx = get_json("/underlying/context", symbol=linear)
    direct = ws.snapshot(linear)
    if direct["ws_recent_trades"]:
        ctx["ws_recent_trades"] = direct["ws_recent_trades"]
    if direct["liquidations"]:
        ctx["liquidations"] = direct["liquidations"]
    if direct.get("ws_ticker"):
        ctx["ws_ticker"] = direct["ws_ticker"]
    if direct.get("ws_orderbook"):
        ctx["ws_orderbook"] = direct["ws_orderbook"]
    tickers = get_json("/options/tickers", baseCoin=base).get("list", [])
    cands = build_candidates(tickers, instruments, ctx, int(time.time()*1000), 1.0, 48.0, 0.35)
    cands, depth_by_symbol = refine_with_depth(cands, ctx)
    return cands, {"context":ctx, "tickers":tickers, "depth":depth_by_symbol}

def ticker_map(rows: list[dict[str, Any]]) -> dict[str,dict[str,Any]]:
    return {str(x.get("symbol")):x for x in rows}


def current_score_for_symbol(cands: list[Any], symbol: str) -> float:
    for c in cands:
        if c.symbol==symbol:
            return float(c.score)
    return 0.0


def manage_active(base: str, cands: list[Any], raw: dict[str, Any]) -> None:
    with lock:
        pos=state["active"].get(base)
    if not pos:
        return
    row=ticker_map(raw["tickers"]).get(pos["symbol"])
    if not row:
        return
    ticker_bid = float(row.get("bid1Price") or 0)
    depth_now = raw.get("depth", {}).get(pos["symbol"])
    if not depth_now:
        try:
            depth_now = option_depth(pos["symbol"], ticker_bid)
        except Exception:
            depth_now = {}
    bid = float(depth_now.get("best_bid", 0.0)) or ticker_bid
    if bid <= 0:
        return
    multiple=bid/pos["entry_ask"]
    pos["last_bid"]=bid
    pos["last_multiple"]=multiple
    pos["mfe_multiple"]=max(float(pos["mfe_multiple"]),multiple)
    score=current_score_for_symbol(cands,pos["symbol"])
    pos["score"]=score
    pos["current_spread_fraction"] = float(depth_now.get("spread_fraction", 1.0))
    pos["current_depth_balance"] = float(depth_now.get("depth_balance", 0.0))
    pos["current_exitability"] = float(depth_now.get("exitability", 0.0))
    pos["current_liquidity_score"] = float(depth_now.get("liquidity_score", 0.0))
    uf=underlying_features(raw["context"])
    direction=float(uf["direction"])
    correct_direction = direction if pos["option_type"]=="CALL" else -direction

    if not pos["x2_seen"] and multiple>=X2_MULTIPLE:
        pos["x2_seen"]=True
        protected=max(MIN_PROTECTED_X_AFTER_X2, pos["mfe_multiple"]*TRAIL_MFE_FRACTION)
        pos["protected_multiple"]=protected
        liquid_enough = pos["current_liquidity_score"] >= 0.35 and pos["current_exitability"] >= 0.25
        if score>=HOLD_ABOVE_X2_SCORE and correct_direction>0.12 and liquid_enough:
            emit("X2_HOLD",{
                "base":base,"option_type":pos["option_type"],"symbol":pos["symbol"],"entry_ask":pos["entry_ask"],"bid":bid,
                "multiple":multiple,"mfe_multiple":pos["mfe_multiple"],
                "protected_multiple":protected,"score":score,
                "exitability":pos["current_exitability"],
                "depth_balance":pos["current_depth_balance"],
            })
        else:
            close_position(base,pos,bid,multiple,"x2 reached; continuation not strong enough","TAKE_PROFIT")
            return

    if pos["x2_seen"]:
        trail_fraction = TRAIL_MFE_FRACTION
        if pos["current_liquidity_score"] < 0.40 or pos["current_spread_fraction"] > MAX_EXEC_SPREAD_FRACTION * 0.75:
            trail_fraction = max(trail_fraction, 0.85)
        pos["protected_multiple"]=max(
            float(pos.get("protected_multiple") or MIN_PROTECTED_X_AFTER_X2),
            pos["mfe_multiple"]*trail_fraction,
            MIN_PROTECTED_X_AFTER_X2,
        )
        if multiple<=pos["protected_multiple"]:
            close_position(base,pos,bid,multiple,f"profit protection hit at {pos['protected_multiple']:.2f}x","TAKE_PROFIT")
            return

    if score<INVALIDATE_THRESHOLD or correct_direction < -0.10:
        close_position(base,pos,bid,multiple,"live thesis invalidated","EXIT")
        return

    now=time.time()
    if now-float(pos.get("last_hold_notice",0))>=900:
        pos["last_hold_notice"]=now
        emit("HOLD",{
            "base":base,"option_type":pos["option_type"],"symbol":pos["symbol"],
            "entry_ask":pos["entry_ask"],"bid":bid,"multiple":multiple,
            "mfe_multiple":pos["mfe_multiple"],"score":score
        })
    with lock:
        state["active"][base]=pos
        state["entry_confirmation"].pop(base, None)


def close_position(base: str,pos: dict[str,Any],bid: float,multiple: float,reason: str,kind: str) -> None:
    emit(kind,{
        "base":base,"option_type":pos["option_type"],"symbol":pos["symbol"],"strike":pos["strike"],
        "entry_ask":pos["entry_ask"],"bid":bid,
        "multiple":multiple,"return_pct":(multiple-1)*100,
        "mfe_multiple":pos["mfe_multiple"],"reason":reason,
    })
    cooldown[pos["symbol"]]=time.time()
    with lock:
        state["active"].pop(base,None)


def maybe_enter(base: str, cands: list[Any]) -> None:
    with lock:
        if base in state["active"]:
            state["entry_confirmation"].pop(base, None)
            return
    now = time.time()
    eligible = []
    for cand in cands:
        exec_ask = float(cand.components.get("option_best_ask", 0.0)) or float(cand.ask)
        if not (
            cand.score >= ENTRY_THRESHOLD
            and cand.side in {"CALL","PUT"}
            and exec_ask > 0
            and float(cand.components.get("feature_count", 0.0)) == 116.0
            and float(cand.components.get("agent_approved", 0.0)) >= 1.0
            and float(cand.components.get("agent_quorum", 0.0)) >= 4.0
            and now - cooldown.get(cand.symbol, 0) >= COOLDOWN_SECONDS
        ):
            continue
        spread = float(cand.components.get("option_exec_spread", 1.0))
        depth_balance = float(cand.components.get("option_depth_balance", 0.0))
        if spread > MAX_EXEC_SPREAD_FRACTION or depth_balance < MIN_EXIT_DEPTH_BALANCE:
            continue
        eligible.append(cand)
    if not eligible:
        with lock:
            state["entry_confirmation"].pop(base, None)
        return

    side_strength: dict[str, float] = {}
    for side in ("CALL","PUT"):
        side_rows = [x for x in eligible if x.side == side]
        if side_rows:
            side_strength[side] = max(
                0.55*float(x.components.get("agent_consensus",0.0)) + 0.45*float(x.score)
                for x in side_rows
            )
    if not side_strength:
        return
    chosen_side = max(side_strength, key=side_strength.get)
    side_rows = [x for x in eligible if x.side == chosen_side]

    # Do not enter on one transient good scan. Require the same exact contract
    # to remain agent-approved across consecutive scans for at least 60 seconds.
    candidate_preview = min(
        side_rows,
        key=lambda x: (
            float(x.components.get("option_best_ask",0.0)) or float(x.ask),
            -float(x.components.get("agent_consensus",0.0)),
            -float(x.score),
        )
    )
    preview_ask = float(candidate_preview.components.get("option_best_ask",0.0)) or float(candidate_preview.ask)
    now_ms = int(now * 1000)
    with lock:
        conf = dict(state["entry_confirmation"].get(base) or {})
    same_contract = (
        conf.get("symbol") == candidate_preview.symbol
        and conf.get("side") == chosen_side
    )
    if not same_contract:
        conf = {
            "symbol": candidate_preview.symbol,
            "side": chosen_side,
            "first_seen_ms": now_ms,
            "last_seen_ms": now_ms,
            "confirmations": 1,
            "first_ask": preview_ask,
            "last_ask": preview_ask,
            "min_consensus": float(candidate_preview.components.get("agent_consensus",0.0)),
            "min_quorum": int(candidate_preview.components.get("agent_quorum",0.0)),
        }
    else:
        first_ask = float(conf.get("first_ask") or preview_ask or 0.0)
        ask_drift = (preview_ask / first_ask - 1.0) if first_ask > 0 else 0.0
        if abs(ask_drift) > 0.05:
            conf = {
                "symbol": candidate_preview.symbol,
                "side": chosen_side,
                "first_seen_ms": now_ms,
                "last_seen_ms": now_ms,
                "confirmations": 1,
                "first_ask": preview_ask,
                "last_ask": preview_ask,
                "min_consensus": float(candidate_preview.components.get("agent_consensus",0.0)),
                "min_quorum": int(candidate_preview.components.get("agent_quorum",0.0)),
            }
        else:
            conf["confirmations"] = int(conf.get("confirmations",0)) + 1
            conf["last_seen_ms"] = now_ms
            conf["last_ask"] = preview_ask
            conf["min_consensus"] = min(float(conf.get("min_consensus",1.0)), float(candidate_preview.components.get("agent_consensus",0.0)))
            conf["min_quorum"] = min(int(conf.get("min_quorum",5)), int(candidate_preview.components.get("agent_quorum",0.0)))
    with lock:
        state["entry_confirmation"][base] = conf

    age_ms = now_ms - int(conf.get("first_seen_ms", now_ms))
    if int(conf.get("confirmations",0)) < 3 or age_ms < 60000:
        return

    # Re-resolve the candidate after confirmation from the currently eligible rows.
    side_rows = [x for x in side_rows if x.symbol == conf.get("symbol")]
    if not side_rows:
        with lock:
            state["entry_confirmation"].pop(base, None)
        return
    cand = min(
        side_rows,
        key=lambda x: (
            float(x.components.get("option_best_ask",0.0)) or float(x.ask),
            -float(x.components.get("agent_consensus",0.0)),
            -float(x.score),
        )
    )
    entry_ask = float(cand.components.get("option_best_ask",0.0)) or float(cand.ask)
    entry_bid = float(cand.components.get("option_best_bid",0.0)) or float(cand.bid)
    pos={
        "base":base,"symbol":cand.symbol,"option_type":cand.side,
        "entry_ts_ms":int(time.time()*1000),"entry_ask":entry_ask,
        "entry_bid":entry_bid,"entry_mark":cand.mark,"strike":cand.strike,
        "expiry_ms":cand.expiry_ms,"dte_hours":cand.dte_hours,
        "score":cand.score,"mark_iv":cand.mark_iv,"delta":cand.delta,
        "gamma":cand.gamma,"theta":cand.theta,"underlying":cand.underlying,
        "agent_consensus":float(cand.components.get("agent_consensus",0.0)),
        "agent_quorum":int(cand.components.get("agent_quorum",0.0)),
        "spread_fraction":float(cand.components.get("option_exec_spread", 0.0)),
        "depth_balance":float(cand.components.get("option_depth_balance", 0.0)),
        "exitability":float(cand.components.get("option_exitability", 0.0)),
        "last_bid":entry_bid,"last_multiple":(entry_bid/entry_ask if entry_ask else 0),
        "mfe_multiple":max(0.0,entry_bid/entry_ask if entry_ask else 0.0),
        "x2_seen":False,"protected_multiple":None,"last_hold_notice":0.0,
    }
    with lock:
        state["active"][base]=pos
    emit("ENTRY",{
        "base":base,"symbol":cand.symbol,"option_type":cand.side,"strike":cand.strike,
        "dte_hours":cand.dte_hours,"entry_ask":entry_ask,"underlying":cand.underlying,
        "score":cand.score,"mark_iv":cand.mark_iv,"delta":cand.delta,
        "gamma":cand.gamma,"theta":cand.theta,
        "agent_consensus":float(cand.components.get("agent_consensus",0.0)),
        "agent_quorum":int(cand.components.get("agent_quorum",0.0)),
        "spread_fraction":float(cand.components.get("option_exec_spread", 0.0)),
        "depth_balance":float(cand.components.get("option_depth_balance", 0.0)),
        "exitability":float(cand.components.get("option_exitability", 0.0)),
    })

def startup_alert_loop() -> None:
    deadline = time.time() + 180
    while time.time() < deadline:
        with lock:
            scans = int(state["scan_count"])
        if scans > 0:
            try:
                sent = tg_send(
                    "✅ <b>PANDORA OPTIONS LIVE</b>\n"
                    "BTC / ETH / SOL scanner is online.\n"
                    "BUY / HOLD / SELL alerts are enabled.\n"
                    "Execution remains manual.",
                    kind="STARTUP",
                )
                print(json.dumps({"kind": "TELEGRAM_STARTUP_TEST", "sent": sent}), flush=True)
            except Exception as exc:
                with lock:
                    state["last_error"] = f"telegram_startup:{exc!r}"
                print(json.dumps({"kind": "TELEGRAM_STARTUP_TEST_ERROR", "error": repr(exc)}), flush=True)
            return
        time.sleep(2)


def loop() -> None:
    instruments: dict[str,dict[str,Any]]={}
    next_refresh=0.0
    last_heartbeat = 0.0
    valid_bases = [x for x in UNDERLYINGS if x in LINEAR]
    scan_pool = ThreadPoolExecutor(max_workers=max(1, len(valid_bases)), thread_name_prefix="options-base")
    while True:
        try:
            if time.time()>=next_refresh or not instruments:
                instruments=load_instruments()
                next_refresh=time.time()+900
            futures={scan_pool.submit(candidate_now, base, instruments):base for base in valid_bases}
            for future in as_completed(futures):
                base=futures[future]
                try:
                    cands,raw=future.result()
                except Exception as exc:
                    print(json.dumps({"kind":"BASE_SCAN_ERROR","base":base,"error":repr(exc)}),flush=True)
                    continue
                now_ms=int(time.time()*1000)
                candidate_rows=[
                    {"symbol":x.symbol,"side":x.side,"score":round(x.score,5),
                     "ask":float(x.components.get("option_best_ask",0.0)) or x.ask,
                     "bid":float(x.components.get("option_best_bid",0.0)) or x.bid,
                     "strike":x.strike,"dte_hours":round(x.dte_hours,3),
                     "feature_count":int(x.components.get("feature_count",0.0)),
                     "agent_consensus":round(float(x.components.get("agent_consensus",0.0)),5),
                     "agent_quorum":int(x.components.get("agent_quorum",0.0)),
                     "agent_approved":bool(x.components.get("agent_approved",0.0)),
                     "agent_votes":{
                         "direction":round(float(x.components.get("agent_direction",0.0)),5),
                         "flow":round(float(x.components.get("agent_flow",0.0)),5),
                         "gamma_vol":round(float(x.components.get("agent_gamma_vol",0.0)),5),
                         "execution_liquidity":round(float(x.components.get("agent_execution_liquidity",0.0)),5),
                         "value_price":round(float(x.components.get("agent_value_price",0.0)),5),
                     },
                     "spread_fraction":round(float(x.components.get("option_exec_spread",0.0)),6),
                     "depth_balance":round(float(x.components.get("option_depth_balance",0.0)),6),
                     "exitability":round(float(x.components.get("option_exitability",0.0)),6)}
                    for x in cands[:12]
                ]
                behavior_rows=[
                    {"ts_ms":now_ms,"base":base,**row}
                    for row in candidate_rows
                    if row["feature_count"]==116 and row["agent_quorum"]>=3
                ]
                with lock:
                    state["last_candidates"][base]=candidate_rows[:10]
                    if behavior_rows:
                        state["behavior_samples"].extend(behavior_rows)
                        state["behavior_samples"]=state["behavior_samples"][-600:]
                manage_active(base,cands,raw)
                maybe_enter(base,cands)
            with lock:
                state["scan_count"]+=1
                state["last_scan_ms"]=int(time.time()*1000)
                state["last_error"]=None
            if time.time() - last_heartbeat >= 30:
                with lock:
                    heartbeat = {
                        "kind":"HEARTBEAT",
                        "ts_ms":state["last_scan_ms"],
                        "scan_count":state["scan_count"],
                        "active":state["active"],
                        "top":{base:(rows[0] if rows else None) for base,rows in state["last_candidates"].items()},
                        "feature_plane":116,
                        "agents":5,
                        "parallel_bases":len(valid_bases),
                        "telegram_configured":state["telegram_configured"],
                        "ws":ws.status(),
                    }
                print(json.dumps(heartbeat, sort_keys=True), flush=True)
                last_heartbeat = time.time()
        except Exception as exc:
            with lock:
                state["last_error"]=repr(exc)
            print(json.dumps({"kind":"LOOP_ERROR","error":repr(exc)}),flush=True)
        time.sleep(SCAN_SECONDS)


threading.Thread(target=loop,daemon=True,name="options-live-decision-loop").start()
threading.Thread(target=telegram_pair_loop,daemon=True,name="telegram-pair-loop").start()
threading.Thread(target=telegram_identity_probe,daemon=True,name="telegram-identity-probe").start()
threading.Thread(target=lambda: print(json.dumps({"kind":"TELEGRAM_WEBHOOK_SETUP",**twr.configure()}),flush=True),daemon=True,name="telegram-webhook-config").start()
threading.Thread(target=startup_alert_loop,daemon=True,name="options-startup-alert").start()


@app.post("/telegram/webhook")
def telegram_webhook():
    global telegram_chat_id
    if not twr.valid_secret(request.headers):
        return jsonify({"ok":False}),403
    update=request.get_json(silent=True) or {}
    msg=update.get("message") or {}
    chat=msg.get("chat") or {}
    text=str(msg.get("text") or "").strip()
    if str(chat.get("type") or "")=="private" and chat.get("id") is not None and text.startswith(("/start","/options","/status")):
        telegram_chat_id=str(chat["id"])
        with lock:
            state["telegram_configured"]=True
        print(json.dumps({"kind":"TELEGRAM_PAIR_ACCEPTED","chat_id":telegram_chat_id}),flush=True)
        reply="✅ <b>PANDORA OPTIONS подключён</b>\nBTC / ETH / SOL / HYPE BUY / HOLD / SELL сигналы включены."
        try:
            tg_send(reply)
        except Exception as exc:
            print(json.dumps({"kind":"TELEGRAM_PAIR_SEND_ERROR","error":repr(exc)}),flush=True)
    return jsonify({"ok":True})


@app.get("/health")
def health():
    with lock:
        s={
            "ok": state["last_error"] is None,
            "research_only": True,
            "real_orders_enabled": False,
            "telegram_configured": state["telegram_configured"],
            "last_scan_ms": state["last_scan_ms"],
            "scan_count": state["scan_count"],
            "active_count": len(state["active"]),
            "last_error": state["last_error"],
            "last_alert_delivery": state["last_alert_delivery"],
            "ws": ws.status(),
        }
    return jsonify(s), (200 if s["ok"] else 503)


@app.get("/status")
def status():
    with lock:
        return jsonify({
            "research_only":True,
            "real_orders_enabled":False,
            "entry_threshold":ENTRY_THRESHOLD,
            "feature_plane_count":116,
            "agent_count":5,
            "x2_multiple":X2_MULTIPLE,
            "active":state["active"],
            "last_candidates":state["last_candidates"],
            "last_events":state["last_events"][-30:],
            "behavior_samples":state["behavior_samples"][-120:],
            "entry_confirmation":state["entry_confirmation"],
            "telegram_configured":state["telegram_configured"],
            "last_alert_delivery":state["last_alert_delivery"],
        })


if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","10000")))
