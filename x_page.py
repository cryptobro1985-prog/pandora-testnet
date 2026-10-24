"""Logged-out X profile page fallback.
Reads the server-rendered GraphQL timeline embedded as a seroval JavaScript literal.
Derived from the MIT FreshRSS XProfiles parser, reduced to text/id/date/author only.
"""
import datetime as dt
import html as htmlmod
import re

from curl_cffi import requests as curl_requests

UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
SCRIPT_RE=re.compile(r"<script[^>]*>(.*?)</script>",re.I|re.S)
START_RE=re.compile(r"^\(\$R=>\$R\[\d+\]\.next\(")

class Reader:
    def __init__(self,src,pos=0):
        self.s=src;self.i=pos;self.depth=0

    def ws(self):
        n=len(self.s)
        while self.i<n and self.s[self.i].isspace():self.i+=1

    def value(self):
        while True:
            m=re.match(r"\s*\$R\[\d+\]=",self.s[self.i:])
            if not m:break
            self.i+=len(m.group(0))
        self.ws()
        if self.i>=len(self.s):raise ValueError("eof")
        ch=self.s[self.i]
        if ch=="{":return self.obj()
        if ch=="[":return self.arr()
        if ch in ('"',"'"):return self.string()
        m=re.match(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?",self.s[self.i:])
        if m:
            t=m.group(0);self.i+=len(t)
            return float(t) if any(x in t for x in ".eE") else int(t)
        for word,val in (("!0",True),("!1",False),("true",True),("false",False),("null",None),("void 0",None),("undefined",None)):
            if self.s.startswith(word,self.i):
                self.i+=len(word);return val
        m=re.match(r"\$R\[\d+\]",self.s[self.i:])
        if m:
            self.i+=len(m.group(0));return None
        raise ValueError("unexpected@"+str(self.i))

    def obj(self):
        self.depth+=1
        if self.depth>256:raise ValueError("deep")
        self.i+=1;out={};self.ws()
        if self.i<len(self.s) and self.s[self.i]=="}":
            self.i+=1;self.depth-=1;return out
        while True:
            self.ws()
            if self.i>=len(self.s):raise ValueError("eof obj")
            if self.s[self.i] in ('"',"'"):
                key=self.string()
            else:
                m=re.match(r"[A-Za-z_$][A-Za-z0-9_$]*|\d+",self.s[self.i:])
                if not m:raise ValueError("bad key")
                key=m.group(0);self.i+=len(key)
            self.ws()
            if self.i>=len(self.s) or self.s[self.i]!=":":raise ValueError("colon")
            self.i+=1;out[key]=self.value();self.ws()
            if self.i>=len(self.s):raise ValueError("eof obj2")
            ch=self.s[self.i];self.i+=1
            if ch=="}":
                self.depth-=1;return out
            if ch!=",":raise ValueError("comma")

    def arr(self):
        self.depth+=1
        if self.depth>256:raise ValueError("deep")
        self.i+=1;out=[];self.ws()
        if self.i<len(self.s) and self.s[self.i]=="]":
            self.i+=1;self.depth-=1;return out
        while True:
            self.ws()
            if self.i<len(self.s) and self.s[self.i]==",":
                out.append(None)
            else:
                out.append(self.value())
            self.ws()
            if self.i>=len(self.s):raise ValueError("eof arr")
            ch=self.s[self.i];self.i+=1
            if ch=="]":
                self.depth-=1;return out
            if ch!=",":raise ValueError("arr comma")

    def string(self):
        quote=self.s[self.i];self.i+=1;out=[];n=len(self.s)
        while self.i<n:
            ch=self.s[self.i];self.i+=1
            if ch==quote:return "".join(out)
            if ch!="\\":
                out.append(ch);continue
            if self.i>=n:break
            e=self.s[self.i];self.i+=1
            simple={"n":"\n","t":"\t","r":"\r","b":"\b","f":"\f","v":"\v","0":"\0","\\":"\\",'"':'"',"'":"'"}
            if e in simple:out.append(simple[e]);continue
            if e=="x" and self.i+2<=n:
                try:out.append(chr(int(self.s[self.i:self.i+2],16)));self.i+=2;continue
                except Exception:pass
            if e=="u":
                if self.i<len(self.s) and self.s[self.i]=="{":
                    j=self.s.find("}",self.i+1)
                    if j>self.i:
                        try:out.append(chr(int(self.s[self.i+1:j],16)));self.i=j+1;continue
                        except Exception:pass
                if self.i+4<=n:
                    try:out.append(chr(int(self.s[self.i:self.i+4],16)));self.i+=4;continue
                    except Exception:pass
            out.append(e)
        raise ValueError("unterminated string")

def _find_timeline(node,depth=0):
    if depth>14:return None
    if isinstance(node,dict):
        if node.get("kind")=="Result.Ok" and isinstance(node.get("value"),str):
            import json
            try:node={**node,"value":json.loads(node["value"])}
            except Exception:pass
        tl=node.get("timeline")
        if isinstance(tl,dict) and isinstance(tl.get("instructions"),list):
            return tl["instructions"]
        for v in node.values():
            found=_find_timeline(v,depth+1)
            if found is not None:return found
    elif isinstance(node,list):
        for v in node:
            found=_find_timeline(v,depth+1)
            if found is not None:return found
    return None

def _path(node,*keys):
    cur=node
    for k in keys:
        if not isinstance(cur,dict):return None
        cur=cur.get(k)
    return cur

def _unwrap(tweet):
    if not isinstance(tweet,dict):return None
    if tweet.get("__typename")=="TweetWithVisibilityResults":
        tweet=tweet.get("tweet")
    return tweet if isinstance(tweet,dict) and tweet.get("__typename")=="Tweet" else None

def _tweet_to_post(raw,requested):
    t=_unwrap(raw)
    if not t:return None
    ident=str(t.get("rest_id") or "")
    author=_path(t,"core","user_results","result") or {}
    handle=_path(author,"core","screen_name") or _path(author,"legacy","screen_name") or ""
    if not ident or not handle or handle.lower()!=requested.lower():return None
    note=_path(t,"note_tweet","note_tweet_results","result")
    text=(note.get("text") if isinstance(note,dict) else None) or _path(t,"details","full_text") or _path(t,"legacy","full_text") or ""
    text=htmlmod.unescape(str(text)).strip()
    if not text:return None
    ms=_path(t,"details","created_at_ms")
    if isinstance(ms,(int,float)):
        created=dt.datetime.fromtimestamp(float(ms)/1000,dt.timezone.utc).isoformat()
    else:
        created=_path(t,"legacy","created_at")
    return {"id":ident,"text":text,"created_at":created,"url":"https://x.com/"+handle+"/status/"+ident}

def parse(html,handle):
    for script in SCRIPT_RE.findall(html):
        if "GraphQLRequestStream.Completed" not in script:continue
        m=START_RE.match(script)
        if not m:continue
        try:msg=Reader(script,m.end()).value()
        except Exception:continue
        instructions=_find_timeline(msg)
        if not instructions:continue
        out={}
        for ins in instructions:
            if not isinstance(ins,dict):continue
            entries=list(ins.get("entries") or [])
            if isinstance(ins.get("entry"),dict):entries.append(ins["entry"])
            for entry in entries:
                raw=_path(entry,"content","content","tweet_results","result")
                post=_tweet_to_post(raw,handle)
                if post:out[post["id"]]=post
        if out:return list(out.values())
    raise RuntimeError("x_page_no_embedded_timeline")

def fetch(handle,timeout=7):
    url="https://x.com/"+handle
    r=curl_requests.get(url,headers={"User-Agent":UA,"Accept":"text/html,application/xhtml+xml","Cache-Control":"no-cache"},impersonate="chrome146",timeout=timeout)
    if r.status_code!=200:raise RuntimeError("x_page_http_"+str(r.status_code))
    body=r.text or ""
    if "GraphQLRequestStream.Completed" not in body:
        low=body[:10000].lower()
        if "challenge" in low or "captcha" in low or "cloudflare" in low:
            raise RuntimeError("x_page_challenge")
        raise RuntimeError("x_page_timeline_missing")
    return parse(body,handle)
