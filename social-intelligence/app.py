"""Minimal privacy-preserving source verification API for Social Intelligence Mini App.

This does not infer ownership, identify people by photos, scrape private content,
enumerate memberships or produce people-tracking dossiers.
"""
from __future__ import annotations

import re
import os
import json
from http.client import HTTPSConnection
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from source_registry import capability_snapshot
from connectors import telegram_get_chat, telegram_get_chat_member, vk_users_get, vk_wall_get, vk_wall_comments, vk_likes_get_list, instagram_business_discovery, instagram_media_comments, public_profile_page

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

class SearchRequest(BaseModel):
    profiles: list[InputProfile] = Field(default_factory=list, max_length=12)

class TelegramChatRequest(BaseModel):
    chat_id: str = Field(min_length=2, max_length=128)

class TelegramMemberRequest(TelegramChatRequest):
    user_id: int

class VKUserRequest(BaseModel):
    user_ids: str = Field(min_length=1, max_length=512)

class VKWallRequest(BaseModel):
    owner_id: str
    count: int = 30

class VKCommentsRequest(BaseModel):
    owner_id: str
    post_id: int
    count: int = 100

class VKLikesRequest(BaseModel):
    owner_id: str
    item_id: int
    item_type: str = "post"
    count: int = 100

class IGDiscoveryRequest(BaseModel):
    ig_user_id: str = Field(min_length=1, max_length=64)
    username: str = Field(min_length=1, max_length=64)

class IGCommentsRequest(BaseModel):
    media_id: str = Field(min_length=1, max_length=128)
    limit: int = 100


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



TELEGRAM_STATUS = {"configured": False, "menu_button": False, "bot_username": None, "error": None}

def _telegram_api_call(token: str, method: str, payload: dict | None = None) -> dict:
    conn = HTTPSConnection("api.telegram.org", timeout=15)
    try:
        body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        conn.request(
            "POST",
            "/bot" + token + "/" + method,
            body=body,
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        data = json.loads(response.read().decode("utf-8", "replace"))
        if response.status != 200 or not data.get("ok"):
            raise RuntimeError("Telegram Bot API rejected " + method)
        return data
    finally:
        conn.close()

def configure_telegram_menu_on_startup() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    target = os.getenv("MINIAPP_URL", "").strip()
    TELEGRAM_STATUS.update({"configured": False, "menu_button": False, "bot_username": None, "error": None})
    if not token or not target.startswith("https://"):
        TELEGRAM_STATUS["error"] = "missing_token_or_url"
        return
    try:
        me = _telegram_api_call(token, "getMe")
        username = (me.get("result") or {}).get("username")
        TELEGRAM_STATUS["configured"] = True
        TELEGRAM_STATUS["bot_username"] = username
        _telegram_api_call(token, "setChatMenuButton", {
            "menu_button": {
                "type": "web_app",
                "text": "Открыть Social Intelligence",
                "web_app": {"url": target},
            }
        })
        TELEGRAM_STATUS["menu_button"] = True
    except Exception:
        TELEGRAM_STATUS["error"] = "telegram_api_error"

@app.on_event("startup")
def startup_configure_telegram_menu():
    configure_telegram_menu_on_startup()
    print("telegram_bot_status_startup=" + json.dumps(TELEGRAM_STATUS, ensure_ascii=False))

@app.get("/api/telegram/bot-status")
def telegram_bot_status():
    return TELEGRAM_STATUS

@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "service": "social-intelligence", "version": "0.2.0"}


@app.get("/api/capabilities")
def capabilities():
    return capability_snapshot()



@app.post("/api/telegram/chat")
async def api_telegram_chat(payload: TelegramChatRequest):
    return await telegram_get_chat(payload.chat_id)

@app.post("/api/telegram/member")
async def api_telegram_member(payload: TelegramMemberRequest):
    return await telegram_get_chat_member(payload.chat_id, payload.user_id)

@app.post("/api/vk/user")
async def api_vk_user(payload: VKUserRequest):
    return await vk_users_get(payload.user_ids)

@app.post("/api/vk/wall")
async def api_vk_wall(payload: VKWallRequest):
    return await vk_wall_get(payload.owner_id, payload.count)

@app.post("/api/vk/comments")
async def api_vk_comments(payload: VKCommentsRequest):
    return await vk_wall_comments(payload.owner_id, payload.post_id, payload.count)

@app.post("/api/vk/likes")
async def api_vk_likes(payload: VKLikesRequest):
    return await vk_likes_get_list(payload.owner_id, payload.item_id, payload.item_type, payload.count)

@app.post("/api/instagram/business-discovery")
async def api_ig_discovery(payload: IGDiscoveryRequest):
    return await instagram_business_discovery(payload.ig_user_id, payload.username)

@app.post("/api/instagram/comments")
async def api_ig_comments(payload: IGCommentsRequest):
    return await instagram_media_comments(payload.media_id, payload.limit)

@app.post("/api/search")
async def search(payload: SearchRequest):
    """Run a real best-effort public lookup for supplied social profile URLs.

    The endpoint returns only data available from the supplied public profile page
    and configured official APIs. It does not enumerate hidden relationships or
    reconstruct private activity histories.
    """
    import asyncio
    capabilities = capability_snapshot()["platforms"]

    async def one(item: InputProfile):
        try:
            normalized = normalize_profile(item.platform, item.url)
        except ValueError as exc:
            return {"platform": item.platform, "status": "invalid", "reason": str(exc)}

        handle = [p for p in urlsplit(normalized).path.split("/") if p][0]
        public_task = public_profile_page(normalized)
        api_task = None

        if item.platform == "telegram" and capabilities["telegram"]["configured"]:
            api_task = telegram_get_chat("@" + handle)
        elif item.platform == "vk" and capabilities["vk"]["configured"]:
            api_task = vk_users_get(handle)
        elif item.platform == "instagram" and capabilities["instagram"]["configured"]:
            ig_user_id = os.getenv("META_IG_USER_ID", "").strip()
            if ig_user_id:
                api_task = instagram_business_discovery(ig_user_id, handle)

        public_result = await public_task
        api_result = await api_task if api_task else {"status": "not_configured"}

        return {
            "platform": item.platform,
            "status": "complete",
            "url": normalized,
            "handle": handle,
            "public": public_result,
            "api": api_result,
            "api_configured": bool(capabilities[item.platform]["configured"]),
        }

    results = await asyncio.gather(*(one(item) for item in payload.profiles))
    return {
        "status": "complete",
        "results": results,
        "capabilities": capabilities,
        "notice": "Best-effort lookup of supplied public profile URLs and configured official APIs only.",
    }

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
