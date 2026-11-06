"""Render status endpoint + background 3-month Pump.fun wallet graph crawler.
Research-only: no order submission, no private keys.
"""
import datetime,json,os,threading,time,traceback
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from research.solana_wallet_leaders import three_month_crawler as crawler

START=datetime.datetime.now(datetime.timezone.utc).isoformat()
status={"started_at":START,"runs":0,"last_run":None,"last_error":None,"running":False,"mode":"PUMPFUN_3M_WALLET_GRAPH"}
lock=threading.Lock()

def loop():
    while True:
        with lock: status["running"]=True
        try:
            report=crawler.run_chunk()
            with lock:
                status["runs"]+=1
                status["last_run"]=datetime.datetime.now(datetime.timezone.utc).isoformat()
                status["last_error"]=None
                status["progress"]=report.get("progress",{})
                status["pump_tiers"]=report.get("pump_tiers",{})
                status["top_candidates"]=report.get("top_wallets",[])[:10]
        except Exception as exc:
            traceback.print_exc()
            with lock: status["last_error"]=str(exc)[:1000]
        finally:
            with lock: status["running"]=False
        time.sleep(max(5,int(os.getenv("RESEARCH_INTERVAL_SECONDS","10"))))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/","/health","/report"):
            self.send_error(404);return
        with lock: payload=dict(status)
        if self.path=="/report":
            try: payload["research"]=json.loads(crawler.REPORT.read_text())
            except Exception: payload["research"]={"status":"no_report_yet"}
        data=json.dumps(payload,ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers();self.wfile.write(data)
    def log_message(self,*args): pass

if __name__=="__main__":
    threading.Thread(target=loop,daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0",int(os.getenv("PORT","10000"))),Handler).serve_forever()
