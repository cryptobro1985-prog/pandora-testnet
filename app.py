import os,json,time,threading,urllib.request,urllib.parse,sqlite3,datetime,xml.etree.ElementTree as ET,re,hashlib\nfrom adaptive import choose\nfrom x_source import recent\nfrom truth_source import user_statuses
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
API="https://api.hyperliquid-testnet.xyz/info"
DB="/tmp/pandora.sqlite3"
START=time.time()
S={"adaptive":{"samples":0,"changed":False},"mode":"PAPER_ONLY","orders_enabled":False,"last_poll":None,"market_count":0,"news_seen":0,"trades":0,"errors":0,"last_error":None,"sources":{},"positions":{},"equity":100.0,"realized_pnl":0.0}
LOCK=threading.RLock()
FEEDS={"FedOfficial":"https://www.federalreserve.gov/feeds/press_all.xml","SECOfficial":"https://www.sec.gov/news/pressreleases.rss","GoogleNewsCrypto":"https://news.google.com/rss/search?q=cryptocurrency+OR+bitcoin+OR+altcoin&hl=en-US&gl=US&ceid=US:en","GoogleNewsMarkets":"https://news.google.com/rss/search?q=crypto+SEC+OR+Federal+Reserve+OR+token+listing&hl=en-US&gl=US&ceid=US:en","Cointelegraph":"https://cointelegraph.com/rss","Decrypt":"https://decrypt.co/feed","CoinDesk":"https://www.coindesk.com/arc/outboundfeeds/rss/","CFTCOfficial":"https://www.cftc.gov/RSS/RSSGP/rssgp.xml","DOJNews":"https://www.justice.gov/feeds/opa/justice-news.xml","TruthSocialSearch":"https://news.google.com/rss/search?q=site%3Atruthsocial.com+crypto&hl=en-US&gl=US&ceid=US:en","XSearch":"https://news.google.com/rss/search?q=site%3Ax.com+cryptocurrency&hl=en-US&gl=US&ceid=US:en"}
POS=("surge","approve","approval","partnership","listing","adoption","buyback","breakout","bullish","launch","etf approved")
NEG=("hack","exploit","lawsuit","delist","ban","liquidation","fraud","selloff","bearish","crash","stolen")
STOP_ROE=-0.10;TAKE_ROE=0.20;LEV=10.0;MARGIN_FRACTION=0.25;FEE=0.00045;LOCK_TRIGGER_ROE=0.15;LOCK_ROE=0.075
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def get(url,body=None):
 data=None if body is None else json.dumps(body).encode()
 req=urllib.request.Request(url,data=data,headers={"User-Agent":"Mozilla/5.0 PANDORA-research/1.0","Content-Type":"application/json"})
 with urllib.request.urlopen(req,timeout=12) as r:return r.read()
def init():
 with sqlite3.connect(DB) as c:
  c.execute("create table if not exists news (id text primary key,ts text,source text,title text,symbol text,signal integer)")
  c.execute("create table if not exists trades (id integer primary key autoincrement,opened text,closed text,symbol text,side integer,entry real,exit real,pnl real,reason text,headline text)")
  c.execute("create table if not exists snapshots (ts text,markets integer,equity real,positions integer)")
def market():
 while True:
  try:
   mids=json.loads(get(API,{"type":"allMids"}))
   valid={k:float(v) for k,v in mids.items() if re.match(r"^[A-Z0-9]{2,15}$",k) and float(v)>0}
   with LOCK:
    S["last_poll"]=now();S["market_count"]=len(valid)
    for sym,p in valid.items():
     if sym in S["positions"]:
      pos=S["positions"][sym];move=(p/pos["entry"]-1)*pos["side"];roe=move*LEV
      if roe>=TAKE_ROE and not pos["locked"]:
       pos["locked"]=True;pos["stop"]=pos["entry"]*(1+pos["side"]*0.10/LEV)
      if roe<=STOP_ROE or (pos["locked"] and (p-pos["stop"])*pos["side"]<=0) or time.time()-pos["t"]>3600:
       reason="stop" if roe<=STOP_ROE else "locked" if pos["locked"] and (p-pos["stop"])*pos["side"]<=0 else "timeout"
       pnl=pos["notional"]*move-pos["notional"]*FEE*2
       S["equity"]+=pnl;S["realized_pnl"]+=pnl;S["trades"]+=1
       with sqlite3.connect(DB) as c:c.execute("insert into trades(opened,closed,symbol,side,entry,exit,pnl,reason,headline) values(?,?,?,?,?,?,?,?,?)",(pos["opened"],now(),sym,pos["side"],pos["entry"],p,pnl,reason,pos["headline"]))
       del S["positions"][sym]
    S["_prices"]=valid
    with sqlite3.connect(DB) as c:c.execute("insert into snapshots values(?,?,?,?)",(now(),len(valid),S["equity"],len(S["positions"])))
  except Exception as e:
   with LOCK:S["errors"]+=1;S["last_error"]="market: "+str(e)[:180]
  time.sleep(30)
def detect(title,prices):
 upper=title.upper()
 mentions=[k for k in prices if len(k)>=3 and re.search(r"(?<![A-Z0-9])"+re.escape(k)+r"(?![A-Z0-9])",upper)]
 if not mentions:
  if any(w in title.lower() for w in ("federal reserve","interest rates","inflation","bitcoin","crypto market","sec")):mentions=["BTC","ETH"]
  else:return None,0
 score=sum(w in title.lower() for w in POS)-sum(w in title.lower() for w in NEG)
 return (mentions[0] if mentions else None),(1 if score>0 else -1 if score<0 else 0)
