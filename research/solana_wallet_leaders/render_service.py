"""Render HTTP health/status and best-effort background Solana observations.
Free Render services sleep on idle; this is not a guaranteed nonstop worker.
"""
import datetime,json,os,pathlib,threading,time,traceback
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from research.solana_wallet_leaders import collector
START=datetime.datetime.now(datetime.timezone.utc).isoformat()
status={"started_at":START,"runs":0,"last_run":None,"last_error":None,"running":False}
lock=threading.Lock()
def loop():
    while True:
        with lock:status["running"]=True
        try:
            collector.main()
            with lock:
                status["runs"]+=1
                status["last_run"]=datetime.datetime.now(datetime.timezone.utc).isoformat()
                status["last_error"]=None
        except Exception as exc:
            traceback.print_exc()
            with lock:status["last_error"]=str(exc)[:500]
        finally:
            with lock:status["running"]=False
        time.sleep(max(60,int(os.getenv("RESEARCH_INTERVAL_SECONDS","300"))))
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/","/health","/report"):
            self.send_error(404);return
        with lock:payload=dict(status)
        if self.path=="/report":
            try:payload["research"]=json.loads(collector.REPORT.read_text())
            except Exception:payload["research"]={"status":"no_report_yet"}
        data=json.dumps(payload,ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def log_message(self,*args):pass
if __name__=="__main__":
    threading.Thread(target=loop,daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0",int(os.getenv("PORT","10000"))),Handler).serve_forever()
