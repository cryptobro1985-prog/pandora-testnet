from __future__ import annotations
import os, re, asyncio
from datetime import timezone
from typing import Any
import httpx

TIMEOUT=20.0
HANDLE=re.compile(r"^[A-Za-z0-9._]{1,30}$")

def normalize_username(value:str)->str:
    v=(value or "").strip()
    v=re.sub(r"^https?://(www\\.)?instagram\\.com/","",v,flags=re.I)
    v=v.split("?")[0].strip("/")
    if v.startswith("@"): v=v[1:]
    if "/" in v: v=v.split("/")[0]
    if not HANDLE.fullmatch(v): raise ValueError("Некорректный Instagram username/URL")
    return v

def _safe_json(resp:httpx.Response)->dict[str,Any]:
    try:
        d=resp.json(); return d if isinstance(d,dict) else {"data":d}
    except Exception: return {"error":"non_json_response","status_code":resp.status_code}

async def meta_get(path:str,params:dict[str,Any]|None=None)->dict[str,Any]:
    token=os.getenv("META_ACCESS_TOKEN","").strip()
    if not token: return {"status":"not_configured","source":"meta_graph"}
    version=os.getenv("META_GRAPH_VERSION","v24.0")
    q=dict(params or {}); q["access_token"]=token
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r=await client.get("https://graph.facebook.com/"+version+"/"+path.lstrip("/"),params=q)
    data=_safe_json(r)
    if "error" in data:
        e=data.get("error") or {}
        return {"status":"unavailable","source":"meta_graph","detail":e.get("message","Meta Graph API error"),"code":e.get("code")}
    return {"status":"ok","source":"meta_graph","response":data}

async def business_discovery(username:str)->dict[str,Any]:
    ig_user_id=os.getenv("META_IG_USER_ID","").strip()
    if not ig_user_id: return {"status":"not_configured","source":"meta_business_discovery"}
    fields=("business_discovery.username("+username+"){id,username,name,biography,website,followers_count,"
            "follows_count,media_count,profile_picture_url,media.limit(40){id,caption,comments_count,like_count,"
            "media_type,permalink,timestamp}}")
    return await meta_get(ig_user_id,{"fields":fields})

async def media_comments(media_id:str,limit:int=100)->dict[str,Any]:
    return await meta_get(media_id+"/comments",{"fields":"id,text,timestamp,username,like_count,replies{id,text,timestamp,username,like_count}","limit":max(1,min(limit,100))})

async def public_profile(username:str)->dict[str,Any]:
    url="https://www.instagram.com/"+username+"/"
    headers={"User-Agent":"Mozilla/5.0","Accept-Language":"en-US,en;q=0.9"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT,follow_redirects=True,headers=headers) as client:
            r=await client.get(url)
        if r.status_code>=400: return {"status":"unavailable","source":"public_page","http_status":r.status_code}
        text=r.text[:1000000]
        def m(prop):
            x=re.search(r'<meta[^>]+property=["\\\']'+prop+r'["\\\'][^>]+content=["\\\']([^"\\\']*)',text,re.I)
            return x.group(1) if x else ""
        return {"status":"ok","source":"public_page","url":str(r.url),"title":m("og:title"),"description":m("og:description"),"image":m("og:image")}
    except Exception as e:
        return {"status":"unavailable","source":"public_page","detail":type(e).__name__}

def _instaloader_collect(username:str,max_posts:int=30)->dict[str,Any]:
    try:
        import instaloader
        L=instaloader.Instaloader(download_pictures=False,download_videos=False,download_video_thumbnails=False,save_metadata=False,compress_json=False,quiet=True)
        login_user=os.getenv("IG_USERNAME","").strip()
        session_file=os.getenv("IG_SESSIONFILE","").strip()
        session_b64=os.getenv("IG_SESSION_B64","").strip()
        if session_b64 and login_user:
            import base64,tempfile
            p=tempfile.NamedTemporaryFile(delete=False); p.write(base64.b64decode(session_b64)); p.close()
            try: L.load_session_from_file(login_user,p.name)
            finally:
                try: os.unlink(p.name)
                except OSError: pass
        elif session_file and login_user and os.path.exists(session_file):
            L.load_session_from_file(login_user,session_file)
        profile=instaloader.Profile.from_username(L.context,username)
        out={"status":"ok","source":"instaloader","profile":{"username":profile.username,"name":profile.full_name or "",
             "biography":profile.biography or "","followers_count":getattr(profile,"followers",None),
             "follows_count":getattr(profile,"followees",None),"media_count":getattr(profile,"mediacount",None),
             "profile_picture_url":str(profile.profile_pic_url) if profile.profile_pic_url else None,
             "is_verified":getattr(profile,"is_verified",None)},"posts":[],"followers":[],"following":[],"warnings":[]}
        for i,post in enumerate(profile.get_posts()):
            if i>=max_posts: break
            row={"id":post.mediaid,"shortcode":post.shortcode,"permalink":"https://www.instagram.com/p/"+post.shortcode+"/",
                 "timestamp":post.date_utc.replace(tzinfo=timezone.utc).isoformat(),"caption":post.caption or "",
                 "like_count":getattr(post,"likes",None),"comments_count":getattr(post,"comments",None),"comments_detail":[],"likers":[]}
            try:
                for j,c in enumerate(post.get_comments()):
                    if j>=250: break
                    actor=getattr(getattr(c,"owner",None),"username",None)
                    if actor: row["comments_detail"].append({"username":actor,"text":c.text or "","timestamp":c.created_at_utc.replace(tzinfo=timezone.utc).isoformat() if c.created_at_utc else None})
            except Exception as e: out["warnings"].append("comments:"+post.shortcode+":"+type(e).__name__)
            try:
                for j,u in enumerate(post.get_likes()):
                    if j>=500: break
                    if getattr(u,"username",None): row["likers"].append(u.username)
            except Exception as e: out["warnings"].append("likes:"+post.shortcode+":"+type(e).__name__)
            out["posts"].append(row)
        try:
            for i,u in enumerate(profile.get_followers()):
                if i>=10000: break
                out["followers"].append(u.username)
        except Exception as e: out["warnings"].append("followers:"+type(e).__name__)
        try:
            for i,u in enumerate(profile.get_followees()):
                if i>=10000: break
                out["following"].append(u.username)
        except Exception as e: out["warnings"].append("following:"+type(e).__name__)
        return out
    except Exception as e:
        return {"status":"unavailable","source":"instaloader","detail":type(e).__name__}

async def instaloader_collect(username:str,max_posts:int=30)->dict[str,Any]:
    return await asyncio.to_thread(_instaloader_collect,username,max_posts)
