"""Minimal privacy-preserving source verification API for Social Intelligence Mini App.

This does not infer ownership, identify people by photos, scrape private content,
enumerate memberships or produce people-tracking dossiers.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Social Intelligence Mini App", version="0.1.0")
WEB = Path(__file__).resolve().parent / "web"

PLATFORMS = {
    "instagram": {"instagram.com", "www.instagram.com"},
    "vk": {"vk.com", "www.vk.com"},
    "telegram": {"t.me", "telegram.me"},
}
HANDLE = re.compile(r"^[a-zA-Z0-9_.]{2,64}$")
VK_HANDLE = re.compile(r"^[a-zA-Z0-9_.-]{2,64}$")


class InputProfile(BaseModel):
    platform: Literal["instagram", "vk", "telegram"]
    url: str = Field(min_length=8, max_length=500)


class AnalyzeRequest(BaseModel):
    authorized: bool = False
    profiles: list[InputProfile] = Field(default_factory=list, max_length=12)


def normalize_profile(platform: str, raw_url: str) -> str:
    try:
        url = urlsplit(raw_url.strip())
        host = (url.hostname or "").lower().rstrip(".")
        if url.scheme not in {"http", "https"} or host not in PLATFORMS[platform]:
            raise ValueError("Only official social-profile HTTPS links are accepted")
        if url.username or url.password or url.port:
            raise ValueError("User info and custom ports are not supported")
        parts = [part for part in url.path.split("/") if part]
        if len(parts) != 1:
            raise ValueError("Enter a direct public-profile link, not a post or chat")
        handle = parts[0]
        valid = (VK_HANDLE if platform == "vk" else HANDLE).fullmatch(handle)
        if not valid or handle.lower() in {
            "explore", "reels", "reel", "p", "stories",
            "joinchat", "addstickers", "share", "login", "settings",
        } or handle.startswith("+"):
            raise ValueError("Invalid or non-profile link")
        canonical_host = {"instagram": "instagram.com", "vk": "vk.com", "telegram": "t.me"}[platform]
        return urlunsplit(("https", canonical_host, "/" + handle, "", ""))
    except (ValueError, KeyError) as exc:
        raise ValueError(str(exc)) from exc


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "service": "social-intelligence", "version": "0.1.0"}


@app.post("/api/analyze")
def analyze(payload: AnalyzeRequest):
    if not payload.authorized:
        raise HTTPException(status_code=403, detail="Confirm your rights to check this information")
    results = []
    for item in payload.profiles:
        try:
            normalized = normalize_profile(item.platform, item.url)
        except ValueError as exc:
            results.append({"platform": item.platform, "status": "invalid", "reason": str(exc)})
            continue
        results.append({
            "platform": item.platform,
            "status": "link_verified",
            "url": normalized,
            "source": "user_supplied",
            "note": "Link format verified only; account ownership, content and activity not verified",
        })
    return {
        "status": "complete",
        "profiles": results,
        "data_access": "user_supplied_links_only",
        "unsupported": [
            "hidden_memberships", "private_messages", "profile_viewers",
            "location_history", "deleted_likes", "third_party_phone_history",
            "dating_profile_discovery", "face_identification",
        ],
        "notice": "No personal details are stored, scraped, or inferred by this MVP.",
    }
