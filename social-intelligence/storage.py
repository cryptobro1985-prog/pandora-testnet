from __future__ import annotations
import json,sqlite3,os
from pathlib import Path
from datetime import datetime,timezone

SQLITE_DB=Path(os.getenv("IG_INTEL_DB","/tmp/instagram_intelligence.sqlite3"))
DATABASE_URL=os.getenv("DATABASE_URL","").strip()

def _pg():
    return bool(DATABASE_URL)

def _connect():
    if _pg():
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(DATABASE_URL,row_factory=dict_row,autocommit=False)
    SQLITE_DB.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(SQLITE_DB);c.row_factory=sqlite3.Row
    return c

def init_schema():
    c=_connect()
    stmts=[
      """create table if not exists si_scan_runs(
        id {idtype},username text,started_at text,finished_at text,status text,sources_json text,warnings_json text)""",
      """create table if not exists si_snapshots(
        id {idtype},username text not null,created_at text not null,followers_json text,following_json text,profile_json text not null)""",
      "create index if not exists idx_si_snap_user on si_snapshots(username,id)",
      """create table if not exists si_interactions(
        id {idtype},username text,observed_at text,kind text,actor text,direction text,event_time text,url text,text text,source text,dedupe_key text unique)""",
      """create table if not exists si_posts(
        id {idtype},username text,observed_at text,shortcode text,permalink text,data_json text,unique(username,shortcode))"""
    ]
    idtype="bigserial primary key" if _pg() else "integer primary key autoincrement"
    for s in stmts:
        c.execute(s.format(idtype=idtype))
    c.commit();c.close()

def get_last_snapshot(username):
    c=_connect()
    sql="select * from si_snapshots where username=%s order by id desc limit 1" if _pg() else "select * from si_snapshots where username=? order by id desc limit 1"
    row=c.execute(sql,(username,)).fetchone();c.close();return row

def save_snapshot(username,created_at,followers_json,following_json,profile_json):
    c=_connect()
    sql="insert into si_snapshots(username,created_at,followers_json,following_json,profile_json) values(%s,%s,%s,%s,%s)" if _pg() else "insert into si_snapshots(username,created_at,followers_json,following_json,profile_json) values(?,?,?,?,?)"
    c.execute(sql,(username,created_at,followers_json,following_json,profile_json));c.commit();c.close()

def begin_run(username):
    now=datetime.now(timezone.utc).isoformat();c=_connect()
    if _pg():
        row=c.execute("insert into si_scan_runs(username,started_at,status) values(%s,%s,%s) returning id",(username,now,"running")).fetchone()
        rid=row["id"]
    else:
        cur=c.execute("insert into si_scan_runs(username,started_at,status) values(?,?,?)",(username,now,"running"));rid=cur.lastrowid
    c.commit();c.close();return rid

def finish_run(run_id,status,sources,warnings):
    c=_connect();vals=(datetime.now(timezone.utc).isoformat(),status,json.dumps(sources,ensure_ascii=False),json.dumps(warnings,ensure_ascii=False),run_id)
    sql="update si_scan_runs set finished_at=%s,status=%s,sources_json=%s,warnings_json=%s where id=%s" if _pg() else "update si_scan_runs set finished_at=?,status=?,sources_json=?,warnings_json=? where id=?"
    c.execute(sql,vals);c.commit();c.close()

def save_posts(username,posts):
    c=_connect();now=datetime.now(timezone.utc).isoformat()
    for p in posts or []:
        sc=p.get("shortcode") or str(p.get("id") or "")
        if not sc: continue
        vals=(username,now,sc,p.get("permalink"),json.dumps(p,ensure_ascii=False))
        if _pg():
            sql="""insert into si_posts(username,observed_at,shortcode,permalink,data_json) values(%s,%s,%s,%s,%s)
                   on conflict(username,shortcode) do update set observed_at=excluded.observed_at,permalink=excluded.permalink,data_json=excluded.data_json"""
        else:
            sql="""insert into si_posts(username,observed_at,shortcode,permalink,data_json) values(?,?,?,?,?)
                   on conflict(username,shortcode) do update set observed_at=excluded.observed_at,permalink=excluded.permalink,data_json=excluded.data_json"""
        c.execute(sql,vals)
    c.commit();c.close()

def save_events(username,events):
    c=_connect();now=datetime.now(timezone.utc).isoformat()
    for e in events or []:
        key="|".join([username,e.get("kind") or "",str(e.get("actor") or "").lower(),e.get("timestamp") or "",e.get("url") or "",e.get("text") or ""])
        vals=(username,now,e.get("kind"),e.get("actor"),e.get("direction"),e.get("timestamp"),e.get("url"),e.get("text"),e.get("source"),key)
        if _pg():
            sql="""insert into si_interactions(username,observed_at,kind,actor,direction,event_time,url,text,source,dedupe_key)
                   values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict(dedupe_key) do nothing"""
            c.execute(sql,vals)
        else:
            try:
                c.execute("""insert into si_interactions(username,observed_at,kind,actor,direction,event_time,url,text,source,dedupe_key)
                             values(?,?,?,?,?,?,?,?,?,?)""",vals)
            except sqlite3.IntegrityError: pass
    c.commit();c.close()

def history(username,limit=200):
    c=_connect()
    if _pg():
        rows=c.execute("select kind,actor,direction,event_time as timestamp,url,text,source from si_interactions where username=%s order by coalesce(event_time,observed_at) desc limit %s",(username,limit)).fetchall()
    else:
        rows=c.execute("select kind,actor,direction,event_time as timestamp,url,text,source from si_interactions where username=? order by coalesce(event_time,observed_at) desc limit ?",(username,limit)).fetchall()
    c.close();return [dict(r) for r in rows]

def backend_info():
    return {"persistence":"postgres" if _pg() else "sqlite_ephemeral","database_url_configured":_pg()}
