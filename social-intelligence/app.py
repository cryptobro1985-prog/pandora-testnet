from __future__ import annotations
import os,json
from pathlib import Path
from datetime import datetime,timezone
from fastapi import FastAPI,Response
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
from connectors import normalize_username,business_discovery,media_comments,public_profile,public_embedded_collect,instaloader_collect
from analysis import build_events,relationship_report,audience_quality,graph_payload,timeline
from storage import connect,begin_run,finish_run,save_posts,save_events,history

app=FastAPI(title="Instagram Intelligence",version="2.0.0")
WEB=Path(__file__).resolve().parent/"web"

class ScanRequest(BaseModel):
    query:str=Field(min_length=1,max_length=300)
    max_posts:int=Field(default=30,ge=1,le=60)

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
    now=datetime.now(timezone.utc).isoformat(); c=connect()
    prev=c.execute("select * from snapshots where username=? order by id desc limit 1",(username,)).fetchone()
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
    c.execute("insert into snapshots(username,created_at,followers_json,following_json,profile_json) values(?,?,?,?,?)",
              (username,now,json.dumps(current_f,ensure_ascii=False),json.dumps(current_g,ensure_ascii=False),json.dumps(profile,ensure_ascii=False)))
    c.commit();c.close();d["snapshot_at"]=now;return d

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
    connect().close()
    target=os.getenv("IG_STARTUP_SMOKE_TARGET","").strip()
    if target:
        import asyncio,logging
        async def runner():
            try:
                result=await asyncio.wait_for(scan(ScanRequest(query=target,max_posts=8)),timeout=45)
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
def health(): return {"ok":True,"service":"instagram-intelligence","version":"2.0.0"}

@app.get("/api/capabilities")
def capabilities():
    return {"instagram_only":True,
      "collectors":["2scraper_public_embedded","instaloader","meta_business_discovery","public_page_fallback"],
      "open_source_components":["2scraper/instagram-scraper","instaloader/instaloader","JuaniVeltri/igstalker","mohammedelahmar/InstaTrack","ignromanov/safe-unfollow"],
      "meta_configured":bool(os.getenv("META_ACCESS_TOKEN") and os.getenv("META_IG_USER_ID")),
      "instaloader_session_configured":bool(os.getenv("IG_USERNAME") and (os.getenv("IG_SESSIONFILE") or os.getenv("IG_SESSION_B64"))),
      "not_observable":["profile_viewer_identities","profiles_viewed_by_target","private_messages"]}

@app.get("/api/history/{username}")
def api_history(username:str,limit:int=200):
    return {"username":normalize_username(username),"events":history(normalize_username(username),max(1,min(limit,1000)))}

@app.get("/api/smoke")
async def smoke():
    result=await scan(ScanRequest(query="instagram",max_posts=8))
    comments=sum(1 for e in result["events"] if e.get("kind")=="comment_in")
    likes=sum(1 for e in result["events"] if e.get("kind")=="like_in")
    mentions=sum(1 for e in result["events"] if e.get("kind")=="mention_out")
    tags=sum(1 for e in result["events"] if e.get("kind")=="tag_out")
    return {"ok":True,"target":result["username"],"profile_present":bool(result["profile"]),"posts":len(result["posts"]),
      "comment_events":comments,"like_identity_events":likes,"mention_events":mentions,"tag_events":tags,
      "relationships":len(result["relationships"]),"graph_nodes":len(result["graph"]["nodes"]),"timeline_events":len(result["timeline"]),
      "followers_observed":result["changes"]["followers_observed"],"following_observed":result["changes"]["following_observed"],
      "audience_quality_status":result["audience_quality"]["status"],"sources":result["sources"],"warnings":result["warnings"][:10],
      "unknown_is_not_zero":result["limits"]["unknown_is_not_zero"]}

@app.post("/api/scan")
async def scan(req:ScanRequest):
    import asyncio
    username=normalize_username(req.query)
    run_id=begin_run(username)
    warnings=[];sources=[]
    try:
        public,embedded,meta,insta=await asyncio.gather(
          _bounded(public_profile(username),"public_page",12),
          _bounded(public_embedded_collect(username,min(req.max_posts,12)),"public_embedded",28),
          _bounded(business_discovery(username),"meta_business_discovery",18),
          _bounded(instaloader_collect(username,req.max_posts),"instaloader",30)
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

        posts=_merge_posts(embedded_posts,meta_posts,insta_posts)

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

        save_posts(username,posts);save_events(username,tl)
        finish_run(run_id,"complete",sources,warnings)
        return {"ok":True,"username":username,"profile":p,"posts":posts,"events":events,"relationships":relationships,
          "followers":followers,"following":following,"changes":changes,"audience_quality":aq,"graph":graph,"timeline":tl,
          "history":history(username,200),"sources":sources,"warnings":warnings,
          "limits":{"profile_viewers":"not_observable","profiles_viewed_by_target":"not_observable","private_messages":"not_observable",
                    "outgoing_likes_comments":"only_directly_observed","unknown_is_not_zero":True}}
    except Exception as e:
        finish_run(run_id,"failed",sources,warnings+[type(e).__name__+":"+str(e)[:200]])
        raise
