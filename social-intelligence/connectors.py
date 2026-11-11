"""Official/public source connector scaffolding.

Only calls platform APIs for data those APIs actually expose. No private-message
access, no hidden membership enumeration, no viewer deanonymization, no secret
follow/like history reconstruction.
"""
from __future__ import annotations
import os
from typing import Any
import httpx

TIMEOUT = 15.0

def _token(name:str)->str:
    return os.getenv(name,"").strip()

def _safe_json(resp:httpx.Response)->dict[str,Any]:
    try:
        data=resp.json()
        return data if isinstance(data,dict) else {"data":data}
    except Exception:
        return {"error":"non_json_response","status_code":resp.status_code}

async def telegram_get_chat(chat_id:str)->dict[str,Any]:
    token=_token("TELEGRAM_BOT_TOKEN")
    if not token:
        return {"status":"not_configured"}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r=await client.get(f"https://api.telegram.org/bot{token}/getChat",params={"chat_id":chat_id})
    data=_safe_json(r)
    if not data.get("ok"):
        return {"status":"unavailable","detail":data.get("description","Telegram API error")}
    result=data.get("result",{})
    return {"status":"ok","chat":{"id":result.get("id"),"type":result.get("type"),"title":result.get("title"),"username":result.get("username"),"description":result.get("description")}}

async def telegram_get_chat_member(chat_id:str,user_id:int)->dict[str,Any]:
    token=_token("TELEGRAM_BOT_TOKEN")
    if not token:
        return {"status":"not_configured"}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r=await client.get(f"https://api.telegram.org/bot{token}/getChatMember",params={"chat_id":chat_id,"user_id":user_id})
    data=_safe_json(r)
    if not data.get("ok"):
        return {"status":"unavailable","detail":data.get("description","Telegram API error")}
    result=data.get("result",{})
    return {"status":"ok","member":{"status":result.get("status"),"user":result.get("user")}}

async def vk_call(method:str, params:dict[str,Any])->dict[str,Any]:
    token=_token("VK_ACCESS_TOKEN")
    if not token:
        return {"status":"not_configured"}
    api_version=os.getenv("VK_API_VERSION","5.199")
    full=dict(params)
    full.update({"access_token":token,"v":api_version})
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r=await client.get(f"https://api.vk.com/method/{method}",params=full)
    data=_safe_json(r)
    if "error" in data:
        err=data["error"] if isinstance(data["error"],dict) else {}
        return {"status":"unavailable","error_code":err.get("error_code"),"detail":err.get("error_msg","VK API error")}
    return {"status":"ok","response":data.get("response")}

async def vk_users_get(user_ids:str)->dict[str,Any]:
    return await vk_call("users.get",{"user_ids":user_ids,"fields":"photo_200,city,country,education,universities,schools,career,domain,status,site,verified"})

async def vk_wall_get(owner_id:str,count:int=30)->dict[str,Any]:
    return await vk_call("wall.get",{"owner_id":owner_id,"count":max(1,min(count,100)),"extended":1})

async def vk_wall_comments(owner_id:str,post_id:int,count:int=100)->dict[str,Any]:
    return await vk_call("wall.getComments",{"owner_id":owner_id,"post_id":post_id,"count":max(1,min(count,100)),"extended":1,"thread_items_count":10})

async def vk_likes_get_list(owner_id:str,item_id:int,item_type:str="post",count:int=100)->dict[str,Any]:
    allowed={"post","comment","photo","video","note","market","photo_comment","video_comment","topic_comment","market_comment"}
    if item_type not in allowed:
        return {"status":"invalid","detail":"unsupported VK like object type"}
    return await vk_call("likes.getList",{"type":item_type,"owner_id":owner_id,"item_id":item_id,"count":max(1,min(count,1000)),"extended":1})

