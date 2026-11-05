"""Telegram paper alerts. No Bybit private API or order execution."""
from __future__ import annotations
import os
import requests


def send_telegram(text: str, *, session=None) -> bool:
    token = os.getenv("OPTIONS_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("OPTIONS_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    client = session or requests
    response = client.post(
        "https://api.telegram.org/bot" + token + "/sendMessage",
        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError("Telegram sendMessage returned not-ok")
    return True


def format_paper_entry(signal: dict, quote: dict, *, quote_age_ms: int | None = None) -> str:
    if not signal.get("paper_only"):
        raise ValueError("non-paper signal rejected")
    if not quote.get("executable"):
        raise ValueError("non-executable quote rejected")
    if quote_age_ms is None or quote_age_ms < 0 or quote_age_ms > 5000:
        raise ValueError("stale or unverified quote")
    return (
        "PAPER BUY " + str(signal["option_type"]) + "\n"
        + str(signal["symbol"]) + "\n"
        + "Ask VWAP: " + format(quote["buy"]["vwap"], ".8g") + "\n"
        + "Bid VWAP now: " + format(quote["sell"]["vwap"], ".8g") + "\n"
        + "Quantity: " + format(quote["buy"]["quantity"], ".8g") + "\n"
        + "Estimated total entry: " + format(quote["entry_total"], ".8g") + "\n"
        + "Immediate round-trip PnL: " + format(quote["immediate_round_trip_pnl"], ".8g") + "\n"
        + "Quote age: " + str(quote_age_ms) + " ms\n"
        + "RESEARCH ONLY - no real order placed"
    )
