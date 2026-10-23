import json,os,time,threading,urllib.request,sqlite3,datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
DB="/tmp/pandora.sqlite3"
URL="https://api.hyperliquid-testnet.xyz/info"
state={"mode":"paper","orders_enabled":False,"polls":0,"errors":0,"last_poll":None,"last_error":None,"btc_mid":None,"eth_mid":None}
def fetch(payload):
 req=urllib.request.Request(URL,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json","User-Agent":"PANDORA-testnet/1"})
 with urllib.request.urlopen(req,timeout=15) as r:return json.load(r)
def loop():
 while True:
  try:
   mids=fetch({"type":"allMids"})
   state.update(polls=state["polls"]+1,last_poll=datetime.datetime.now(datetime.timezone.utc).isoformat(),btc_mid=mids.get("BTC"),eth_mid=mids.get("ETH"),last_error=None)
   with sqlite3.connect(DB) as db:
    db.execute("create table if not exists snapshots (ts text, btc text, eth text)")
    db.execute("insert into snapshots values (?,?,?)",(state["last_poll"],state["btc_mid"],state["eth_mid"]))
  except Exception as e:
   state["errors"]+=1
   state["last_error"]=str(e)[:250]
  time.sleep(30)
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path not in ("/","/health","/status"):
   self.send_error(404);return
  data=json.dumps(state).encode()
  self.send_response(200)
  self.send_header("Content-Type","application/json")
  self.send_header("Content-Length",str(len(data)))
  self.end_headers();self.wfile.write(data)
if __name__=="__main__":
 threading.Thread(target=loop,daemon=True).start()
 ThreadingHTTPServer(("0.0.0.0",int(os.getenv("PORT","10000"))),Handler).serve_forever()