async def meta_get(path:str, params:dict[str,Any]|None=None)->dict[str,Any]:
    token=_token("META_ACCESS_TOKEN")
    if not token:
        return {"status":"not_configured"}
    version=os.getenv("META_GRAPH_VERSION","v24.0")
    q=dict(params or {})
    q["access_token"]=token
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r=await client.get(f"https://graph.facebook.com/{version}/{path.lstrip('/')}",params=q)
    data=_safe_json(r)
    if "error" in data:
        err=data.get("error") or {}
        return {"status":"unavailable","detail":err.get("message","Meta Graph API error"),"code":err.get("code")}
    return {"status":"ok","response":data}

async def instagram_business_discovery(ig_user_id:str, username:str)->dict[str,Any]:
    fields="business_discovery.username("+username+"){id,username,name,biography,website,followers_count,follows_count,media_count,profile_picture_url,media.limit(25){id,caption,comments_count,like_count,media_type,permalink,timestamp}}"
    return await meta_get(ig_user_id,{"fields":fields})

async def instagram_media_comments(media_id:str,limit:int=100)->dict[str,Any]:
    return await meta_get(f"{media_id}/comments",{"fields":"id,text,timestamp,username,like_count,replies{id,text,timestamp,username,like_count}","limit":max(1,min(limit,100))})


from html.parser import HTMLParser

class _MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self._in_title = False
        self.meta = {}
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() == "meta":
            key = (attrs.get("property") or attrs.get("name") or "").lower()
            value = attrs.get("content")
            if key and value:
                self.meta[key] = value[:2000]
    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self._in_title = False
    def handle_data(self, data):
        if self._in_title and len(self.title) < 500:
            self.title += data

