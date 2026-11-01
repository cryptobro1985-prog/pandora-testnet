"""Independent Pandora Beda PAPER worker, supervised inside the existing Render service.

Beda is a separate Python process and a separate PostgreSQL schema. The
original Flow V2 decision engine is vendored unchanged. No RAW tape is recorded.
"""
import copy,datetime,json,os,re,subprocess,sys,threading,time,urllib.request
from pathlib import Path

class BedaBridge:
 def __init__(self):
  self.lock=threading.RLock();self.state=dict(online=False,status="STARTING",
   experiment="pandora_beda",starting_equity=500.,positions=[],trades=[])
  self.process=None;self.root=Path(__file__).resolve().parent/"pandora_beda"

 def snapshot(self):
  with self.lock:
   result=copy.deepcopy(self.state)
  if result.get("last_good_epoch") and time.time()-result["last_good_epoch"]>25:
   result["online"]=False;result["status"]="STALE"
  return result

 def _publish(self,**fields):
  with self.lock:self.state.update(fields)

 def _poll(self):
  req=urllib.request.Request("http://127.0.0.1:10001/api/pandora",
     headers={"Accept":"application/json","User-Agent":"pandora-beda-internal-bridge"})
  with urllib.request.urlopen(req,timeout=3) as resp:
   payload=json.load(resp)
  p=payload.get("pandora") or {};health=payload.get("health") or {}
  now=time.time()
  data=dict(online=True,status="PAPER_RUNNING" if health.get("engine_active") else "PAPER_WARMING",
   experiment="pandora_beda",last_good_epoch=now,updated_at=payload.get("snapshot_at"),
   starting_equity=float(p.get("starting_equity") or 500.),
   equity=p.get("total_equity"),realized_equity=(p.get("account") or {}).get("equity"),
   realized_pnl=p.get("realized_pnl"),unrealized_pnl=p.get("unrealized_pnl"),
   positions=(p.get("open_positions") or [])[:25],
   trades=(p.get("closed_trades") or [])[:40],
   statistics=p.get("statistics"),scanner=(payload.get("discovery") or {}).get("selected_symbols"),
   risk_ready=health.get("risk_ready"),risk_reason=(p.get("risk") or {}).get("reason"),
   health_error=health.get("engine_error"),error=None)
  self._publish(**data)

 def run(self,stop):
  print('[Pandora Beda] supervisor started',flush=True)
  env=os.environ.copy()
  env.update(PORT="10001",PANDORA_BEDA_PROCESS="1",PYTHONUNBUFFERED="1")
  # Distinct process and search_path: neither account nor lease touches V3.
  try:
   while not stop.is_set():
    if self.process is None or self.process.poll() is not None:
     self._publish(online=False,status="INITIALIZING")
     try:
      cmd=[sys.executable,"scripts/reset_paper_experiment.py"]
      result=subprocess.run(cmd,cwd=self.root,env=env,timeout=90,
               stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
      if result.returncode:
       # Only whitelisted error categories are emitted; database URIs,
       # role names and passwords are never logged.
       problem=re.search(r'PAPER initialization failed \(([A-Za-z]+)(?:; category=([A-Z_]+))?\)',result.stderr)
       reason=(problem.group(1)+":"+str(problem.group(2) or "UNCLASSIFIED")) if problem else (
          "SCRIPT_EXIT_"+str(result.returncode))
       self._publish(online=False,status="INIT_FAILED",error=reason)
       print("[Pandora Beda] PAPER initialization failed: "+reason,flush=True)
       stop.wait(15);continue
      print("[Pandora Beda] isolated PAPER schema initialized",flush=True)
      self.process=subprocess.Popen([sys.executable,"app.py"],cwd=self.root,env=env)
      self._publish(online=False,status="STARTING_ENGINE",error=None)
     except Exception as exc:
      self._publish(online=False,status="START_FAILED",error=type(exc).__name__)
      stop.wait(15);continue
    try:self._poll()
    except Exception as exc:
     self._publish(online=False,status="WAITING_API",error=type(exc).__name__)
    stop.wait(5)
  finally:
   if self.process is not None and self.process.poll() is None:
    try:self.process.terminate();self.process.wait(timeout=6)
    except Exception:
     try:self.process.kill()
     except Exception:pass

BEDA=BedaBridge()
