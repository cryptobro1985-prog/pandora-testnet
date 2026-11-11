from __future__ import annotations
import os,json,io,zipfile
from pathlib import Path
from datetime import datetime,timezone
from fastapi import FastAPI,Response,HTTPException
from fastapi.responses import FileResponse,PlainTextResponse,StreamingResponse
from pydantic import BaseModel,Field
from connectors import normalize_username,business_discovery,media_comments,public_profile,public_embedded_collect,playwright_public_collect,instaloader_collect,warm_playwright
from analysis import build_events,relationship_report,audience_quality,graph_payload,timeline
from storage import init_schema,get_last_snapshot,save_snapshot,begin_run,finish_run,save_posts,save_events,history,backend_info,save_bridge_payload,get_latest_bridge_payload

app=FastAPI(title="Instagram Intelligence",version="2.1.0")
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware,allow_origins=["https://www.instagram.com","https://instagram.com"],allow_credentials=False,allow_methods=["POST","OPTIONS"],allow_headers=["*"])
WEB=Path(__file__).resolve().parent/"web"

class ScanRequest(BaseModel):
    query:str=Field(min_length=1,max_length=300)
    max_posts:int=Field(default=30,ge=1,le=60)

class BridgePayload(BaseModel):
    username:str=Field(min_length=1,max_length=30)
    profile:dict={}
    followers:list[dict]=Field(default_factory=list,max_length=20000)
    following:list[dict]=Field(default_factory=list,max_length=20000)
    posts:list[dict]=Field(default_factory=list,max_length=100)
    source:str="browser_bridge"

def _state(items):
    if items is None: return {"observed":False,"items":[]}
    return {"observed":True,"items":items}

def _decode_state(raw):
    if not raw: return {"observed":False,"items":[]}
    try: value=json.loads(raw)
    except Exception: return {"observed":False,"items":[]}
    if isinstance(value,dict) and "observed" in value:
        return {"observed":bool(value.get("observed")),"items":value.get("items") or []}
    if isinstance(value,list):
        return {"observed":bool(value),"items":value}
    return {"observed":False,"items":[]}

def _identity_map(items):
    out={}
    for item in items or []:
        if isinstance(item,dict):
            key=str(item.get("pk") or item.get("id") or item.get("username") or "").strip()
            label=str(item.get("username") or key).strip()
        else:
            key=label=str(item).strip()
        if key: out[key]=label
    return out

def snapshot(username,followers,following,profile):
    now=datetime.now(timezone.utc).isoformat()
    prev=get_last_snapshot(username)
    current_f=_state(followers); current_g=_state(following)
    d={"new_followers":[],"lost_followers":[],"new_following":[],"unfollowed":[],"previous_snapshot":None,
       "followers_observed":current_f["observed"],"following_observed":current_g["observed"]}
    if prev:
        old_f=_decode_state(prev["followers_json"]); old_g=_decode_state(prev["following_json"])
        if current_f["observed"] and old_f["observed"]:
            old=_identity_map(old_f["items"]); cur=_identity_map(current_f["items"])
            d["new_followers"]=sorted(cur[k] for k in cur.keys()-old.keys())
            d["lost_followers"]=sorted(old[k] for k in old.keys()-cur.keys())
        if current_g["observed"] and old_g["observed"]:
            old=_identity_map(old_g["items"]); cur=_identity_map(current_g["items"])
            d["new_following"]=sorted(cur[k] for k in cur.keys()-old.keys())
            d["unfollowed"]=sorted(old[k] for k in old.keys()-cur.keys())
        d["previous_snapshot"]=prev["created_at"]
    save_snapshot(username,now,json.dumps(current_f,ensure_ascii=False),json.dumps(current_g,ensure_ascii=False),json.dumps(profile,ensure_ascii=False))
    d["snapshot_at"]=now
    return d

def _post_key(p):
    return str(p.get("shortcode") or p.get("permalink") or p.get("id") or "")

