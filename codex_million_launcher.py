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
  self.state={"online":False,"status":"STARTING","experiment":"codex_million_dollar","positions":[],"trades":[],"tokens":[]};self._last_log=None
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
  # Frozen Codex revision a01bc1d0 publishes its live strategy as
  # "strategy1_primary" (newer PANDORA builds use "pandora"). Accept both
  # shapes so the bridge exposes the ACTUAL Codex scanner/positions/history.
  p=payload.get("strategy1_primary") or payload.get("pandora") or {};h=payload.get("health") or {}
  self._publish(online=True,status="PAPER_RUNNING" if h.get("engine_active") else "PAPER_WARMING",
   last_good_epoch=time.time(),updated_at=payload.get("snapshot_at"),starting_equity=p.get("starting_equity",500),
   equity=p.get("total_equity"),realized_pnl=p.get("realized_pnl"),unrealized_pnl=p.get("unrealized_pnl"),
   positions=p.get("open_positions") or [],trades=p.get("closed_trades") or [],tokens=p.get("tokens") or [],
   discovery=payload.get("discovery") or {},events=p.get("events") or {},statistics=p.get("statistics"),
   total_pnl_usdt=p.get("total_pnl_usdt"),total_pnl_percent=p.get("total_pnl_percent"),
   max_equity=p.get("max_equity"),account=p.get("account") or {},runtime=p.get("runtime") or {},
   pyramid_adds=p.get("pyramid_adds") or [],re_entries=p.get("re_entries") or [],
   reversals=p.get("reversals") or [],token_rotations=p.get("token_rotations") or [],
   sources=payload.get("sources") or {},entry_diagnostics=payload.get("strategy1_entry_diagnostics") or {},
   risk_ready=h.get("risk_ready"),health=h,health_error=h.get("engine_error"),
   frozen_revision="a01bc1d0c9c216ddb28c75b31fb42e1248867a0d",error=None)
  summary=(h.get("engine_active"),len(p.get("tokens") or []),len(p.get("open_positions") or []),len(p.get("closed_trades") or []),(payload.get("discovery") or {}).get("selection_frozen"))
  if summary!=self._last_log:
   self._last_log=summary
   print("[CODEX_MILLION] engine_active=%s discovery=%s open=%s closed=%s selection_frozen=%s risk_ready=%s" % (summary[0],summary[1],summary[2],summary[3],summary[4],h.get("risk_ready")),flush=True)
 def run(self,stop):
  env=os.environ.copy();env.pop("PGOPTIONS",None);env.update(PORT="10002",DATABASE_URL=self._isolated_url(),PYTHONUNBUFFERED="1",
   PANDORA_ENABLE_BEDA="0",PANDORA_COMPARISON_ENGINES="0",
   RENDER_EXTERNAL_URL="http://127.0.0.1:10002")
  while not stop.is_set():
   if self.process is None or self.process.poll() is not None:
    self._publish(online=False,status="STARTING_ENGINE")
    self.process=subprocess.Popen([sys.executable,"app.py"],cwd=self.root,env=env)
   try:self._poll()
   except Exception as exc:
    self._publish(online=False,status="WAITING_API",error=type(exc).__name__+":"+str(exc)[:160])
    summary=("ERROR",type(exc).__name__,str(exc)[:120])
    if summary!=self._last_log:
     self._last_log=summary;print("[CODEX_MILLION] poll_error=%s:%s" % (type(exc).__name__,str(exc)[:160]),flush=True)
   stop.wait(5)
  if self.process is not None and self.process.poll() is None:
   try:self.process.terminate();self.process.wait(timeout=6)
   except Exception:
    try:self.process.kill()
    except Exception:pass

CODEX=CodexBridge()
