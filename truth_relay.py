import json,os,urllib.parse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from realtime_free import fetch_truth,fetch_truth_activitypub,fetch_truth_rss

TOKEN=os.getenv("RELAY_TOKEN","").strip()

class H(BaseHTTPRequestHandler):
 def do_GET(self):
  q=urllib.parse.urlsplit(self.path)
  if q.path=="/health":
   body=json.dumps({"ok":True}).encode();self.send_response(200);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body);return
  if q.path!="/truth":
   self.send_error(404);return
  args=urllib.parse.parse_qs(q.query)
  if TOKEN and args.get("token",[""])[0]!=TOKEN:
   self.send_error(401);return
  handle=args.get("handle",[""])[0].strip()
  if not handle or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for ch in handle):
   self.send_error(400);return
  errors=[]
  try:
   account_id,posts,headers=fetch_truth(handle)
   payload={"ok":True,"backend":"public_rest","handle":handle,"posts":posts}
  except Exception as exc:
   errors.append("rest:"+str(exc)[:100])
   try:
    posts=fetch_truth_activitypub(handle)
    payload={"ok":True,"backend":"activitypub","handle":handle,"posts":posts,"errors":errors}
   except Exception as exc2:
    errors.append("activitypub:"+str(exc2)[:100])
    try:
     posts=fetch_truth_rss(handle)
     payload={"ok":True,"backend":"profile_rss","handle":handle,"posts":posts,"errors":errors}
    except Exception as exc3:
     errors.append("rss:"+str(exc3)[:100])
     payload={"ok":False,"handle":handle,"posts":[],"errors":errors}
  body=json.dumps(payload,ensure_ascii=False).encode()
  self.send_response(200 if payload.get("ok") else 502)
  self.send_header("Content-Type","application/json; charset=utf-8")
  self.send_header("Cache-Control","no-store")
  self.send_header("Content-Length",str(len(body)))
  self.end_headers();self.wfile.write(body)

if __name__=="__main__":
 ThreadingHTTPServer(("0.0.0.0",int(os.getenv("PORT","10000"))),H).serve_forever()
