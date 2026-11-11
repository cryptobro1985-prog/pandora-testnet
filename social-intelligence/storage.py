from __future__ import annotations
import json,sqlite3,os
from pathlib import Path
from datetime import datetime,timezone

DB=Path(os.getenv("IG_INTEL_DB","/tmp/instagram_intelligence.sqlite3"))

def connect():
    DB.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.executescript("""
    create table if not exists scan_runs(id integer primary key autoincrement,username text,started_at text,finished_at text,status text,sources_json text,warnings_json text);
    create table if not exists snapshots(id integer primary key autoincrement,username text not null,created_at text not null,followers_json text,following_json text,profile_json text not null);
    create index if not exists idx_snap_user on snapshots(username,id);
    create table if not exists interactions(id integer primary key autoincrement,username text,observed_at text,kind text,actor text,direction text,event_time text,url text,text text,source text,dedupe_key text unique);
    create table if not exists posts(id integer primary key autoincrement,username text,observed_at text,shortcode text,permalink text,data_json text,unique(username,shortcode));
    """)
    return c

def begin_run(username):
    now=datetime.now(timezone.utc).isoformat(); c=connect()
    cur=c.execute("insert into scan_runs(username,started_at,status) values(?,?,?)",(username,now,"running")); c.commit(); rid=cur.lastrowid;c.close();return rid

def finish_run(run_id,status,sources,warnings):
    c=connect(); c.execute("update scan_runs set finished_at=?,status=?,sources_json=?,warnings_json=? where id=?",
      (datetime.now(timezone.utc).isoformat(),status,json.dumps(sources,ensure_ascii=False),json.dumps(warnings,ensure_ascii=False),run_id));c.commit();c.close()

def save_posts(username,posts):
    c=connect(); now=datetime.now(timezone.utc).isoformat()
    for p in posts or []:
        sc=p.get("shortcode") or str(p.get("id") or "")
        if not sc: continue
        c.execute("insert into posts(username,observed_at,shortcode,permalink,data_json) values(?,?,?,?,?) on conflict(username,shortcode) do update set observed_at=excluded.observed_at,permalink=excluded.permalink,data_json=excluded.data_json",
          (username,now,sc,p.get("permalink"),json.dumps(p,ensure_ascii=False)))
    c.commit();c.close()

def save_events(username,events):
    c=connect(); now=datetime.now(timezone.utc).isoformat()
    for e in events or []:
        key="|".join([username,e.get("kind") or "",str(e.get("actor") or "").lower(),e.get("timestamp") or "",e.get("url") or "",e.get("text") or ""])
        try:
            c.execute("insert into interactions(username,observed_at,kind,actor,direction,event_time,url,text,source,dedupe_key) values(?,?,?,?,?,?,?,?,?,?)",
              (username,now,e.get("kind"),e.get("actor"),e.get("direction"),e.get("timestamp"),e.get("url"),e.get("text"),e.get("source"),key))
        except sqlite3.IntegrityError: pass
    c.commit();c.close()

def history(username,limit=200):
    c=connect(); rows=c.execute("select kind,actor,direction,event_time as timestamp,url,text,source from interactions where username=? order by coalesce(event_time,observed_at) desc limit ?",(username,limit)).fetchall();c.close()
    return [dict(r) for r in rows]
