"""Attach a deployed HTTPS Mini App to a Telegram bot menu.

Requires environment variables BOT_TOKEN and MINIAPP_URL. Does not print the token.
Use a freshly rotated token stored in repository Actions secrets, never in source.
"""
import json
import os
import sys
from urllib.parse import urlsplit
from http.client import HTTPSConnection


def main() -> int:
    token = os.environ.get("BOT_TOKEN", "").strip()
    target = os.environ.get("MINIAPP_URL", "").strip()
    parsed = urlsplit(target)
    if not token:
        print("Missing BOT_TOKEN secret", file=sys.stderr)
        return 2
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port:
        print("MINIAPP_URL must be an HTTPS website without credentials or custom ports", file=sys.stderr)
        return 2
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        print("MINIAPP_URL must be publicly accessible", file=sys.stderr)
        return 2

    data = json.dumps({
        "menu_button": {
            "type": "web_app",
            "text": "Открыть Social Intelligence",
            "web_app": {"url": target},
        }
    }, ensure_ascii=False).encode("utf-8")
    conn = HTTPSConnection("api.telegram.org", timeout=15)
    try:
        conn.request(
            "POST",
            "/bot" + token + "/setChatMenuButton",
            body=data,
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        result = json.loads(response.read().decode("utf-8"))
        if response.status != 200 or not result.get("ok"):
            print("Telegram did not accept menu button. Check URL, bot token and Bot API status.", file=sys.stderr)
            return 1
        print("Telegram menu button configured successfully.")
        return 0
    except Exception:
        print("Unable to reach Telegram Bot API or set menu button.", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
