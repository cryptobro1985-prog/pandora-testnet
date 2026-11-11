#!/usr/bin/env python3
"""Convert an owner-authorized browser cookie export or Playwright storage state
into a base64 environment value for Instagram Intelligence.

This helper runs locally. It does not log in, request a password, or send cookies
anywhere. The resulting value is sensitive and should be placed directly into
the Render environment, not committed to git or pasted into chats.
"""
from __future__ import annotations
import argparse,base64,json
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument("input",help="JSON cookie export or Playwright storage_state JSON")
    p.add_argument("--mode",choices=["cookies","storage"],default="cookies")
    args=p.parse_args()
    raw=Path(args.input).read_text(encoding="utf-8")
    data=json.loads(raw)
    if args.mode=="cookies":
        if isinstance(data,dict) and "cookies" in data and isinstance(data["cookies"],list):
            data=data["cookies"]
        if not isinstance(data,(dict,list)):
            raise SystemExit("Cookie export must be a JSON object or list")
        name="IG_SESSION_JSON_B64"
    else:
        if not isinstance(data,dict) or "cookies" not in data:
            raise SystemExit("Playwright storage state must contain a cookies array")
        name="IG_BROWSER_STORAGE_STATE_B64"
    payload=base64.b64encode(json.dumps(data,separators=(",",":"),ensure_ascii=False).encode()).decode()
    print(name+"="+payload)
    print("\nSensitive value: set it directly in Render Environment; do not commit it.")

if __name__=="__main__":
    main()
