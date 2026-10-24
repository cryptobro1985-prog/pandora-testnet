"""Free low-latency public social readers used by PANDORA.
X: FxTwitter v2 public profile timelines.
Truth Social: Mastodon-compatible REST with curl_cffi browser impersonation.
"""
import datetime as dt
import html
import json
import re
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import time

from curl_cffi import requests as curl_requests

FX_BASE="https://api.fxtwitter.com"
VX_BASE="https://api.vxtwitter.com"
XLOOKUP_BASE="https://x-lookup.mynameistito.com"
TRUTH_BASE="https://truthsocial.com/api"
FX_UA="PANDORA-market-news/1.0 (+https://pandora-testnet-monitor.onrender.com)"
try:
    from truthbrush.api import USER_AGENT as TRUTH_UA, IMPERSONATE_TARGET
except Exception:
    TRUTH_UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
    IMPERSONATE_TARGET="chrome146"

_tls=threading.local()

def _truth_session():
    sess=getattr(_tls,"truth_session",None)
    if sess is None:
        sess=curl_requests.Session()
        _tls.truth_session=sess
    return sess

def _clean(value):
    value=html.unescape(re.sub(r"<[^>]+>"," ",value or ""))
    return re.sub(r"\s+"," ",value).strip()

def fetch_x(handle,timeout=4):
    url=FX_BASE+"/2/profile/"+urllib.parse.quote(handle,safe="")+"/statuses"
    last=None
    for attempt in range(3):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":FX_UA,"Accept":"application/json","Cache-Control":"no-cache"})
            with urllib.request.urlopen(req,timeout=timeout) as response:
                payload=json.load(response)
            code=int(payload.get("code",200) or 0)
            if code!=200:
                raise RuntimeError("fxtwitter_code_"+str(code))
            break
        except Exception as exc:
            last=exc
            if attempt<2:
                time.sleep(0.18*(attempt+1))
    else:
        raise last
    rows=payload.get("results")
    if not isinstance(rows,list):
        raise RuntimeError("fxtwitter_invalid_results")
    out=[]
    for row in rows:
        if not isinstance(row,dict) or row.get("type") not in (None,"status"):
            continue
        ident=str(row.get("id") or "")
        text=(row.get("text") or "").strip()
        if not ident or not text:
            continue
        author=row.get("author") or {}
        author_handle=str(author.get("screen_name") or "")
        reposted=row.get("reposted_by") or {}
        reposter=str(reposted.get("screen_name") or "")
        if author_handle.lower()!=handle.lower() and reposter.lower()!=handle.lower():
            continue
        ts=row.get("created_timestamp")
        if isinstance(ts,(int,float)):
            created=dt.datetime.fromtimestamp(float(ts),dt.timezone.utc).isoformat()
        else:
            created=row.get("created_at")
        if reposter and author_handle.lower()!=handle.lower():
            text="[repost by @"+handle+"] "+text
        out.append({"id":ident,"text":text,"created_at":created,"url":row.get("url") or ("https://x.com/"+handle+"/status/"+ident)})
    return out

def fetch_x_lookup(handle,timeout=5):
    """Independent public Cloudflare x-lookup profile timeline."""
    url=XLOOKUP_BASE+"/"+urllib.parse.quote(handle,safe="")+"?format=json&nocache=true&limit=20"
    req=urllib.request.Request(url,headers={"User-Agent":FX_UA,"Accept":"application/json","Cache-Control":"no-cache"})
    with urllib.request.urlopen(req,timeout=timeout) as response:
        payload=json.load(response)
    if not isinstance(payload,dict):
        raise RuntimeError("xlookup_invalid_payload")
    if payload.get("error"):
        raise RuntimeError("xlookup_"+str(payload.get("code") or payload.get("error"))[:80])
    rows=payload.get("posts")
    if not isinstance(rows,list):
        raise RuntimeError("xlookup_invalid_results")
    out=[]
    for row in rows:
        if not isinstance(row,dict):
            continue
        ident=str(row.get("id") or "")
        text=(row.get("text") or "").strip()
        if not ident or not text:
            continue
        author=row.get("author") or {}
        screen=str(author.get("screen_name") or handle)
        if screen.lower()!=handle.lower():
            continue
        ts=row.get("created_timestamp")
        if isinstance(ts,(int,float)):
            created=dt.datetime.fromtimestamp(float(ts),dt.timezone.utc).isoformat()
        else:
            created=row.get("created_at")
        out.append({"id":ident,"text":text,"created_at":created,
                    "url":row.get("url") or ("https://x.com/"+handle+"/status/"+ident)})
    return out