def _merge_posts(*groups):
    merged={}
    for group in groups:
        for p in group or []:
            key=_post_key(p)
            if not key: continue
            if key not in merged: merged[key]=dict(p)
            else:
                cur=merged[key]
                for k,v in p.items():
                    if v not in (None,"",[],{}) and cur.get(k) in (None,"",[],{}): cur[k]=v
                    elif k in ("comments_detail","likers","mentions","hashtags","tagged_users","coauthors") and v:
                        old=cur.get(k) or []
                        if k=="comments_detail":
                            seen={(x.get("username"),x.get("timestamp"),x.get("text")) for x in old if isinstance(x,dict)}
                            for x in v:
                                sig=(x.get("username"),x.get("timestamp"),x.get("text")) if isinstance(x,dict) else (str(x),None,None)
                                if sig not in seen: old.append(x);seen.add(sig)
                            cur[k]=old
                        else: cur[k]=list(dict.fromkeys(old+v))
    return list(merged.values())

async def _bounded(coro,source,timeout=22):
    import asyncio
    try: return await asyncio.wait_for(coro,timeout=timeout)
    except asyncio.TimeoutError: return {"status":"unavailable","source":source,"detail":"timeout"}
    except Exception as e: return {"status":"unavailable","source":source,"detail":type(e).__name__}

@app.on_event("startup")
async def startup():
    init_schema()
    import asyncio,logging
    if os.getenv("IG_PREWARM_PLAYWRIGHT","").strip().lower() in ("1","true","yes","on"):
        async def warm_runner():
            warm=await warm_playwright()
            logging.getLogger("uvicorn.error").warning("playwright_warmup=%s",json.dumps(warm))
        asyncio.create_task(warm_runner())
    target=os.getenv("IG_STARTUP_SMOKE_TARGET","").strip()
    if target:
        async def runner():
            try:
                result=await asyncio.wait_for(scan(ScanRequest(query=target,max_posts=8)),timeout=90)
                logging.getLogger("uvicorn.error").warning("instagram_smoke_test=%s",json.dumps({
                    "username":result.get("username"),"posts":len(result.get("posts") or []),"events":len(result.get("events") or []),
                    "relationships":len(result.get("relationships") or []),"sources":result.get("sources"),"warnings":(result.get("warnings") or [])[:8]
                },ensure_ascii=False))
            except Exception as e:
                logging.getLogger("uvicorn.error").warning("instagram_smoke_test_error=%s:%s",type(e).__name__,str(e)[:300])
        asyncio.create_task(runner())

@app.head("/")
def head(): return Response(status_code=200)

@app.get("/")
def index(): return FileResponse(WEB/"index.html",headers={"Cache-Control":"no-store"})

@app.get("/api/health")
def health(): return {"ok":True,"service":"instagram-intelligence","version":"2.1.0","storage":backend_info()}

@app.get("/api/capabilities")
def capabilities():
    return {"instagram_only":True,
      "collectors":["browser_bridge_authorized","2scraper_playwright_public","2scraper_public_embedded","instaloader","meta_business_discovery","public_page_fallback"],
      "open_source_components":["2scraper/instagram-scraper","instaloader/instaloader","JuaniVeltri/igstalker","mohammedelahmar/InstaTrack","ignromanov/safe-unfollow"],
      "meta_configured":bool(os.getenv("META_ACCESS_TOKEN") and os.getenv("META_IG_USER_ID")),
      "instaloader_session_configured":bool(os.getenv("IG_USERNAME") and (os.getenv("IG_SESSIONFILE") or os.getenv("IG_SESSION_B64") or os.getenv("IG_SESSION_JSON_B64") or os.getenv("IG_SESSIONID"))),
      "not_observable":["profile_viewer_identities","profiles_viewed_by_target","private_messages"]}

