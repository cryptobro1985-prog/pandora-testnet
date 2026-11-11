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
from source_registry import capability_snapshot
from connectors import telegram_get_chat, telegram_get_chat_member, vk_users_get, vk_wall_get, vk_wall_comments, vk_likes_get_list, instagram_business_discovery, instagram_media_comments

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