def fetch_x_syndication(handle,timeout=5):
    """Official public embed timeline fallback; browser TLS fingerprint via curl_cffi."""
    url="https://syndication.twitter.com/srv/timeline-profile/screen-name/"+urllib.parse.quote(handle,safe="")+"?showReplies=false"
    response=_truth_session().get(url,headers={"User-Agent":TRUTH_UA,"Accept":"text/html"},impersonate=IMPERSONATE_TARGET,timeout=timeout)
    if response.status_code!=200:
        raise RuntimeError("x_syndication_http_"+str(response.status_code))
    body=response.text or ""
    marker='id="__NEXT_DATA__"'
    idx=body.find(marker)
    if idx<0:raise RuntimeError("x_syndication_next_data_missing")
    start=body.find(">",idx)
    end=body.find("</script>",start+1)
    if start<0 or end<0:raise RuntimeError("x_syndication_malformed")
    doc=json.loads(body[start+1:end].strip())
    entries=(((doc.get("props") or {}).get("pageProps") or {}).get("timeline") or {}).get("entries") or []
    out=[]
    for entry in entries:
        if not isinstance(entry,dict) or entry.get("type")!="tweet":continue
        row=((entry.get("content") or {}).get("tweet") or {})
        ident=str(row.get("id_str") or "")
        text=(row.get("full_text") or "").strip()
        user=row.get("user") or {}
        screen=str(user.get("screen_name") or "")
        if not ident or not text or screen.lower()!=handle.lower():continue
        out.append({"id":ident,"text":text,"created_at":row.get("created_at"),
                    "url":"https://x.com/"+handle+"/status/"+ident})
    if not out:raise RuntimeError("x_syndication_empty")
    return out

def fetch_x_vx(handle,timeout=4):
    """Independent no-key fallback: vxTwitter user endpoint with recent tweets."""
    url=VX_BASE+"/"+urllib.parse.quote(handle,safe="")+"?with_tweets=true"
    req=urllib.request.Request(url,headers={"User-Agent":FX_UA,"Accept":"application/json","Cache-Control":"no-cache"})
    with urllib.request.urlopen(req,timeout=timeout) as response:
        payload=json.load(response)
    if not isinstance(payload,dict):
        raise RuntimeError("vxtwitter_invalid_profile")
    if payload.get("error"):
        raise RuntimeError("vxtwitter_"+str(payload.get("error"))[:80])
    rows=payload.get("latest_tweets")
    if not isinstance(rows,list):
        raise RuntimeError("vxtwitter_invalid_results")
    out=[]
    for row in rows:
        if not isinstance(row,dict):
            continue
        ident=str(row.get("tweetID") or row.get("id") or "")
        text=(row.get("text") or "").strip()
        if not ident or not text:
            continue
        screen=str(row.get("user_screen_name") or payload.get("screen_name") or handle)
        if screen.lower()!=handle.lower():
            continue
        epoch=row.get("date_epoch")
        if isinstance(epoch,(int,float)):
            created=dt.datetime.fromtimestamp(float(epoch),dt.timezone.utc).isoformat()
        else:
            created=row.get("created_at") or row.get("date")
        out.append({"id":ident,"text":text,"created_at":created,
                    "url":row.get("tweetURL") or ("https://x.com/"+handle+"/status/"+ident)})
    return out

def fetch_x_nitter(handle,timeout=5):
    """Last-resort public RSS rotation. Used only after normal X readers fail."""
    instances=[
        "https://nitter.kareem.one",
        "https://nitter.meowing.monster",
        "https://shitter.thepixora.com",
        "https://nitter.jaydenha.uk",
    ]
    start=sum(ord(ch) for ch in handle)%len(instances)
    errors=[]
    for n in range(len(instances)):
        base=instances[(start+n)%len(instances)]
        url=base+"/"+urllib.parse.quote(handle,safe="")+"/rss"
        try:
            req=urllib.request.Request(url,headers={"User-Agent":FX_UA,"Accept":"application/rss+xml,application/xml,text/xml"})
            with urllib.request.urlopen(req,timeout=timeout) as response:
                raw=response.read(1_500_000)
            root=ET.fromstring(raw)
            out=[]
            for item in root.findall(".//item")[:20]:
                link=(item.findtext("link") or "").strip()
                ident=(item.findtext("guid") or link).strip()
                title=_clean(item.findtext("title") or item.findtext("description") or "")
                created=(item.findtext("pubDate") or "").strip() or None
                if ident and title:
                    out.append({"id":ident,"text":title,"created_at":created,"url":link or ("https://x.com/"+handle)})
            if out:return out
            errors.append(base+":empty")
        except Exception as exc:
            errors.append(base+":"+str(exc)[:55])
    raise RuntimeError("nitter_all_failed "+" | ".join(errors))

