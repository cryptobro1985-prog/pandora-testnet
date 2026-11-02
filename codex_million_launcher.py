"""Independent Codex Million Dollars PAPER worker.
Runs the frozen Codex revision in a separate process and PostgreSQL schema.
No private exchange API and no real orders.
"""
import copy,json,os,socket,subprocess,sys,threading,time,urllib.request,urllib.parse
from pathlib import Path
import psycopg

class CodexBridge:
 def __init__(self):
  self.lock=threading.RLock();self.process=None
  self.root=Path("/app/codex_engine")
  self.state={"online":False,"status":"STARTING","experiment":"codex_million_dollar","positions":[],"trades":[],"tokens":[]}
 def snapshot(self):
  with self.lock:r=copy.deepcopy(self.state)
  if r.get("last_good_epoch") and time.time()-r["last_good_epoch"]>25:r["online"]=False;r["status"]="STALE"
  return r
 def _publish(self,**kw):
  with self.lock:self.state.update(kw)
 def _isolated_url(self):
  base=os.environ["DATABASE_URL"]
  with psycopg.connect(base,autocommit=True) as db:db.execute("CREATE SCHEMA IF NOT EXISTS codex_million")
  # Keep the same reachable DATABASE_URL as PANDORA. PostgreSQL's PGOPTIONS
  # applies the schema at connection startup without rewriting the host/URL.
  return base
 def _poll(self):
  req=urllib.request.Request("http://127.0.0.1:10002/api/pandora",headers={"Accept":"application/json","User-Agent":"pandora-codex-bridge"})
  with urllib.request.urlopen(req,timeout=4) as resp:payload=json.load(resp)
  p=payload.get("pandora") or {};h=payload.get("health") or {}
  self._publish(online=True,status="PAPER_RUNNING" if h.get("engine_active") else "PAPER_WARMING",
   last_good_epoch=time.time(),updated_at=payload.get("snapshot_at"),starting_equity=p.get("starting_equity",500),
   equity=p.get("total_equity"),realized_pnl=p.get("realized_pnl"),unrealized_pnl=p.get("unrealized_pnl"),
   positions=p.get("open_positions") or [],trades=p.get("closed_trades") or [],tokens=p.get("tokens") or [],
   discovery=payload.get("discovery") or {},events=p.get("events") or {},statistics=p.get("statistics"),
   risk_ready=h.get("risk_ready"),health_error=h.get("engine_error"),error=None)
 def run(self,stop):
  env=os.environ.copy();env.update(PORT="10002",DATABASE_URL=self._isolated_url(),PGOPTIONS="-c search_path=codex_million",PYTHONUNBUFFERED="1",PANDORA_ENABLE_BEDA="0")
  while not stop.is_set():
   if self.process is None or self.process.poll() is not None:
    self._publish(online=False,status="STARTING_ENGINE")
    self.process=subprocess.Popen([sys.executable,"app.py"],cwd=self.root,env=env)
   try:self._poll()
   except Exception as exc:self._publish(online=False,status="WAITING_API",error=type(exc).__name__)
   stop.wait(5)
  if self.process is not None and self.process.poll() is None:
   try:self.process.terminate();self.process.wait(timeout=6)
   except Exception:
    try:self.process.kill()
    except Exception:pass

CODEX=CodexBridge()
