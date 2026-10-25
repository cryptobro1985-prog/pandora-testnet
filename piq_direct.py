"""Direct public PiQ Markets headline reader for PANDORA.

Uses the free public PiQ website/widget surface; no PiQ API key is required.
The reader only returns stories that have an explicit publication timestamp.
"""
import datetime as dt
import html
import json
import re
import urllib.parse

from curl_cffi import requests as curl_requests

BASE="https://piqmarkets.com"
DISCOVERY_URLS=(
    BASE+"/embed/news-ticker",
    BASE+"/",
)
UA="Mozilla/5.0 (compatible; PANDORA-market-news/1.0)"

class PiQReadError(RuntimeError):
    pass

def _request(url,timeout=4.0):
    r=curl_requests.get(
        url,
        headers={"User-Agent":UA,"Accept":"text/html,application/xhtml+xml","Cache-Control":"no-cache"},
        impersonate="chrome",
        timeout=timeout,
    )
    if int(r.status_code)!=200:
        raise PiQReadError("http_"+str(r.status_code))
    text=r.text or ""
    if not text:
        raise PiQReadError("empty_response")
    if len(text)>5_000_000:
        raise PiQReadError("page_too_large")
    return text

def _clean(value):
    value=html.unescape(re.sub(r"<[^>]+>"," ",value or ""))
    return re.sub(r"\s+"," ",value).strip()

def discover(timeout=4.0,limit=40):
    """Return unique public /story/ URLs visible in the ticker or homepage."""
    errors=[]
    found=[]
    seen=set()
    patterns=(
        re.compile(r'href=["\'](?P<href>/story/[^"\'?#]+)["\'][^>]*>(?P<label>.*?)</a>',re.I|re.S),
        re.compile(r'href=["\'](?P<href>https://piqmarkets\.com/story/[^"\'?#]+)["\'][^>]*>(?P<label>.*?)</a>',re.I|re.S),
    )
    for source_url in DISCOVERY_URLS:
        try:
            page=_request(source_url,timeout=timeout)
        except Exception as exc:
            errors.append(source_url+":"+str(exc)[:100])
            continue
        for pat in patterns:
            for m in pat.finditer(page):
                href=urllib.parse.urljoin(BASE,m.group("href"))
                if href in seen:
                    continue
                seen.add(href)
                label=_clean(m.group("label"))
                found.append({"url":href,"headline_hint":label or None,"discovery_url":source_url})
                if len(found)>=limit:
                    return found
        # Some Next.js pages carry route strings in JSON/script data rather than <a>.
        for raw in re.findall(r'["\'](\\?/story/[^"\'?#<>{}]+)["\']',page,re.I):
            href=raw.replace("\\/","/")
            href=urllib.parse.urljoin(BASE,href)
            if href in seen:
                continue
            seen.add(href)
            found.append({"url":href,"headline_hint":None,"discovery_url":source_url})
            if len(found)>=limit:
                return found
    if not found:
        raise PiQReadError("no_story_links"+" | "+(" | ".join(errors)[:260] if errors else ""))
    return found

def _walk_json(value):
    if isinstance(value,dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value,list):
        for child in value:
            yield from _walk_json(child)

def _iso(value):
    if not isinstance(value,str) or not value.strip():
        return None
    v=value.strip().replace("Z","+00:00")
    try:
        parsed=dt.datetime.fromisoformat(v)
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(dt.timezone.utc).isoformat()
    except Exception:
        return None

def fetch_story(url,headline_hint=None,timeout=4.0):
    page=_request(url,timeout=timeout)
    headline=None
    published=None

    # Prefer structured data because it carries an exact timezone-aware timestamp.
    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',page,re.I|re.S):
        try:
            payload=json.loads(html.unescape(block))
        except Exception:
            continue
        for node in _walk_json(payload):
            if headline is None and isinstance(node.get("headline"),str):
                headline=_clean(node.get("headline"))
            if published is None:
                published=_iso(node.get("datePublished")) or _iso(node.get("dateCreated"))

    if published is None:
        for pat in (
            r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']date["\'][^>]+content=["\']([^"\']+)["\']',
            r'"datePublished"\s*:\s*"([^"]+)"',
            r'"publishedAt"\s*:\s*"([^"]+)"',
            r'"createdAt"\s*:\s*"([^"]+)"',
        ):
            m=re.search(pat,page,re.I)
            if m:
                published=_iso(m.group(1))
                if published:
                    break

    if headline is None:
        for pat in (
            r'<h1[^>]*>(.*?)</h1>',
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            r'<title[^>]*>(.*?)</title>',
        ):
            m=re.search(pat,page,re.I|re.S)
            if m:
                headline=_clean(m.group(1))
                if headline:
                    break

    headline=headline or _clean(headline_hint or "")
    if not headline:
        raise PiQReadError("headline_missing")
    if not published:
        raise PiQReadError("exact_publication_timestamp_missing")
    return {"id":url,"url":url,"text":headline,"created_at":published}

_HIGH_SIGNAL_TERMS=(
    "bitcoin","btc","ethereum","ether","eth","solana","sol","crypto","cryptocurrency","blockchain",
    "stablecoin","token","coinbase","binance","tether","circle","etf","spot etf","hack","hacked","exploit",
    "fed","fomc","federal reserve","rate cut","rate hike","interest rate","inflation","cpi","pce",
    "nonfarm","payrolls","jobs report","treasury","yield","recession","sec "," sec","cftc",
    "tariff","sanction","airstrike","missile","invasion","ceasefire","truce","war "," war",
    "opec","oil "," oil","hormuz","suez","taiwan","china","default","shutdown",
)

def high_signal(headline):
    lo=(headline or "").lower()
    return any(term in lo for term in _HIGH_SIGNAL_TERMS)