@app.post("/api/bridge/ingest")
def bridge_ingest(payload:BridgePayload):
    username=normalize_username(payload.username)
    p=dict(payload.profile or {})
    p["username"]=username
    clean=lambda xs:[x for x in xs if isinstance(x,dict) and (x.get("pk") or x.get("id") or x.get("username"))]
    data={"username":username,"profile":p,"followers":clean(payload.followers)[:20000],"following":clean(payload.following)[:20000],
          "posts":[x for x in payload.posts if isinstance(x,dict)][:100],"source":"browser_bridge"}
    at=save_bridge_payload(username,data)
    return {"ok":True,"username":username,"stored_at":at,"followers":len(data["followers"]),"following":len(data["following"]),"posts":len(data["posts"])}

@app.get("/api/bridge/latest/{username}")
def bridge_latest(username:str):
    username=normalize_username(username)
    item=get_latest_bridge_payload(username)
    if not item: raise HTTPException(status_code=404,detail="no_bridge_snapshot")
    p=item["payload"]
    return {"ok":True,"username":username,"observed_at":item["observed_at"],
            "followers":len(p.get("followers") or []),"following":len(p.get("following") or []),"posts":len(p.get("posts") or [])}

@app.get("/api/session-status")
def session_status():
    browser_cookie=bool(os.getenv("IG_SESSION_JSON_B64") or os.getenv("IG_SESSIONID"))
    storage_state=bool(os.getenv("IG_BROWSER_STORAGE_STATE_B64"))
    cdp=bool(os.getenv("IG_CDP_ENDPOINT"))
    instaloader_session=bool(os.getenv("IG_USERNAME") and (
        os.getenv("IG_SESSION_JSON_B64") or os.getenv("IG_SESSIONID") or
        os.getenv("IG_SESSION_B64") or os.getenv("IG_SESSIONFILE")
    ))
    meta=bool(os.getenv("META_ACCESS_TOKEN"))
    return {
      "browser_cookie_session_configured":browser_cookie,
      "browser_storage_state_configured":storage_state,
      "remote_cdp_configured":cdp,
      "instaloader_session_configured":instaloader_session,
      "meta_token_configured":meta,
      "deep_scan_context_configured":bool(browser_cookie or storage_state or cdp or instaloader_session or meta),
      "supported_authorized_inputs":["IG_SESSION_JSON_B64","IG_BROWSER_STORAGE_STATE_B64","IG_CDP_ENDPOINT","IG_SESSIONID+IG_CSRFTOKEN","IG_SESSION_B64"]
    }

@app.get("/api/bridge-extension.zip")
def bridge_extension_zip():
    bridge_dir=Path(__file__).resolve().parent/"bridge-extension"
    names=("manifest.json","popup.html","popup.js")
    missing=[n for n in names if not (bridge_dir/n).exists()]
    if missing: raise HTTPException(status_code=404,detail="bridge_extension_missing")
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
        for name in names:
            z.write(bridge_dir/name,arcname="instagram-intelligence-bridge/"+name)
        readme=("1. Open chrome://extensions or edge://extensions.\n"
                "2. Enable Developer mode.\n"
                "3. Unpack this ZIP and choose Load unpacked.\n"
                "4. Open instagram.com and sign into your own account.\n"
                "5. Open the extension, enter a PUBLIC @username and press SCAN PUBLIC PROFILE.\n"
                "6. Open Instagram Intelligence and press FULL SCAN for the same username.\n\n"
                "Passwords and Instagram cookies are not sent to the Intelligence backend. Only the collected public-profile result is uploaded.\n"
                "Private profiles are intentionally rejected.\n")
        z.writestr("instagram-intelligence-bridge/README.txt",readme)
    buf.seek(0)
    return StreamingResponse(buf,media_type="application/zip",headers={"Content-Disposition":"attachment; filename=instagram-intelligence-bridge.zip"})

@app.get("/api/history/{username}")
def api_history(username:str,limit:int=200):
    return {"username":normalize_username(username),"events":history(normalize_username(username),max(1,min(limit,1000)))}

