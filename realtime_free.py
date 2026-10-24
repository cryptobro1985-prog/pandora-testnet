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

from curl_cffi import requests as curl_requests

FX_BASE="https://api.fxtwitter.com"
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
    req=urllib.request.Request(url,headers={"User-Agent":FX_UA,"Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=timeout) as response:
        payload=json.load(response)
    code=int(payload.get("code",200) or 0)
    if code!=200:
        raise RuntimeError("fxtwitter_code_"+str(code))
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
