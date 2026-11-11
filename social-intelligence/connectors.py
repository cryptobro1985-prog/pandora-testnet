from __future__ import annotations
import os,re,asyncio,json,base64,subprocess,sys
from datetime import timezone
from typing import Any
import httpx
from public_parser import parse_profile,parse_post,page_route,has_embedded_data

TIMEOUT=20.0
HANDLE=re.compile(r"^[A-Za-z0-9._]{1,30}$")
HEADERS={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/156 Safari/537.36","Accept-Language":"en-US,en;q=0.9"}

def normalize_username(value:str)->str:
    v=(value or "").strip()
    v=re.sub(r"^https?://(www\.)?instagram\.com/","",v,flags=re.I)
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

async def _discover_meta_ig_user_id()->str|None:
    explicit=os.getenv("META_IG_USER_ID","").strip()
    if explicit: return explicit
    token=os.getenv("META_ACCESS_TOKEN","").strip()
    if not token: return None
    version=os.getenv("META_GRAPH_VERSION","v24.0")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            # Instagram-user tokens can identify the IG account directly.
            direct=await client.get("https://graph.facebook.com/"+version+"/me",params={
              "fields":"id,username,name,account_type",
              "access_token":token
            })
            direct_data=_safe_json(direct)
            if direct.status_code<400 and direct_data.get("id") and direct_data.get("username"):
                return str(direct_data["id"])
            # Facebook user/page tokens expose linked professional IG accounts through /me/accounts.
            r=await client.get("https://graph.facebook.com/"+version+"/me/accounts",params={
              "fields":"id,name,instagram_business_account{id,username}",
              "limit":100,
              "access_token":token
            })
        data=_safe_json(r)
        for page in data.get("data") or []:
            iga=page.get("instagram_business_account") if isinstance(page,dict) else None
            if isinstance(iga,dict) and iga.get("id"): return str(iga["id"])
    except Exception:
        pass
    return None

async def business_discovery(username:str)->dict[str,Any]:
    ig_user_id=await _discover_meta_ig_user_id()
    if not ig_user_id:
        return {"status":"not_configured","source":"meta_business_discovery","detail":"missing_or_undiscoverable_meta_ig_user_id"}
    fields=("business_discovery.username("+username+"){id,username,name,biography,website,followers_count,"
            "follows_count,media_count,profile_picture_url,media.limit(40){id,caption,comments_count,like_count,"
            "media_type,permalink,timestamp}}")
    return await meta_get(ig_user_id,{"fields":fields})

async def media_comments(media_id:str,limit:int=100)->dict[str,Any]:
    return await meta_get(media_id+"/comments",{"fields":"id,text,timestamp,username,like_count,replies{id,text,timestamp,username,like_count}","limit":max(1,min(limit,100))})

_PW_INSTALL_LOCK=asyncio.Lock()
_PW_READY=False

async def _ensure_playwright_browser():
    global _PW_READY
    if _PW_READY: return True
    async with _PW_INSTALL_LOCK:
        if _PW_READY: return True
        def install():
            return subprocess.run([sys.executable,"-m","playwright","install","chromium"],capture_output=True,text=True,timeout=180)
        r=await asyncio.to_thread(install)
        _PW_READY=(r.returncode==0)
        return _PW_READY

def _playwright_cookie_list():
    cookies=[]
    sessionid=os.getenv("IG_SESSIONID","").strip()
    csrf=os.getenv("IG_CSRFTOKEN","").strip()
    ds=os.getenv("IG_DS_USER_ID","").strip()
    mid=os.getenv("IG_MID","").strip()
    if sessionid: cookies.append({"name":"sessionid","value":sessionid,"domain":".instagram.com","path":"/","httpOnly":True,"secure":True,"sameSite":"Lax"})
    if csrf: cookies.append({"name":"csrftoken","value":csrf,"domain":".instagram.com","path":"/","secure":True,"sameSite":"Lax"})
    if ds: cookies.append({"name":"ds_user_id","value":ds,"domain":".instagram.com","path":"/","secure":True,"sameSite":"Lax"})
    if mid: cookies.append({"name":"mid","value":mid,"domain":".instagram.com","path":"/","secure":True,"sameSite":"Lax"})
    blob=os.getenv("IG_SESSION_JSON_B64","").strip()
    if blob:
        try:
            data=json.loads(base64.b64decode(blob).decode("utf-8"))
            if isinstance(data,dict):
                existing={x["name"] for x in cookies}
                for name,value in data.items():
                    if name in existing or value is None: continue
                    cookies.append({"name":str(name),"value":str(value),"domain":".instagram.com","path":"/","secure":True,"sameSite":"Lax"})
        except Exception:
            pass
    return cookies

async def playwright_public_collect(username:str,max_posts:int=12)->dict[str,Any]:
    """2scraper-style browser collector; uses the user's configured Instagram session when present."""
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return {"status":"unavailable","source":"playwright_public","detail":"playwright_not_installed"}
    try:
        if not await _ensure_playwright_browser():
            return {"status":"unavailable","source":"playwright_public","detail":"chromium_install_failed"}
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
            context=await browser.new_context(locale="en-US",user_agent=HEADERS["User-Agent"])
            auth_cookies=_playwright_cookie_list()
            if auth_cookies:
                await context.add_cookies(auth_cookies)
            page=await context.new_page()
            await page.goto("https://www.instagram.com/"+username+"/?hl=en",wait_until="domcontentloaded",timeout=45000)
            await page.wait_for_timeout(1500)
            html=await page.content()
            route=page_route(html)
            if route and "LoginHomepageRoute" in route:
                await context.close(); await browser.close()
                return {"status":"unavailable","source":"playwright_public","detail":"login_wall","route":route}
            if route and "ErrorRoute" in route:
                await context.close(); await browser.close()
                return {"status":"not_found","source":"playwright_public","detail":"profile_not_found","route":route}
            if route and "ProfileRoute" in route and not has_embedded_data(html):
                await context.close(); await browser.close()
                return {"status":"rate_limited","source":"playwright_public","detail":"profile_shell_without_embedded_data","route":route}
            prof=parse_profile(html,username)
            posts=[]
            if prof:
                for code in (prof.get("recent_post_codes") or [])[:max(0,min(max_posts,12))]:
                    try:
                        await page.goto("https://www.instagram.com/p/"+code+"/?hl=en",wait_until="domcontentloaded",timeout=45000)
                        await page.wait_for_timeout(1200)
                        parsed=parse_post(await page.content(),code)
                        if parsed: posts.append(parsed)
                    except Exception:
                        continue
            await context.close(); await browser.close()
        if not prof:
            return {"status":"partial","source":"playwright_public","detail":"embedded_profile_missing","profile":{},"posts":[]}
        return {"status":"ok","source":"playwright_public","profile":prof,"posts":posts}
    except Exception as e:
        return {"status":"unavailable","source":"playwright_public","detail":type(e).__name__}

async def public_embedded_collect(username:str,max_posts:int=12)->dict[str,Any]:
    """MIT 2scraper-inspired: read server-rendered application/json from logged-out pages."""
    profile_url="https://www.instagram.com/"+username+"/?hl=en"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT,follow_redirects=True,headers=HEADERS) as client:
            r=await client.get(profile_url)
            if r.status_code>=400:
                return {"status":"unavailable","source":"public_embedded","http_status":r.status_code}
            prof=parse_profile(r.text,username)
            if not prof:
                return {"status":"partial","source":"public_embedded","detail":"embedded_profile_missing","profile":{},"posts":[]}
            posts=[]
            codes=(prof.get("recent_post_codes") or [])[:max(0,min(max_posts,12))]
            for code in codes:
                try:
                    pr=await client.get("https://www.instagram.com/p/"+code+"/?hl=en")
                    if pr.status_code<400:
                        parsed=parse_post(pr.text,code)
                        if parsed: posts.append(parsed)
                except Exception:
                    continue
        return {"status":"ok","source":"public_embedded","profile":prof,"posts":posts}
    except Exception as e:
        return {"status":"unavailable","source":"public_embedded","detail":type(e).__name__}

