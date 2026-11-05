from __future__ import annotations

import json
import math
import os
import threading
import time
from dataclasses import asdict
from typing import Any

import requests
from flask import Flask, jsonify

from research.bybit_options.scoring import build_candidates, underlying_features
from research.bybit_options.ws_cache import LinearPublicWS

app = Flask(__name__)

RELAY = os.getenv("OPTIONS_RELAY_URL", "https://pandora-bybit-options-relay.onrender.com").rstrip("/")
UNDERLYINGS = tuple(x.strip().upper() for x in os.getenv("OPTIONS_UNDERLYINGS", "BTC,ETH,SOL").split(",") if x.strip())
LINEAR = {"BTC":"BTCUSDT","ETH":"ETHUSDT","SOL":"SOLUSDT"}
SCAN_SECONDS = max(2.0, float(os.getenv("LIVE_SCAN_SECONDS", "5")))
ENTRY_THRESHOLD = float(os.getenv("LIVE_ENTRY_THRESHOLD", "0.74"))
INVALIDATE_THRESHOLD = float(os.getenv("LIVE_INVALIDATE_THRESHOLD", "0.47"))
X2_MULTIPLE = float(os.getenv("LIVE_X2_MULTIPLE", "2.0"))
HOLD_ABOVE_X2_SCORE = float(os.getenv("LIVE_HOLD_ABOVE_X2_SCORE", "0.82"))
TRAIL_MFE_FRACTION = float(os.getenv("LIVE_TRAIL_MFE_FRACTION", "0.75"))
MIN_PROTECTED_X_AFTER_X2 = float(os.getenv("LIVE_MIN_PROTECTED_X_AFTER_X2", "1.55"))
COOLDOWN_SECONDS = int(os.getenv("LIVE_SIGNAL_COOLDOWN_SECONDS", "900"))

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TG_PAIR_CODE = os.getenv("TELEGRAM_PAIR_CODE", "").strip()
telegram_chat_id = TG_CHAT_ID

session = requests.Session()
session.headers.update({"User-Agent":"PANDORA-Options-Live-Decision/0.1"})
lock = threading.RLock()

state: dict[str, Any] = {
    "started_ms": int(time.time()*1000),
    "last_scan_ms": 0,
    "last_error": None,
    "scan_count": 0,
    "telegram_configured": bool(TG_TOKEN and telegram_chat_id),
    "active": {},
    "last_events": [],
    "last_candidates": {},
}
cooldown: dict[str, float] = {}
ws = LinearPublicWS([LINEAR[x] for x in UNDERLYINGS if x in LINEAR]).start()


def get_json(path: str, **params: Any) -> dict[str, Any]:
    r = session.get(RELAY + path, params=params, timeout=15)
    r.raise_for_status()
    obj = r.json()
    if obj.get("ok") is False:
        raise RuntimeError(obj)
    return obj


def tg_send(text: str) -> None:
    if not (TG_TOKEN and telegram_chat_id):
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    r = session.post(url, json={
        "chat_id": telegram_chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }, timeout=12)
    r.raise_for_status()



