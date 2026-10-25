"""Direct public PiQ Markets headline reader for PANDORA.

Uses the free public PiQ website/widget surface; no PiQ API key is required.
The reader only returns stories that have an explicit publication timestamp.
"""
import datetime as dt
import html
import json
import re
import urllib.parse
import concurrent.futures
from html.parser import HTMLParser

from curl_cffi import requests as curl_requests

BASE="https://piqmarkets.com"
DISCOVERY_URLS=(
    BASE+"/embed/news-ticker",
    BASE+"/",
)
UA="Mozilla/5.0 (compatible; PANDORA-market-news/1.0)"

class PiQReadError(RuntimeError):
    pass

def _trusted_url(url,story=False):
    """Only the publisher's HTTPS pages may be fetched from discovered data."""
    if not isinstance(url,str) or any(ord(c)<33 for c in url):
        raise PiQReadError("untrusted_url")
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!="https" or parsed.netloc.lower()!="piqmarkets.com":
        raise PiQReadError("untrusted_url")
    path=urllib.parse.unquote(parsed.path)
    if "\\" in path or any(part in (".","..") for part in path.split("/")):
        raise PiQReadError("untrusted_url")
    if story and not re.fullmatch(r"/story/[^/\s?#]+",path):
        raise PiQReadError("invalid_story_url")
    return urllib.parse.urlunsplit(("https","piqmarkets.com",parsed.path,"",""))