@app.get("/api/smoke")
async def smoke(target:str="instagram"):
    result=await scan(ScanRequest(query=target,max_posts=8))
    comments=sum(1 for e in result["events"] if e.get("kind")=="comment_in")
    likes=sum(1 for e in result["events"] if e.get("kind")=="like_in")
    mentions=sum(1 for e in result["events"] if e.get("kind")=="mention_out")
    tags=sum(1 for e in result["events"] if e.get("kind")=="tag_out")
    return {"ok":True,"target":result["username"],"profile_present":bool(result["profile"]),"posts":len(result["posts"]),
      "comment_events":comments,"like_identity_events":likes,"mention_events":mentions,"tag_events":tags,
      "relationships":len(result["relationships"]),"graph_nodes":len(result["graph"]["nodes"]),"timeline_events":len(result["timeline"]),
      "followers_observed":result["changes"]["followers_observed"],"following_observed":result["changes"]["following_observed"],
      "audience_quality_status":result["audience_quality"]["status"],"coverage":result["coverage"],
      "sources":result["sources"],"warnings":result["warnings"][:10],
      "unknown_is_not_zero":result["limits"]["unknown_is_not_zero"]}

@app.post("/api/scan")
async def scan(req:ScanRequest):
    import asyncio
    username=normalize_username(req.query)
    run_id=begin_run(username)
    warnings=[];sources=[]
    try:
        public,embedded,browser,meta,insta=await asyncio.gather(
          _bounded(public_profile(username),"public_page",12),
          _bounded(public_embedded_collect(username,min(req.max_posts,12)),"public_embedded",28),
          _bounded(playwright_public_collect(username,min(req.max_posts,12)),"playwright_public",65),
          _bounded(business_discovery(username),"meta_business_discovery",18),
          _bounded(instaloader_collect(username,req.max_posts),"instaloader",50)
        )
        p={"username":username}; followers=None;following=None
        if public.get("status")=="ok":
            p.update({"public_title":public.get("title"),"public_description":public.get("description"),"profile_picture_url":public.get("image")})
        sources.append({"source":"public_page","status":public.get("status"),"detail":public.get("detail")})

        embedded_posts=[]
        if embedded.get("status") in ("ok","partial"):
            ep=embedded.get("profile") or {}
            for k,v in ep.items():
                if k!="recent_post_codes" and v not in (None,"",[],{}) and p.get(k) in (None,"",[],{}): p[k]=v
            embedded_posts=embedded.get("posts") or []
        sources.append({"source":"public_embedded","status":embedded.get("status"),"detail":embedded.get("detail")})

        browser_posts=[]
        if browser.get("status") in ("ok","partial"):
            bp=browser.get("profile") or {}
            for k,v in bp.items():
                if k!="recent_post_codes" and v not in (None,"",[],{}) and p.get(k) in (None,"",[],{}): p[k]=v
            browser_posts=browser.get("posts") or []
        sources.append({"source":"playwright_public","status":browser.get("status"),"detail":browser.get("detail")})

        meta_posts=[]
        if meta.get("status")=="ok":
            bd=((meta.get("response") or {}).get("business_discovery") or {})
            mapping={"name":"name","biography":"biography","website":"website","followers_count":"followers_count","follows_count":"follows_count","media_count":"media_count","profile_picture_url":"profile_picture_url","username":"username"}
            for src,dst in mapping.items():
                if bd.get(src) is not None: p[dst]=bd.get(src)
            for x in (((bd.get("media") or {}).get("data") or [])):
                row=dict(x);row["_meta_id"]=row.get("id");meta_posts.append(row)
        sources.append({"source":"meta_business_discovery","status":meta.get("status"),"detail":meta.get("detail")})

        insta_posts=[]
        if insta.get("status")=="ok":
            ip=insta.get("profile") or {}
            for k,v in ip.items():
                if v not in (None,"",[],{}) and p.get(k) in (None,"",[],{}): p[k]=v
            if "followers" in insta and insta.get("followers") is not None: followers=insta.get("followers")
            if "following" in insta and insta.get("following") is not None: following=insta.get("following")
            warnings.extend(insta.get("warnings") or [])
            insta_posts=insta.get("posts") or []
        sources.append({"source":"instaloader","status":insta.get("status"),"detail":insta.get("detail")})

        posts=_merge_posts(browser_posts,embedded_posts,meta_posts,insta_posts)

        bridge=get_latest_bridge_payload(username)
        if bridge:
            bp=bridge.get("payload") or {}
            bprof=bp.get("profile") or {}
            for k,v in bprof.items():
                if v not in (None,"",[],{}) and p.get(k) in (None,"",[],{}): p[k]=v
            if followers is None and isinstance(bp.get("followers"),list): followers=bp.get("followers")
            if following is None and isinstance(bp.get("following"),list): following=bp.get("following")
            posts=_merge_posts(posts,bp.get("posts") or [])
            sources.append({"source":"browser_bridge","status":"ok","detail":"snapshot "+str(bridge.get("observed_at"))})
        else:
            sources.append({"source":"browser_bridge","status":"not_configured","detail":"run authorized browser bridge once"})

        # Meta comments are fetched only for Meta media IDs.
        jobs=[];targets=[]
        for x in posts:
            mid=x.get("_meta_id")
            if mid and not x.get("comments_detail"):
                jobs.append(_bounded(media_comments(str(mid),100),"meta_comments",12));targets.append(x)
        if jobs:
            for x,r in zip(targets,await asyncio.gather(*jobs)):
                if r.get("status")=="ok":
                    x["comments_detail"]=(r.get("response") or {}).get("data") or []
                elif r.get("detail"): warnings.append("meta_comments:"+str(r.get("detail")))

        events=build_events(username,posts)
        changes=snapshot(username,followers,following,p)
        relationships=relationship_report(username,events,followers,following)
        aq=audience_quality(followers,events)
        graph=graph_payload(username,relationships)
        tl=timeline(events,changes)

        def cov_status(kind, observed):
            if observed: return "observed"
            low=" ".join(warnings).lower()
            if kind in ("comments","likes") and ("loginrequired" in low or "login_required" in low):
                return "auth_required"
            return "unknown"

        comment_events=[e for e in events if e.get("kind")=="comment_in"]
        like_events=[e for e in events if e.get("kind")=="like_in"]
        outbound_events=[e for e in events if e.get("direction")=="outbound"]
        coverage={
          "profile":"observed" if len(p)>1 else "unknown",
          "posts":"observed" if posts else "unknown",
          "comments":cov_status("comments",bool(comment_events)),
          "liker_identities":cov_status("likes",bool(like_events)),
          "followers":"observed" if followers is not None else "auth_required",
          "following":"observed" if following is not None else "auth_required",
          "follow_unfollow_history":"observed" if (changes.get("previous_snapshot") and (changes.get("followers_observed") or changes.get("following_observed"))) else "needs_two_observed_snapshots",
          "outbound_mentions_tags_coauthors":"observed" if outbound_events else "unknown",
          "profile_viewers":"not_observable",
          "profiles_viewed_by_target":"not_observable",
          "private_messages":"not_observable",
          "outgoing_global_like_history":"not_observable_from_current_public_sources",
          "outgoing_global_comment_history":"not_observable_from_current_public_sources"
        }

        save_posts(username,posts);save_events(username,tl)
        finish_run(run_id,"complete",sources,warnings)
        return {"ok":True,"username":username,"profile":p,"posts":posts,"events":events,"relationships":relationships,
          "followers":followers,"following":following,"changes":changes,"audience_quality":aq,"graph":graph,"timeline":tl,
          "history":history(username,200),"coverage":coverage,"sources":sources,"warnings":warnings,
          "limits":{"profile_viewers":"not_observable","profiles_viewed_by_target":"not_observable","private_messages":"not_observable",
                    "outgoing_likes_comments":"only_directly_observed","unknown_is_not_zero":True}}
    except Exception as e:
        finish_run(run_id,"failed",sources,warnings+[type(e).__name__+":"+str(e)[:200]])
        raise
