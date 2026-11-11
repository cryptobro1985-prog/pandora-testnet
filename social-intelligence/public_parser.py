from __future__ import annotations
import json,re,datetime as dt
from bs4 import BeautifulSoup
from typing import Any

ROUTE_RE=re.compile(r'"canonicalRouteName"\s*:\s*"([A-Za-z0-9_.]+)"')
SHORTCODE_RE=re.compile(r"^[A-Za-z0-9_-]{5,64}$")

def page_route(html:str):
    m=ROUTE_RE.search(html or "")
    return m.group(1) if m else None

def has_embedded_data(html:str):
    s=html or ""
    return '"xig_user_by_username"' in s or '"xig_polaris_media"' in s

MENTION_RE=re.compile(r"(?<![\w.])@([A-Za-z0-9._]{1,30})")
HASHTAG_RE=re.compile(r"(?<![\w&])#(\w+)",re.U)

def json_blocks(html:str):
    out=[]
    for script in BeautifulSoup(html or "","html.parser").find_all("script",type="application/json"):
        raw=script.string or script.get_text()
        try: out.append(json.loads(raw))
        except Exception: pass
    return out

def _find_key(obj:Any,key:str):
    stack=[obj]
    while stack:
        cur=stack.pop()
        if isinstance(cur,dict):
            for k,v in cur.items():
                if k==key: yield v
                if isinstance(v,(dict,list)): stack.append(v)
        elif isinstance(cur,list):
            stack.extend(v for v in cur if isinstance(v,(dict,list)))

def _find_all(html,key):
    return [v for block in json_blocks(html) for v in _find_key(block,key) if isinstance(v,dict)]

def _usernames(items,path=()):
    names=[]
    for item in items or []:
        node=item
        for step in path:
            node=node.get(step) if isinstance(node,dict) else None
        name=node.get("username") if isinstance(node,dict) else None
        if isinstance(name,str) and name and name not in names: names.append(name)
    return names

def _iso(ts):
    try:
        n=int(ts)
        return dt.datetime.fromtimestamp(n,dt.timezone.utc).isoformat()
    except Exception: return None

def parse_profile(html:str,username:str):
    for user in _find_all(html,"xig_user_by_username"):
        if str(user.get("username","")).lower()!=username.lower() or "follower_count" not in user: continue
        pk=str(user.get("pk")) if user.get("pk") is not None else None
        posts=[]
        conn=user.get("polaris_ordered_timeline_connection")
        if isinstance(conn,dict):
            for edge in conn.get("edges") or []:
                node=edge.get("node") if isinstance(edge,dict) else None
                code=node.get("code") if isinstance(node,dict) else None
                if isinstance(code,str) and SHORTCODE_RE.fullmatch(code) and code not in posts: posts.append(code)
        return {
          "username":user.get("username") or username,
          "user_id":pk,
          "name":user.get("full_name") or "",
          "biography":user.get("biography") or "",
          "profile_picture_url":user.get("profile_pic_url"),
          "followers_count":user.get("follower_count"),
          "follows_count":user.get("following_count"),
          "is_verified":user.get("is_verified"),
          "is_private":user.get("is_private"),
          "bio_links":[x.get("url") for x in user.get("bio_links") or [] if isinstance(x,dict) and x.get("url")],
          "recent_post_codes":posts,
        }
    return None

def parse_post(html:str,shortcode:str):
    for wrapper in _find_all(html,"xig_polaris_media"):
        if wrapper.get("code")!=shortcode: continue
        media=wrapper.get("if_not_gated_logged_out")
        if not isinstance(media,dict): continue
        owner=media.get("user") if isinstance(media.get("user"),dict) else {}
        caption=(media.get("caption") or {}).get("text") if isinstance(media.get("caption"),dict) else media.get("caption")
        caption=caption or ""
        tagged=_usernames(((media.get("usertags") or {}).get("in") or []),path=("user",))
        coauthors=_usernames(media.get("coauthor_producers") or [])
        loc=media.get("location") if isinstance(media.get("location"),dict) else {}
        return {
          "id":media.get("pk") or media.get("id"),
          "shortcode":shortcode,
          "permalink":"https://www.instagram.com/p/"+shortcode+"/",
          "username":owner.get("username"),
          "owner_id":str(owner.get("pk")) if owner.get("pk") is not None else None,
          "timestamp":_iso(media.get("taken_at")),
          "caption":caption,
          "like_count":media.get("like_count"),
          "comments_count":media.get("comment_count"),
          "media_type":media.get("media_type"),
          "product_type":media.get("product_type"),
          "mentions":list(dict.fromkeys(x.rstrip(".") for x in MENTION_RE.findall(caption))),
          "hashtags":list(dict.fromkeys(HASHTAG_RE.findall(caption))),
          "tagged_users":tagged,
          "coauthors":coauthors,
          "location":{"id":loc.get("pk"),"name":loc.get("name"),"lat":loc.get("lat"),"lng":loc.get("lng")} if loc else None,
          "comments_detail":[],
          "likers":[]
        }
    return None
