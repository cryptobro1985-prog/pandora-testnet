from __future__ import annotations
from collections import defaultdict
from datetime import datetime,timezone
from math import log1p,exp

WEIGHTS={"comment_in":3.0,"like_in":1.0,"mention_out":4.0,"tag_out":4.0,"coauthor_out":5.0,"follow_in":2.0,"follow_out":2.0}

def _usernames(items):
    out=set()
    for x in items or []:
        if isinstance(x,dict): u=x.get("username")
        else: u=x
        if u: out.add(str(u).lower())
    return out

def build_events(target,posts):
    events=[]
    seen=set()
    def add(kind,actor,ts=None,url=None,text=None,source="observed"):
        if not actor: return
        actor=str(actor).strip()
        if not actor or actor.lower()==target.lower(): return
        key=(kind,actor.lower(),ts or "",url or "",text or "")
        if key in seen: return
        seen.add(key)
        direction="inbound" if kind.endswith("_in") else "outbound"
        events.append({"kind":kind,"actor":actor,"direction":direction,"timestamp":ts,"url":url,"text":text or "","source":source,"observability":"observed"})
    for p in posts or []:
        url=p.get("permalink"); ts=p.get("timestamp")
        for c in p.get("comments_detail") or []:
            add("comment_in",c.get("username"),c.get("timestamp") or ts,url,c.get("text"),"comment")
            for rep in c.get("replies") or []:
                add("comment_in",rep.get("username"),rep.get("timestamp") or ts,url,rep.get("text"),"reply")
        for u in p.get("likers") or []: add("like_in",u,ts,url,source="visible_liker")
        for u in p.get("mentions") or []: add("mention_out",u,ts,url,source="caption_mention")
        for u in p.get("tagged_users") or []: add("tag_out",u,ts,url,source="media_tag")
        for u in p.get("coauthors") or []: add("coauthor_out",u,ts,url,source="coauthor")
    return events

def relationship_report(target,events,followers=None,following=None):
    agg=defaultdict(lambda:{"comments_in":0,"likes_in":0,"mentions_out":0,"tags_out":0,"coauthors_out":0,"events":0,"raw_in":0.0,"raw_out":0.0,"last_seen":None})
    for e in events or []:
        actor=str(e.get("actor") or "").lower()
        if not actor or actor==target.lower(): continue
        kind=e.get("kind"); w=WEIGHTS.get(kind,1.0); a=agg[actor]
        a["events"]+=1
        if e.get("direction")=="inbound": a["raw_in"]+=w
        else: a["raw_out"]+=w
        if kind=="comment_in": a["comments_in"]+=1
        elif kind=="like_in": a["likes_in"]+=1
        elif kind=="mention_out": a["mentions_out"]+=1
        elif kind=="tag_out": a["tags_out"]+=1
        elif kind=="coauthor_out": a["coauthors_out"]+=1
        ts=e.get("timestamp")
        if ts and (not a["last_seen"] or ts>a["last_seen"]): a["last_seen"]=ts
    fs=_usernames(followers); fg=_usernames(following)
    all_users=set(agg)|fs|fg
    rows=[]
    for u in all_users:
        a=agg[u]
        follows_target=u in fs
        target_follows=u in fg
        badges=[]
        if follows_target: badges.append("followers")
        if target_follows: badges.append("following")
        if follows_target and target_follows: badges.append("mutuals")
        elif target_follows and not follows_target and followers is not None: badges.append("notFollowingBack")
        elif follows_target and not target_follows and following is not None: badges.append("notFollowedBack")
        inbound=round(log1p(a["raw_in"])*10,2)
        outbound=round(log1p(a["raw_out"])*10,2)
        mutual_bonus=8 if follows_target and target_follows else 0
        total=round(inbound+outbound+mutual_bonus,2)
        rows.append({"username":u,**a,"inbound_score":inbound,"outbound_score":outbound,"mutual_score":mutual_bonus,"score":total,"badges":badges,
                     "follows_target":follows_target if followers is not None else None,"target_follows":target_follows if following is not None else None})
    rows.sort(key=lambda x:(x["score"],x["events"]),reverse=True)
    return rows

def audience_quality(followers,events):
    if followers is None:
        return {"status":"unknown","reason":"followers_not_observed"}
    follower_names=_usernames(followers)
    engaged={str(e.get("actor")).lower() for e in events or [] if e.get("direction")=="inbound" and e.get("actor")}
    if not follower_names:
        return {"status":"ok","followers":0,"engaged_followers":0,"ghost_candidates":0,"ghost_percentage":0.0,"ghost_users":[]}
    engaged_followers=sorted(follower_names & engaged)
    ghosts=sorted(follower_names-engaged)
    return {"status":"ok","followers":len(follower_names),"engaged_followers":len(engaged_followers),"ghost_candidates":len(ghosts),
            "ghost_percentage":round(100*len(ghosts)/len(follower_names),1),"ghost_users":ghosts}

def graph_payload(target,relationships,limit=50):
    nodes=[{"id":target,"label":"@"+target,"type":"target","score":100}]
    edges=[]
    for r in (relationships or [])[:limit]:
        nodes.append({"id":r["username"],"label":"@"+r["username"],"type":"peer","score":r["score"],"badges":r["badges"]})
        edges.append({"source":target,"target":r["username"],"weight":r["score"],"inbound":r["inbound_score"],"outbound":r["outbound_score"]})
    return {"nodes":nodes,"edges":edges}

def timeline(events,changes):
    out=[dict(e) for e in events or []]
    at=changes.get("snapshot_at") if changes else None
    for u in changes.get("new_followers",[]) if changes else []:
        out.append({"kind":"follow_in","actor":u,"direction":"inbound","timestamp":at,"source":"snapshot_diff","observability":"observed"})
    for u in changes.get("lost_followers",[]) if changes else []:
        out.append({"kind":"unfollow_in","actor":u,"direction":"inbound","timestamp":at,"source":"snapshot_diff","observability":"observed"})
    for u in changes.get("new_following",[]) if changes else []:
        out.append({"kind":"follow_out","actor":u,"direction":"outbound","timestamp":at,"source":"snapshot_diff","observability":"observed"})
    for u in changes.get("unfollowed",[]) if changes else []:
        out.append({"kind":"unfollow_out","actor":u,"direction":"outbound","timestamp":at,"source":"snapshot_diff","observability":"observed"})
    out.sort(key=lambda x:x.get("timestamp") or "",reverse=True)
    return out