def telegram_pair_loop() -> None:
    global telegram_chat_id
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
                        tg_send("✅ <b>PANDORA OPTIONS connected</b>\nLive BUY/HOLD/SELL alerts are now enabled for this chat.")
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
        tg_send(format_event(event))
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
    if kind=="ENTRY":
        return (
            f"🟢 <b>LIVE OPTIONS SETUP — {e['option_type']}</b>\n"
            f"<b>{e['symbol']}</b>\n"
            f"Strike: <b>{fmt_money(e['strike'])}</b> | DTE: {e['dte_hours']:.2f}h\n"
            f"Buy reference ask: <b>{fmt_money(e['entry_ask'])}</b>\n"
            f"Underlying: {fmt_money(e['underlying'])}\n"
            f"Score: <b>{e['score']:.3f}</b>\n"
            f"IV: {e['mark_iv']:.4f} | Δ {e['delta']:.4f} | Γ {e['gamma']:.6g} | Θ {e['theta']:.6g}\n"
            f"Premium can fall to zero: <b>100% premium risk</b>\n"
            f"If premium doubles: $5→$10 | $10→$20 | $20→$40\n"
            f"Mode: live market monitoring; execution remains manual"
        )
    if kind=="X2_HOLD":
        return (
            f"🟣 <b>{e['symbol']} reached {e['multiple']:.2f}x</b>\n"
            f"Decision: <b>HOLD ABOVE X2</b>\n"
            f"Entry ask: {fmt_money(e['entry_ask'])} | Bid now: {fmt_money(e['bid'])}\n"
            f"MFE: {e['mfe_multiple']:.2f}x | protected floor: {e['protected_multiple']:.2f}x\n"
            f"Score: {e['score']:.3f} — momentum still valid"
        )
    if kind in {"TAKE_PROFIT","EXIT"}:
        label="X2 / PROFIT MILESTONE" if kind=="TAKE_PROFIT" else "SETUP INVALIDATED"
        return (
            f"🔴 <b>{label}</b>\n"
            f"<b>{e['symbol']}</b>\n"
            f"Entry ask: {fmt_money(e['entry_ask'])} | Sell reference bid: <b>{fmt_money(e['bid'])}</b>\n"
            f"Result reference: <b>{e['multiple']:.2f}x</b> ({e['return_pct']:+.1f}%)\n"
            f"MFE: {e['mfe_multiple']:.2f}x\n"
            f"Reason: {e['reason']}"
        )
    if kind=="HOLD":
        return (
            f"🟡 <b>HOLD</b> {e['symbol']}\n"
            f"Current: {e['multiple']:.2f}x | MFE {e['mfe_multiple']:.2f}x\n"
            f"Score: {e['score']:.3f}"
        )
    return f"<b>{kind}</b>\n<code>{json.dumps(e, ensure_ascii=False)}</code>"


def load_instruments() -> dict[str, dict[str, Any]]:
    rows = get_json("/options/instruments", baseCoin="All").get("list", [])
    return {str(x.get("symbol")):x for x in rows if str(x.get("baseCoin")) in set(UNDERLYINGS)}


def candidate_now(base: str, instruments: dict[str, dict[str, Any]]) -> tuple[list[Any], dict[str, Any]]:
    linear=LINEAR[base]
    ctx=get_json("/underlying/context", symbol=linear)
    direct=ws.snapshot(linear)
    if direct["ws_recent_trades"]:
        ctx["ws_recent_trades"]=direct["ws_recent_trades"]
    if direct["liquidations"]:
        ctx["liquidations"]=direct["liquidations"]
    tickers=get_json("/options/tickers", baseCoin=base).get("list", [])
    cands=build_candidates(tickers,instruments,ctx,int(time.time()*1000),1.0,48.0,0.35)
    return cands, {"context":ctx,"tickers":tickers}


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
    bid=float(row.get("bid1Price") or 0)
    if bid<=0:
        return
    multiple=bid/pos["entry_ask"]
    pos["last_bid"]=bid
    pos["last_multiple"]=multiple
    pos["mfe_multiple"]=max(float(pos["mfe_multiple"]),multiple)
    score=current_score_for_symbol(cands,pos["symbol"])
    pos["score"]=score
    uf=underlying_features(raw["context"])
    direction=float(uf["direction"])
    correct_direction = direction if pos["option_type"]=="CALL" else -direction

    if not pos["x2_seen"] and multiple>=X2_MULTIPLE:
        pos["x2_seen"]=True
        protected=max(MIN_PROTECTED_X_AFTER_X2, pos["mfe_multiple"]*TRAIL_MFE_FRACTION)
        pos["protected_multiple"]=protected
        if score>=HOLD_ABOVE_X2_SCORE and correct_direction>0.12:
            emit("X2_HOLD",{
                "symbol":pos["symbol"],"entry_ask":pos["entry_ask"],"bid":bid,
                "multiple":multiple,"mfe_multiple":pos["mfe_multiple"],
                "protected_multiple":protected,"score":score,
            })
        else:
            close_position(base,pos,bid,multiple,"x2 reached; continuation not strong enough","TAKE_PROFIT")
            return

    if pos["x2_seen"]:
        pos["protected_multiple"]=max(
            float(pos.get("protected_multiple") or MIN_PROTECTED_X_AFTER_X2),
            pos["mfe_multiple"]*TRAIL_MFE_FRACTION,
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
            "symbol":pos["symbol"],"multiple":multiple,
            "mfe_multiple":pos["mfe_multiple"],"score":score
        })
    with lock:
        state["active"][base]=pos