def _truth_get(path,params=None,timeout=6):
    response=_truth_session().get(
        TRUTH_BASE+path,params=params or {},
        headers={"User-Agent":TRUTH_UA,"Accept":"application/json"},
        impersonate=IMPERSONATE_TARGET,timeout=timeout,
    )
    if response.status_code!=200:
        raise RuntimeError("truth_http_"+str(response.status_code))
    try:
        return response.json(),dict(response.headers)
    except Exception as exc:
        body=(response.text or "")[:200].lower()
        if "just a moment" in body or "cdn-cgi" in body:
            raise RuntimeError("truth_cloudflare_challenge") from exc
        raise RuntimeError("truth_invalid_json") from exc

def truth_lookup(handle):
    payload,headers=_truth_get("/v1/accounts/lookup",{"acct":handle})
    if not isinstance(payload,dict) or not payload.get("id"):
        raise RuntimeError("truth_account_not_found")
    return str(payload["id"]),headers

def fetch_truth(handle,account_id=None,timeout=6):
    if not account_id:
        account_id,_=truth_lookup(handle)
    payload,headers=_truth_get("/v1/accounts/"+urllib.parse.quote(str(account_id),safe="")+"/statuses",
                               {"limit":10,"exclude_replies":"true"},timeout=timeout)
    if not isinstance(payload,list):
        raise RuntimeError("truth_invalid_results")
    out=[]
    for row in payload:
        if not isinstance(row,dict) or not row.get("id"):
            continue
        text=_clean(row.get("content"))
        if not text:
            continue
        out.append({"id":str(row["id"]),"text":text,"created_at":row.get("created_at"),
                    "url":row.get("url") or ("https://truthsocial.com/@"+handle+"/"+str(row["id"]))})
    return str(account_id),out,headers

def fetch_truth_activitypub(handle,timeout=6):
    """Read a public Truth Social actor outbox through ActivityPub/WebFinger."""
    sess=_truth_session()
    common={"User-Agent":TRUTH_UA,"Accept":"application/activity+json, application/ld+json"}
    wf=sess.get("https://truthsocial.com/.well-known/webfinger",
                params={"resource":"acct:"+handle+"@truthsocial.com"},
                headers={"User-Agent":TRUTH_UA,"Accept":"application/jrd+json"},
                impersonate=IMPERSONATE_TARGET,timeout=timeout)
    if wf.status_code!=200:
        raise RuntimeError("truth_ap_webfinger_"+str(wf.status_code))
    data=wf.json()
    actor_url=next((x.get("href") for x in data.get("links",[]) if x.get("rel")=="self" and x.get("href")),None)
    if not actor_url:
        raise RuntimeError("truth_ap_no_actor")
    actor=sess.get(actor_url,headers=common,impersonate=IMPERSONATE_TARGET,timeout=timeout)
    if actor.status_code!=200:
        raise RuntimeError("truth_ap_actor_"+str(actor.status_code))
    actor_data=actor.json()
    outbox=actor_data.get("outbox")
    if not outbox:
        raise RuntimeError("truth_ap_no_outbox")
    page=sess.get(outbox,params={"page":"true"},headers=common,impersonate=IMPERSONATE_TARGET,timeout=timeout)
    if page.status_code!=200:
        raise RuntimeError("truth_ap_outbox_"+str(page.status_code))
    payload=page.json()
    if isinstance(payload.get("first"),str) and not payload.get("orderedItems"):
        page=sess.get(payload["first"],headers=common,impersonate=IMPERSONATE_TARGET,timeout=timeout)
        if page.status_code!=200:
            raise RuntimeError("truth_ap_first_"+str(page.status_code))
        payload=page.json()
    items=payload.get("orderedItems") or payload.get("items") or []
    out=[]
    for activity in items[:20]:
        if not isinstance(activity,dict):
            continue
        obj=activity.get("object")
        if isinstance(obj,str):
            continue
        if not isinstance(obj,dict):
            obj=activity
        ident=str(obj.get("id") or activity.get("id") or "")
        text=_clean(obj.get("content") or obj.get("summary") or "")
        created=obj.get("published") or activity.get("published")
        url=obj.get("url") or ident
        if ident and text and created:
            out.append({"id":ident.rsplit("/",1)[-1],"text":text,"created_at":created,"url":url})
    if not out:
        raise RuntimeError("truth_ap_empty")
    return out
