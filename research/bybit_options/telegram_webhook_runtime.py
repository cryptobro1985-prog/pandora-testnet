from __future__ import annotations
import json
import os
from typing import Any

import requests

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
SECRET = os.getenv("OPTIONS_TELEGRAM_WEBHOOK_SECRET", "").strip()
PUBLIC_BASE = os.getenv("OPTIONS_PUBLIC_BASE_URL", os.getenv("RENDER_EXTERNAL_URL", "https://pandora-options-live-signal.onrender.com")).rstrip("/")


def configure() -> dict[str, Any]:
    if not TOKEN or not SECRET:
        return {"ok": False, "configured": False}
    base = "https://api.telegram.org/bot" + TOKEN
    r = requests.post(
        base + "/setWebhook",
        json={
            "url": PUBLIC_BASE + "/telegram/webhook",
            "secret_token": SECRET,
            "allowed_updates": ["message"],
            "drop_pending_updates": False,
        },
        timeout=12,
    )
    r.raise_for_status()
    return {"ok": True, "configured": True, "url": PUBLIC_BASE + "/telegram/webhook"}


def valid_secret(headers: Any) -> bool:
    return bool(SECRET) and headers.get("X-Telegram-Bot-Api-Secret-Token", "") == SECRET