def close_position(base: str,pos: dict[str,Any],bid: float,multiple: float,reason: str,kind: str) -> None:
    emit(kind,{
        "symbol":pos["symbol"],"entry_ask":pos["entry_ask"],"bid":bid,
        "multiple":multiple,"return_pct":(multiple-1)*100,
        "mfe_multiple":pos["mfe_multiple"],"reason":reason,
    })
    cooldown[pos["symbol"]]=time.time()
    with lock:
        state["active"].pop(base,None)


def maybe_enter(base: str,cands: list[Any]) -> None:
    with lock:
        if base in state["active"]:
            return
    now=time.time()
    eligible=[
        c for c in cands
        if c.score>=ENTRY_THRESHOLD
        and c.side in {"CALL","PUT"}
        and c.ask>0
        and now-cooldown.get(c.symbol,0)>=COOLDOWN_SECONDS
    ]
    if not eligible:
        return
    c=eligible[0]
    pos={
        "base":base,"symbol":c.symbol,"option_type":c.side,
        "entry_ts_ms":int(time.time()*1000),"entry_ask":c.ask,
        "entry_bid":c.bid,"entry_mark":c.mark,"strike":c.strike,
        "expiry_ms":c.expiry_ms,"dte_hours":c.dte_hours,
        "score":c.score,"mark_iv":c.mark_iv,"delta":c.delta,
        "gamma":c.gamma,"theta":c.theta,"underlying":c.underlying,
        "last_bid":c.bid,"last_multiple":(c.bid/c.ask if c.ask else 0),
        "mfe_multiple":max(0.0,c.bid/c.ask if c.ask else 0.0),
        "x2_seen":False,"protected_multiple":None,"last_hold_notice":0.0,
    }
    with lock:
        state["active"][base]=pos
    emit("ENTRY",{
        "symbol":c.symbol,"option_type":c.side,"strike":c.strike,
        "dte_hours":c.dte_hours,"entry_ask":c.ask,"underlying":c.underlying,
        "score":c.score,"mark_iv":c.mark_iv,"delta":c.delta,
        "gamma":c.gamma,"theta":c.theta,
    })


def loop() -> None:
    instruments: dict[str,dict[str,Any]]={}
    next_refresh=0.0
    last_heartbeat = 0.0
    while True:
        try:
            if time.time()>=next_refresh or not instruments:
                instruments=load_instruments()
                next_refresh=time.time()+900
            for base in UNDERLYINGS:
                if base not in LINEAR:
                    continue
                cands,raw=candidate_now(base,instruments)
                with lock:
                    state["last_candidates"][base]=[
                        {"symbol":c.symbol,"side":c.side,"score":round(c.score,5),
                         "ask":c.ask,"bid":c.bid,"strike":c.strike,"dte_hours":round(c.dte_hours,3)}
                        for c in cands[:10]
                    ]
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
                        "top":{
                            base:(rows[0] if rows else None)
                            for base,rows in state["last_candidates"].items()
                        },
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
            "x2_multiple":X2_MULTIPLE,
            "active":state["active"],
            "last_candidates":state["last_candidates"],
            "last_events":state["last_events"][-30:],
            "telegram_configured":state["telegram_configured"],
        })


if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","10000")))
