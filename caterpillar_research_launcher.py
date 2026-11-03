"""Background bridge for the isolated Caterpillar Research v2 PAPER process.

Runs inside the existing Render service so it consumes no second Render service.
The heavy 30-day archive research is intentionally NOT launched here; that runs
in GitHub Actions. This bridge is only for the six-hour realtime OOS observer.
"""
from __future__ import annotations
import copy,json,os,subprocess,sys,threading,time
from pathlib import Path

class CaterpillarResearchBridge:
    def __init__(self):
        self.lock=threading.RLock()
        self.process=None
        self.root=Path("/app/research/caterpillar")
        self.output=Path("/tmp/caterpillar-research-live")
        self.state={
            "enabled":os.getenv("CATERPILLAR_RESEARCH_ENABLE","0")=="1",
            "online":False,"status":"DISABLED","mode":"PAPER_RESEARCH_ONLY",
            "hours":6,"symbols":["ZEC","HYPE","NEAR","SOL","ENA","1000PEPE","DOGE","SUI","AAVE","WLD"],
            "historical_30d":"external_github_actions",
        }

    def snapshot(self):
        with self.lock:
            state=copy.deepcopy(self.state)
        try:
            path=self.output/"research_status.json"
            if path.is_file():
                payload=json.loads(path.read_text())
                state["research_status"]=payload
                state["status_updated_at"]=payload.get("iso_utc")
        except Exception as exc:
            state["snapshot_error"]=type(exc).__name__+":"+str(exc)[:160]
        if self.process is not None:
            state["process_returncode"]=self.process.poll()
            state["online"]=self.process.poll() is None
        return state

    def _publish(self,**kw):
        with self.lock:self.state.update(kw)

    def _run_process(self,resume=False):
        cmd=[sys.executable,"-m","caterpillar","realtime_audit"]
        if resume:
            cmd += ["--resume"]
        else:
            cmd += ["--hours","6","--market-context"]
        cmd += ["--output",str(self.output)]
        env=os.environ.copy()
        env.update(PYTHONUNBUFFERED="1")
        self.process=subprocess.Popen(
            cmd,cwd=self.root,env=env,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            text=True,bufsize=1)
        self._publish(online=True,status="RUNNING",started_epoch=time.time(),resume=resume)
        assert self.process.stdout is not None
        for line in self.process.stdout:
            print("[CATERPILLAR_RESEARCH] "+line.rstrip(),flush=True)
        code=self.process.wait()
        self._publish(online=False,returncode=code,
                      status="COMPLETED" if code==0 else "FAILED",
                      finished_epoch=time.time())
        return code

    def run(self,stop):
        if not self.state["enabled"]:
            self._publish(status="DISABLED")
            while not stop.wait(60):pass
            return
        self.output.mkdir(parents=True,exist_ok=True)
        attempted_resume=False
        while not stop.is_set():
            resume=(self.output/"checkpoint.json").is_file() and not attempted_resume
            attempted_resume=True
            try:
                code=self._run_process(resume=resume)
            except Exception as exc:
                self._publish(online=False,status="ERROR",
                              error=type(exc).__name__+":"+str(exc)[:200])
                code=1
            if code==0:
                # Six-hour run completed. Never silently start a second experiment.
                while not stop.wait(60):pass
                return
            # Same container: one checkpoint-aware retry is useful. A new Render
            # instance loses /tmp and therefore starts a new explicitly separate run.
            if (self.output/"checkpoint.json").is_file() and not stop.wait(5):
                try:
                    code=self._run_process(resume=True)
                    if code==0:
                        while not stop.wait(60):pass
                        return
                except Exception as exc:
                    self._publish(online=False,status="ERROR",
                                  error=type(exc).__name__+":"+str(exc)[:200])
            while not stop.wait(60):pass
            return

RESEARCH=CaterpillarResearchBridge()