async def public_profile_page(url: str) -> dict[str, Any]:
    """Fetch public page metadata only for a prevalidated social-profile URL."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; SocialIntelligenceMVP/0.3; +https://social-intelligence-miniapp-mvp.onrender.com)",
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, headers=headers) as client:
            r = await client.get(url)
        ctype = (r.headers.get("content-type") or "").lower()
        if r.status_code >= 400:
            return {"status": "unavailable", "http_status": r.status_code, "detail": "public page did not return a readable profile"}
        if "text/html" not in ctype:
            return {"status": "unavailable", "http_status": r.status_code, "detail": "public page was not HTML"}
        text = r.text[:1_000_000]
        parser = _MetaParser()
        parser.feed(text)
        title = (parser.meta.get("og:title") or parser.title or "").strip()
        description = (parser.meta.get("og:description") or parser.meta.get("description") or "").strip()
        image = (parser.meta.get("og:image") or "").strip()
        canonical = str(r.url)
        return {
            "status": "ok",
            "url": canonical,
            "title": title[:500],
            "description": description[:2000],
            "image": image[:2000],
            "source": "public_profile_page",
        }
    except Exception:
        return {"status": "unavailable", "detail": "public page request failed"}


from bs4 import BeautifulSoup
from datetime import datetime, timezone

async def public_telegram_feed(username: str, limit: int = 30) -> dict[str, Any]:
    username = username.lstrip("@").strip()
    if not username:
        return {"status": "invalid", "items": []}
    url = f"https://t.me/s/{username}"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; SocialIntelligenceMVP/0.4)"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, headers=headers) as client:
            r = await client.get(url)
        if r.status_code >= 400:
            return {"status":"unavailable","items":[],"http_status":r.status_code}
        soup = BeautifulSoup(r.text, "html.parser")
        items=[]
        for msg in soup.select(".tgme_widget_message_wrap")[-max(1,min(limit,100)):]:
            node = msg.select_one(".tgme_widget_message")
            text_node = msg.select_one(".tgme_widget_message_text")
            time_node = msg.select_one("time")
            views_node = msg.select_one(".tgme_widget_message_views")
            link_node = msg.select_one(".tgme_widget_message_date")
            if not node:
                continue
            post = node.get("data-post") or ""
            author = node.get("data-peer") or username
            dt = time_node.get("datetime") if time_node else None
            href = link_node.get("href") if link_node else (f"https://t.me/{post}" if post else None)
            items.append({
                "title": f"@{author}",
                "text": (text_node.get_text(" ", strip=True) if text_node else "")[:2000],
                "when": dt,
                "views": views_node.get_text(" ", strip=True) if views_node else None,
                "url": href,
            })
        return {"status":"ok","items":items,"source":url}
    except Exception:
        return {"status":"unavailable","items":[],"detail":"public Telegram feed request failed"}

async def public_vk_wall(handle: str, limit: int = 20) -> dict[str, Any]:
    handle = handle.strip().lstrip("/")
    if not handle:
        return {"status":"invalid","items":[]}
    url=f"https://vk.com/{handle}"
    headers={"User-Agent":"Mozilla/5.0 (compatible; SocialIntelligenceMVP/0.4)"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, headers=headers) as client:
            r=await client.get(url)
        if r.status_code>=400:
            return {"status":"unavailable","items":[],"http_status":r.status_code}
        soup=BeautifulSoup(r.text,"html.parser")
        items=[]
        selectors=["div._post","div.post","div[data-post-id]"]
        seen=set()
        for sel in selectors:
            for post in soup.select(sel):
                pid=post.get("id") or post.get("data-post-id") or ""
                if pid in seen: continue
                seen.add(pid)
                text_node=post.select_one(".wall_post_text, .post_text, [data-testid='wall_post_text']")
                time_node=post.select_one("time, .rel_date, .post_date")
                like_node=post.select_one(".PostBottomAction--like .PostBottomAction__count, .like_btns .like_button_count")
                comments_node=post.select_one(".PostBottomAction--comment .PostBottomAction__count, .reply_link")
                href=None
                if pid.startswith("post"):
                    wall_id=pid[4:]
                    href=f"https://vk.com/wall{wall_id}"
                txt=text_node.get_text(" ",strip=True) if text_node else ""
                if not txt and not pid: continue
                items.append({
                    "title":"Публикация VK",
                    "text":txt[:2000],
                    "when":time_node.get("datetime") if time_node and time_node.get("datetime") else (time_node.get_text(" ",strip=True) if time_node else None),
                    "likes":like_node.get_text(" ",strip=True) if like_node else None,
                    "comments":comments_node.get_text(" ",strip=True) if comments_node else None,
                    "url":href or url,
                })
                if len(items)>=limit: break
            if items: break
        return {"status":"ok","items":items,"source":url}
    except Exception:
        return {"status":"unavailable","items":[],"detail":"public VK wall request failed"}


async def public_instagram_feed(username: str, limit: int = 24) -> dict[str, Any]:
    username = username.strip().lstrip("@")
    if not username:
        return {"status":"invalid","items":[]}
    url=f"https://www.instagram.com/{username}/"
    headers={
        "User-Agent":"Mozilla/5.0 (compatible; SocialIntelligenceMVP/0.5)",
        "Accept-Language":"en-US,en;q=0.9",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, headers=headers) as client:
            r=await client.get(url)
        if r.status_code>=400:
            return {"status":"unavailable","items":[],"http_status":r.status_code}
        soup=BeautifulSoup(r.text,"html.parser")
        items=[]
        seen=set()
        for a in soup.select('a[href^="/p/"], a[href^="/reel/"]'):
            href=a.get("href") or ""
            if not href or href in seen:
                continue
            seen.add(href)
            img=a.select_one("img")
            text=(img.get("alt") if img else "") or a.get_text(" ",strip=True)
            items.append({
                "title":"Публикация Instagram" if href.startswith("/p/") else "Reel Instagram",
                "text":text[:1000],
                "when":None,
                "url":"https://www.instagram.com"+href,
            })
            if len(items)>=max(1,min(limit,50)):
                break
        return {"status":"ok","items":items,"source":url}
    except Exception:
        return {"status":"unavailable","items":[],"detail":"public Instagram feed request failed"}
