"""Telegram chat auto-binding for isolated Options research.

Only use getUpdates when no Telegram webhook is configured for this bot.
Do not poll the same bot concurrently from multiple workers.
"""
from __future__ import annotations
import os
import requests


def discover_private_chat(*, session=None) -> str | None:
    """Return a private chat ID from /start or /options command.

    Never take an arbitrary group chat or unsolicited sender as recipient.
    Explicit OPTIONS_TELEGRAM_CHAT_ID takes precedence.
    """
    configured = os.getenv("OPTIONS_TELEGRAM_CHAT_ID", "").strip()
    if configured:
        return configured
    token = os.getenv("OPTIONS_TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return None
    client = session or requests
    hook = client.get(
        "https://api.telegram.org/bot" + token + "/getWebhookInfo", timeout=10
    )
    hook.raise_for_status()
    if hook.json().get("result", {}).get("url"):
        return None  # Do not interfere with existing webhook consumer.
    result = client.get(
        "https://api.telegram.org/bot" + token + "/getUpdates",
        params={"limit": 100, "timeout": 0}, timeout=10
    )
    result.raise_for_status()
    for item in reversed(result.json().get("result", [])):
        message = item.get("message") or {}
        chat = message.get("chat") or {}
        if chat.get("type") == "private" and str(message.get("text", "")).split()[0:1] in (["/start"], ["/options"]):
            return str(chat["id"])
    return None
