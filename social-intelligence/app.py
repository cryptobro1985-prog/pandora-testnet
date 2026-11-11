from __future__ import annotations
import os,json,sqlite3,math,re
from pathlib import Path
from datetime import datetime,timezone
from collections import defaultdict
from fastapi import FastAPI,Response
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
from connectors import normalize_username,business_discovery,media_comments,public_profile,instaloader_collect

app=FastAPI(title="Instagram Intelligence",version="1.0.0")
WEB=Path(__file__).resolve().parent/"web"
DB=Path(os.getenv("IG_INTEL_DB","/tmp/instagram_intelligence.sqlite3"))

class ScanRequest(BaseModel):
    query:str=Field(min_length=1,max_length=300)
    max_posts:int=Field(default=30,ge=1,le=60)

def db():
    DB.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.executescript("create table if not exists snapshots(id integer primary key autoincrement,username text not null,created_at text not null,followers_json text,following_json text,profile_json text not null);create index if not exists idx_snap_user on snapshots(username,id);")
    return c

def score(username,events):
    a=defaultdict(lambda:{"comments_in":0,"likes_in":0,"mentions_out":0,"events":0,"raw":0.0})
    for e in events:
        actor=(e.get("actor") or "").lower(); kind=e.get("kind")
        if not actor or actor==username.lower(): continue
        w={"comment_in":3.0,"like_in":1.0,"mention_out":4.0}.get(kind,1.0); x=a[actor]; x["events"]+=1; x["raw"]+=w
        if kind=="comment_in": x["comments_in"]+=1
        elif kind=="like_in": x["likes_in"]+=1
        elif kind=="mention_out": x["mentions_out"]+=1
    rows=[{"username":u,"score":round(math.log1p(v["raw"])*10,2),**v} for u,v in a.items()]
    rows.sort(key=lambda x:(x["score"],x["events"]),reverse=True); return rows

def snapshot(username,followers,following,profile):
    now=datetime.now(timezone.utc).isoformat(); c=db()
    prev=c.execute("select * from snapshots where username=? order by id desc limit 1",(username,)).fetchone()
    d={"new_followers":[],"lost_followers":[],"new_following":[],"unfollowed":[],"previous_snapshot":None,"followers_observed":followers is not None,"following_observed":following is not None}
    if prev:
        pf=set(json.loads(prev["followers_json"] or "[]")); pg=set(json.loads(prev["following_json"] or "[]"))
        if followers is not None:
            cf=set(followers); d["new_followers"]=sorted(cf-pf); d["lost_followers"]=sorted(pf-cf)
        if following is not None:
            cg=set(following); d["new_following"]=sorted(cg-pg); d["unfollowed"]=sorted(pg-cg)
        d["previous_snapshot"]=prev["created_at"]
    c.execute("insert into snapshots(username,created_at,followers_json,following_json,profile_json) values(?,?,?,?,?)",
              (username,now,json.dumps(followers or []),json.dumps(following or []),json.dumps(profile,ensure_ascii=False)))
    c.commit(); c.close(); d["snapshot_at"]=now; return d

async def _startup_smoke():
    target=os.getenv("IG_STARTUP_SMOKE_TARGET","").strip()
    if not target:
        return
    try:
        import asyncio
        result=await asyncio.wait_for(scan(ScanRequest(query=target,max_posts=8)), timeout=28)
        print("instagram_smoke_test="+json.dumps({
            "username":result.get("username"),
            "profile_keys":sorted((result.get("profile") or {}).keys()),
            "posts":len(result.get("posts") or []),
            "events":len(result.get("events") or []),
            "relationships":len(result.get("relationships") or []),
            "followers_observed":result.get("followers") is not None,
            "following_observed":result.get("following") is not None,
            "sources":result.get("sources"),
            "warnings":(result.get("warnings") or [])[:8]
        },ensure_ascii=False))
    except Exception as e:
        print("instagram_smoke_test_error="+type(e).__name__+":"+str(e)[:300])

@app.on_event("startup")
async def startup():
    db().close()
    import asyncio
    asyncio.create_task(_startup_smoke())
