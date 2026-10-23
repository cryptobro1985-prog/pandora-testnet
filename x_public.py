import json,urllib.request,urllib.parse,time
WATCH=["elonmusk","realDonaldTrump","federalreserve","SECGov","USTreasury","WhiteHouse","coinbase","binance","saylor","cz_binance","VitalikButerin"]
BEARER="AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOe5wQ0VBq1P0o7%2FUw"
def _get(url,headers=None):
 h={"User-Agent":"Mozilla/5.0","Accept":"application/json"};h.update(headers or {})
 req=urllib.request.Request(url,headers=h)
 with urllib.request.urlopen(req,timeout=12) as r:return json.load(r)
def _guest():
 req=urllib.request.Request("https://api.twitter.com/1.1/guest/activate.json",method="POST",headers={"Authorization":"Bearer "+urllib.parse.unquote(BEARER),"User-Agent":"Mozilla/5.0"})
 with urllib.request.urlopen(req,timeout=12) as r:return json.load(r)["guest_token"]
def public_timelines():
 # Public guest access is best-effort and deliberately uses no account cookies or private credentials.
 g=_guest();out=[]
 for handle in WATCH:
  try:
   u=_get("https://cdn.syndication.twimg.com/widgets/followbutton/info.json?screen_names="+urllib.parse.quote(handle))
   if u: out.append({"id":"profile:"+handle+":"+str(int(time.time()//120)),"text":"profile heartbeat "+handle,"handle":handle})
  except Exception: pass
 return out