async def public_profile(username:str)->dict[str,Any]:
    url="https://www.instagram.com/"+username+"/?hl=en"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT,follow_redirects=True,headers=HEADERS) as client:
            r=await client.get(url)
        if r.status_code>=400: return {"status":"unavailable","source":"public_page","http_status":r.status_code}
        text=r.text[:1500000]
        def m(prop):
            x=re.search(r'<meta[^>]+property=["\']'+prop+r'["\'][^>]+content=["\']([^"\']*)',text,re.I)
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
        session_json_b64=os.getenv("IG_SESSION_JSON_B64","").strip()
        cookie_sessionid=os.getenv("IG_SESSIONID","").strip()
        cookie_csrf=os.getenv("IG_CSRFTOKEN","").strip()
        cookie_ds=os.getenv("IG_DS_USER_ID","").strip()
        cookie_mid=os.getenv("IG_MID","").strip()
        authed=False
        if session_json_b64 and login_user:
            data=json.loads(base64.b64decode(session_json_b64).decode("utf-8"))
            if not isinstance(data,dict): raise ValueError("IG_SESSION_JSON_B64 must decode to a cookie dict")
            L.context.load_session(login_user,data); authed=bool(L.test_login())
        elif cookie_sessionid and cookie_csrf and login_user:
            data={"sessionid":cookie_sessionid,"csrftoken":cookie_csrf}
            if cookie_ds: data["ds_user_id"]=cookie_ds
            if cookie_mid: data["mid"]=cookie_mid
            L.context.load_session(login_user,data); authed=bool(L.test_login())
        elif session_b64 and login_user:
            import tempfile
            p=tempfile.NamedTemporaryFile(delete=False); p.write(base64.b64decode(session_b64)); p.close()
            try: L.load_session_from_file(login_user,p.name); authed=bool(L.test_login())
            finally:
                try: os.unlink(p.name)
                except OSError: pass
        elif session_file and login_user and os.path.exists(session_file):
            L.load_session_from_file(login_user,session_file); authed=bool(L.test_login())
        profile=instaloader.Profile.from_username(L.context,username)
        out={"status":"ok","source":"instaloader","profile":{"username":profile.username,"user_id":str(getattr(profile,"userid","")) or None,
             "name":profile.full_name or "","biography":profile.biography or "","followers_count":getattr(profile,"followers",None),
             "follows_count":getattr(profile,"followees",None),"media_count":getattr(profile,"mediacount",None),
             "profile_picture_url":str(profile.profile_pic_url) if profile.profile_pic_url else None,
             "is_verified":getattr(profile,"is_verified",None),"is_private":getattr(profile,"is_private",None)},
             "posts":[],"followers":None,"following":None,"warnings":[],"authenticated":authed}
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
                likes=[]
                for j,u in enumerate(post.get_likes()):
                    if j>=500: break
                    if getattr(u,"username",None): likes.append(u.username)
                row["likers"]=likes
            except Exception as e: out["warnings"].append("likes:"+post.shortcode+":"+type(e).__name__)
            out["posts"].append(row)
        if authed:
            try:
                followers=[]
                for i,u in enumerate(profile.get_followers()):
                    if i>=10000: break
                    followers.append({"pk":str(getattr(u,"userid",u.username)),"username":u.username,"full_name":getattr(u,"full_name","") or "","is_verified":bool(getattr(u,"is_verified",False))})
                out["followers"]=followers
            except Exception as e: out["warnings"].append("followers:"+type(e).__name__)
            try:
                following=[]
                for i,u in enumerate(profile.get_followees()):
                    if i>=10000: break
                    following.append({"pk":str(getattr(u,"userid",u.username)),"username":u.username,"full_name":getattr(u,"full_name","") or "","is_verified":bool(getattr(u,"is_verified",False))})
                out["following"]=following
            except Exception as e: out["warnings"].append("following:"+type(e).__name__)
        return out
    except Exception as e:
        return {"status":"unavailable","source":"instaloader","detail":type(e).__name__}

async def instaloader_collect(username:str,max_posts:int=30)->dict[str,Any]:
    return await asyncio.to_thread(_instaloader_collect,username,max_posts)