def xnews():
 while True:
  try:
   posts=recent()
   with LOCK:S["sources"]["XOfficial"]={"ok":bool(os.getenv("X_BEARER_TOKEN","")),"last_check":now(),"posts":len(posts)}
   for p in posts:
    title=(p.get("text") or "").strip()
    if not title:continue
    ident=hashlib.sha256(("XOfficial"+str(p.get("id",title))).encode()).hexdigest()
    with LOCK:
     prices=S.get("_prices",{});sym,side=detect(title,prices)
     with sqlite3.connect(DB) as c:
      if c.execute("select 1 from news where id=?",(ident,)).fetchone():continue
      c.execute("insert into news values(?,?,?,?,?,?)",(ident,now(),"XOfficial",title,sym,side))
     S["news_seen"]+=1
  except Exception as e:
   with LOCK:S["sources"]["XOfficial"]={"ok":False,"last_check":now(),"error":str(e)[:140]}
  time.sleep(60)
def truthnews():
 while True:
  try:
   posts=user_statuses("realDonaldTrump",30)
   with LOCK:S["sources"]["TruthSocialPublic"]={"ok":True,"last_check":now(),"posts":len(posts)}
   for p in reversed(posts):
    title=re.sub("<[^>]+>"," ",p.get("content",""));title=re.sub(r"\\s+"," ",title).strip()
    if not title:continue
    ident=hashlib.sha256(("TruthSocialPublic"+str(p.get("id",title))).encode()).hexdigest()
    with LOCK:
     prices=S.get("_prices",{});sym,side=detect(title,prices)
     with sqlite3.connect(DB) as c:
      if c.execute("select 1 from news where id=?",(ident,)).fetchone():continue
      c.execute("insert into news values(?,?,?,?,?,?)",(ident,now(),"TruthSocialPublic",title,sym,side))
     S["news_seen"]+=1
  except Exception as e:
   with LOCK:S["sources"]["TruthSocialPublic"]={"ok":False,"last_check":now(),"error":str(e)[:140]}
  time.sleep(20)
def adapt():
 global STOP_ROE,TAKE_ROE
 while True:
  try:
   z=choose(DB,(STOP_ROE,TAKE_ROE))
   with LOCK:
    if z.get("changed"):STOP_ROE=float(z["stop"]);TAKE_ROE=float(z["take"])
    S["adaptive"]=z
  except Exception as e:
   with LOCK:S["last_error"]="adaptive: "+str(e)[:160]
  time.sleep(900)
def news():
 while True:
  for source,url in FEEDS.items():
   try:
    root=ET.fromstring(get(url))
    items=root.findall(".//item")[:30]
    count=0
    for item in reversed(items):
     title=(item.findtext("title") or "").strip()
     ident=hashlib.sha256((source+title).encode()).hexdigest()
     if not title:continue
     with LOCK:
      prices=S.get("_prices",{})
      sym,side=detect(title,prices)
      with sqlite3.connect(DB) as c:
       if c.execute("select 1 from news where id=?",(ident,)).fetchone():continue
       c.execute("insert into news values(?,?,?,?,?,?)",(ident,now(),source,title,sym,side))
      S["news_seen"]+=1;count+=1
      if sym in prices and side and sym not in S["positions"] and len(S["positions"])<5 and S["equity"]>10:
       price=prices[sym];notional=S["equity"]*MARGIN_FRACTION*LEV
       S["positions"][sym]={"entry":price,"side":side,"notional":notional,"opened":now(),"t":time.time(),"headline":title,"locked":False,"stop":None}
    with LOCK:S["sources"][source]={"ok":True,"last_check":now(),"new":count,"feed_items":len(items)}
   except Exception as e:
    with LOCK:
     S["errors"]+=1;S["last_error"]=source+": "+str(e)[:180]
     S["sources"][source]={"ok":False,"last_check":now(),"error":str(e)[:150]}
  time.sleep(60)
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path not in ("/","/health","/status","/trades","/news"):
   self.send_error(404);return
  with LOCK:
   if self.path=="/trades":
    with sqlite3.connect(DB) as c:
     c.row_factory=sqlite3.Row;data={"trades":[dict(x) for x in c.execute("select * from trades order by id desc limit 100")]}
   elif self.path=="/news":
    with sqlite3.connect(DB) as c:
     c.row_factory=sqlite3.Row;data={"news":[dict(x) for x in c.execute("select ts,source,title,symbol,signal from news order by ts desc limit 50")]}
   else:data={k:v for k,v in S.items() if k!="_prices"};data["uptime_seconds"]=int(time.time()-START);data["warning"]="Free Render may sleep; /tmp SQLite data is ephemeral; feeds are not direct X/Truth Social streams; news timestamps are collection time; this is a simulation, not validated execution."
  body=json.dumps(data,ensure_ascii=False).encode()
  self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
if __name__=="__main__":
 init()
 threading.Thread(target=market,daemon=True).start()
 threading.Thread(target=news,daemon=True).start()\n threading.Thread(target=xnews,daemon=True).start()\n threading.Thread(target=adapt,daemon=True).start()\n threading.Thread(target=truthnews,daemon=True).start()
 ThreadingHTTPServer(("0.0.0.0",int(os.getenv("PORT","10000"))),Handler).serve_forever()