def _request(url,timeout=4.0):
    url=_trusted_url(url)
    r=curl_requests.get(
        url,
        headers={"User-Agent":UA,"Accept":"text/html,application/xhtml+xml","Cache-Control":"no-cache"},
        impersonate="chrome",
        timeout=timeout,
        allow_redirects=False,
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
    if not isinstance(value,str):return ""
    value=html.unescape(re.sub(r"<[^>]+>"," ",value or ""))
    return re.sub(r"\s+"," ",value).strip()

def discover(timeout=4.0,limit=40):
    """Return unique public /story/ URLs visible in the ticker or homepage."""
    limit=max(1,min(100,int(limit)))
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
                try:href=_trusted_url(urllib.parse.urljoin(BASE,m.group("href")),story=True)
                except PiQReadError:continue
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
            try:href=_trusted_url(urllib.parse.urljoin(BASE,href),story=True)
            except PiQReadError:continue
            if href in seen:
                continue
            seen.add(href)
            found.append({"url":href,"headline_hint":None,"discovery_url":source_url})
            if len(found)>=limit:
                return found
        # A usable ticker is sufficient; a second homepage fetch adds latency
        # without improving the timestamp provenance of the discovered links.
        if len(found)>=min(limit,10):
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

class _PageMetadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta={};self.scripts=[];self.h1=[];self._h1=False;self._script=None

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=="meta":
            key=(attrs.get("property") or attrs.get("name") or "").lower()
            if key and attrs.get("content"):
                self.meta.setdefault(key,attrs["content"])
        elif tag=="h1":self._h1=True
        elif tag=="script":self._script=[attrs.get("type",""),[]]

    def handle_endtag(self,tag):
        if tag=="h1":self._h1=False
        elif tag=="script" and self._script is not None:
            self.scripts.append((self._script[0],"".join(self._script[1])))
            self._script=None

    def handle_data(self,data):
        if self._h1:self.h1.append(data)
        if self._script is not None:self._script[1].append(data)


def _identity_matches(node,url):
    """None means unidentified; False means explicitly a different story."""
    identities=[]
    for key in ("url","@id","mainEntityOfPage"):
        value=node.get(key)
        if isinstance(value,dict):value=value.get("@id") or value.get("url")
        if isinstance(value,str):identities.append(value)
    if isinstance(node.get("slug"),str):identities.append("/story/"+node["slug"])
    if not identities:return None
    for identity in identities:
        try:
            if _trusted_url(urllib.parse.urljoin(url,identity),story=True)==url:return True
        except PiQReadError:pass
    return False


def _json_nodes(scripts):
    """Read JSON as data; never execute hydration scripts."""
    for kind,block in scripts:
        if kind.lower() not in ("application/ld+json","application/json"):continue
        try:payload=json.loads(block)
        except (ValueError,TypeError):continue
        for node in _walk_json(payload):yield kind.lower(),node


def fetch_story(url,headline_hint=None,timeout=4.0):
    url=_trusted_url(url,story=True)
    page=_request(url,timeout=timeout)
    metadata=_PageMetadata();metadata.feed(page)
    canonical=metadata.meta.get("og:url")
    if canonical and _trusted_url(canonical,story=True)!=url:
        raise PiQReadError("story_url_mismatch")
    page_headline=_clean(" ".join(metadata.h1)) or _clean(metadata.meta.get("og:title"))
    hint=_clean(headline_hint or "")
    candidates=[]
    for kind,node in _json_nodes(metadata.scripts):
        typ=node.get("@type",[])
        types={typ} if isinstance(typ,str) else {x for x in typ if isinstance(x,str)} if isinstance(typ,list) else set()
        article=bool(types.intersection({"Article","NewsArticle","ReportageNewsArticle","AnalysisNewsArticle"}))
        if kind=="application/ld+json" and not article:continue
        headline=_clean(node.get("headline") or node.get("title") or "")
        if not headline:continue
        identity=_identity_matches(node,url)
        if identity is False:continue
        headline_match=headline.casefold() in {s.casefold() for s in (page_headline,hint) if s}
        if identity is not True and (page_headline or hint) and not headline_match:continue
        if kind=="application/json" and identity is not True and not headline_match:continue
        # Application data's publishedAt is accepted only on the same identified
        # story object. Generic author/site createdAt is never publication time.
        published=_iso(node.get("datePublished"))
        if not published and kind=="application/json" and (identity is True or headline_match):
            published=_iso(node.get("publishedAt"))
        candidates.append((4 if identity is True else 2 if headline_match else 1,headline,published))

    headline=page_headline or hint;published=None
    if candidates:
        best=max(x[0] for x in candidates)
        best_candidates={(h,p) for rank,h,p in candidates if rank==best}
        if len(best_candidates)>1:raise PiQReadError("ambiguous_story_metadata")
        headline,published=next(iter(best_candidates))
    # This property belongs to the current article. Attribute order is irrelevant.
    # dateModified, visible <time>, dateCreated and generic date are not substitutes.
    meta_published=_iso(metadata.meta.get("article:published_time"))
    if published and meta_published and published!=meta_published:
        raise PiQReadError("conflicting_publication_timestamps")
    published=published or meta_published
    if not headline:raise PiQReadError("headline_missing")
    if not published:raise PiQReadError("exact_publication_timestamp_missing")
    return {"id":url,"url":url,"text":headline,"created_at":published}

_HIGH_SIGNAL_PHRASES=(
    "bitcoin","ethereum","ether","solana","crypto","cryptocurrency","blockchain",
    "stablecoin","token","coinbase","binance","tether","circle","spot etf","etf approved",
    "hack","hacked","exploit","federal reserve","fomc","rate cut","rate hike","interest rate",
    "inflation","nonfarm","payrolls","jobs report","treasury","yield","recession",
    "tariff","sanction","airstrike","missile","invasion","ceasefire","truce",
    "opec","hormuz","suez","taiwan","china","default","shutdown",
)
_HIGH_SIGNAL_TOKEN_RE=re.compile(
    r"(?<![A-Za-z0-9])(?:BTC|ETH|SOL|SEC|CFTC|CPI|PCE|OIL|WAR)(?![A-Za-z0-9])",
    re.I,
)
_HIGH_SIGNAL_PHRASE_RE=re.compile(
    r"(?<![A-Za-z0-9])(?:"+"|".join(re.escape(term)+r"(?:s)?" for term in _HIGH_SIGNAL_PHRASES)+r")(?![A-Za-z0-9])",re.I
)

def high_signal(headline):
    text=headline or ""
    return bool(_HIGH_SIGNAL_TOKEN_RE.search(text) or _HIGH_SIGNAL_PHRASE_RE.search(text))


_story_cache={}

def fetch_latest(timeout=4.0,limit=30):
    """Fetch the public PiQ ticker/homepage and resolve only newly seen stories.

    The first call may resolve a small batch of story pages to obtain exact
    publication timestamps. Subsequent polls usually fetch just the new story,
    so this does not hammer PiQ with one request per cached headline.
    """
    discovered=discover(timeout=timeout,limit=max(20,min(60,int(limit)*2)))
    new=[item for item in discovered if item["url"] not in _story_cache][:12]
    if new:
        def load(item):
            try:
                return item["url"],fetch_story(item["url"],item.get("headline_hint"),timeout=timeout)
            except Exception:
                return item["url"],None
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(6,len(new))) as pool:
            for url,row in pool.map(load,new):
                if row:
                    _story_cache[url]=row
    current_urls=[item["url"] for item in discovered]
    rows=[_story_cache[url] for url in current_urls if url in _story_cache]
    if len(_story_cache)>500:
        keep=set(current_urls)
        for url in list(_story_cache):
            if url not in keep and len(_story_cache)>300:
                _story_cache.pop(url,None)
    if not rows:
        raise PiQReadError("no_timestamped_stories_resolved")
    rows.sort(key=lambda row:row.get("created_at") or "",reverse=True)
    discovery_url=discovered[0].get("discovery_url") if discovered else BASE
    return rows[:max(1,int(limit))],discovery_url