@app.head("/")
def head(): return Response(status_code=200)
@app.get("/")
def index(): return FileResponse(WEB/"index.html",headers={"Cache-Control":"no-store"})
@app.get("/api/health")
def health(): return {"ok":True,"service":"instagram-intelligence","version":"1.0.0"}
@app.get("/api/capabilities")
def capabilities():
    return {"instagram_only":True,"meta_configured":bool(os.getenv("META_ACCESS_TOKEN") and os.getenv("META_IG_USER_ID")),
            "instaloader_session_configured":bool(os.getenv("IG_USERNAME") and (os.getenv("IG_SESSIONFILE") or os.getenv("IG_SESSION_B64"))),
            "profile_viewers":False,"profiles_viewed_by_target":False}

async def _bounded(coro, source, timeout=22):
    import asyncio
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        return {"status":"unavailable","source":source,"detail":"timeout"}
    except Exception as e:
        return {"status":"unavailable","source":source,"detail":type(e).__name__}

@app.post("/api/scan")
async def scan(req:ScanRequest):
    import asyncio
    username=normalize_username(req.query)
    public,meta,insta=await asyncio.gather(
        _bounded(public_profile(username),"public_page",12),
        _bounded(business_discovery(username),"meta_business_discovery",18),
        _bounded(instaloader_collect(username,req.max_posts),"instaloader",22)
    )
    p={"username":username}; posts=[]; warnings=[]; sources=[]; followers=None; following=None
    if public.get("status")=="ok":
        p.update({"public_title":public.get("title"),"public_description":public.get("description"),"profile_picture_url":public.get("image")}); sources.append({"source":"public_page","status":"ok"})
    else: sources.append({"source":"public_page","status":public.get("status")})
    if meta.get("status")=="ok":
        bd=((meta.get("response") or {}).get("business_discovery") or {})
        for k in ["username","name","biography","website","followers_count","follows_count","media_count","profile_picture_url"]:
            if bd.get(k) is not None: p[k]=bd.get(k)
        posts=[dict(x) for x in (((bd.get("media") or {}).get("data") or []))]; sources.append({"source":"meta_business_discovery","status":"ok"})
    else: sources.append({"source":"meta_business_discovery","status":meta.get("status"),"detail":meta.get("detail")})
    if insta.get("status")=="ok":
        ip=insta.get("profile") or {}
        for k,v in ip.items():
            if v not in [None,"",[]] and not p.get(k): p[k]=v
        if insta.get("followers"): followers=list(dict.fromkeys(insta["followers"]))
        if insta.get("following"): following=list(dict.fromkeys(insta["following"]))
        warnings.extend(insta.get("warnings") or []); sources.append({"source":"instaloader","status":"ok"})
        known={str(x.get("id")):x for x in posts if x.get("id") is not None}
        for x in insta.get("posts") or []:
            if str(x.get("id")) in known:
                known[str(x.get("id"))]["comments_detail"]=x.get("comments_detail",[]); known[str(x.get("id"))]["likers"]=x.get("likers",[])
            else: posts.append(x)
    else: sources.append({"source":"instaloader","status":insta.get("status"),"detail":insta.get("detail")})
    jobs=[]; jobposts=[]
    for x in posts:
        if x.get("id") and not x.get("comments_detail"):
            jobs.append(media_comments(str(x["id"]),100)); jobposts.append(x)
    if jobs:
        rs=await asyncio.gather(*jobs)
        for x,r in zip(jobposts,rs):
            if r.get("status")=="ok": x["comments_detail"]=(r.get("response") or {}).get("data") or []
    events=[]; mention=re.compile(r"@([A-Za-z0-9._]{1,30})")
    for x in posts:
        url=x.get("permalink") or ("https://www.instagram.com/p/"+x.get("shortcode")+"/" if x.get("shortcode") else None)
        for c in x.get("comments_detail") or []:
            actor=c.get("username")
            if actor: events.append({"kind":"comment_in","actor":actor,"timestamp":c.get("timestamp"),"text":c.get("text",""),"url":url})
        for actor in x.get("likers") or []: events.append({"kind":"like_in","actor":actor,"timestamp":x.get("timestamp"),"url":url})
        for actor in set(mention.findall(x.get("caption") or "")): events.append({"kind":"mention_out","actor":actor,"timestamp":x.get("timestamp"),"url":url})
    return {"ok":True,"username":username,"profile":p,"posts":posts,"events":events,"relationships":score(username,events),
            "followers":followers,"following":following,"changes":snapshot(username,followers,following,p),"sources":sources,"warnings":warnings,
            "limits":{"profile_viewers":"not_observable","profiles_viewed_by_target":"not_observable","unknown_is_not_zero":True}}
