import os,json,time,threading,urllib.request,urllib.parse,sqlite3,datetime,xml.etree.ElementTree as ET,re,hashlib
import sqlite3,math
CANDIDATES=[(-0.06,0.12),(-0.08,0.16),(-0.10,0.20),(-0.12,0.24)]
def choose(db_path,current=(-0.10,0.20)):
 with sqlite3.connect(db_path) as c: rows=c.execute("select pnl from trades order by id desc limit 120").fetchall()
 xs=[float(x[0]) for x in reversed(rows)]
 if len(xs)<30:return {"stop":current[0],"take":current[1],"samples":len(xs),"changed":False}
 cut=max(20,int(len(xs)*0.7));train=xs[:cut];valid=xs[cut:]
 # conservative proxy: only permit a bounded change when validation PnL is positive
 if sum(valid)<=0:return {"stop":current[0],"take":current[1],"samples":len(xs),"validation_pnl":sum(valid),"changed":False}
 # no leverage/margin mutation: adaptation is deliberately bounded to exits
 avg=sum(train)/len(train); cand=CANDIDATES[3] if avg>0 else CANDIDATES[1]
 return {"stop":cand[0],"take":cand[1],"samples":len(xs),"validation_pnl":sum(valid),"changed":cand!=current}

WATCH=["elonmusk","realDonaldTrump","federalreserve","SECGov","USTreasury","WhiteHouse","coinbase","binance","saylor","cz_binance","VitalikButerin"]
def recent():
 token=os.getenv("X_BEARER_TOKEN","").strip()
 if not token:return []
 q="("+" OR ".join("from:"+x for x in WATCH)+") -is:retweet"
 url="https://api.x.com/2/tweets/search/recent?"+urllib.parse.urlencode({"query":q,"max_results":100,"tweet.fields":"created_at,author_id"})
 req=urllib.request.Request(url,headers={"Authorization":"Bearer "+token,"User-Agent":"PANDORA-paper/1"})
 with urllib.request.urlopen(req,timeout=15) as r:return json.load(r).get("data",[])

BASE="https://truthsocial.com/api/v1"
def _get(path):
 req=urllib.request.Request(BASE+path,headers={"User-Agent":"PANDORA-public-monitor/1.0","Accept":"application/json"})
 with urllib.request.urlopen(req,timeout=12) as r:return json.load(r)
def user_statuses(handle="realDonaldTrump",limit=20):
 q=urllib.parse.quote(handle)
 found=_get("/accounts/search?q="+q+"&limit=5")
 acct=next((x for x in found if str(x.get("acct","")).lower()==handle.lower()),found[0] if found else None)
 if not acct:return []
 rows=_get("/accounts/"+str(acct["id"])+"/statuses?limit="+str(limit)+"&exclude_replies=true")
 out=[]
 for x in rows:
  out.append({"id":x.get("id"),"created_at":x.get("created_at"),"content":x.get("content","")})
 return out

from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
API="https://api.hyperliquid-testnet.xyz/info"
DB="/tmp/pandora.sqlite3"
START=time.time()
S={"adaptive":{"samples":0,"changed":False},"mode":"PAPER_ONLY","orders_enabled":False,"last_poll":None,"market_count":0,"news_seen":0,"trades":0,"errors":0,"last_error":None,"sources":{},"positions":{},"equity":100.0,"realized_pnl":0.0}
LOCK=threading.RLock()
FEEDS={"FedOfficial":"https://www.federalreserve.gov/feeds/press_all.xml","SECOfficial":"https://www.sec.gov/news/pressreleases.rss","GoogleNewsCrypto":"https://news.google.com/rss/search?q=cryptocurrency+OR+bitcoin+OR+altcoin&hl=en-US&gl=US&ceid=US:en","GoogleNewsMarkets":"https://news.google.com/rss/search?q=crypto+SEC+OR+Federal+Reserve+OR+token+listing&hl=en-US&gl=US&ceid=US:en","Cointelegraph":"https://cointelegraph.com/rss","Decrypt":"https://decrypt.co/feed","CoinDesk":"https://www.coindesk.com/arc/outboundfeeds/rss/","CFTCOfficial":"https://www.cftc.gov/RSS/RSSGP/rssgp.xml","DOJNews":"https://www.justice.gov/feeds/opa/justice-news.xml","TruthSocialSearch":"https://news.google.com/rss/search?q=site%3Atruthsocial.com+crypto&hl=en-US&gl=US&ceid=US:en","XSearch":"https://news.google.com/rss/search?q=site%3Ax.com+cryptocurrency&hl=en-US&gl=US&ceid=US:en"}
POS=("surge","approve","approval","partnership","listing","adoption","buyback","breakout","bullish","launch","etf approved")
NEG=("hack","exploit","lawsuit","delist","ban","liquidation","fraud","selloff","bearish","crash","stolen")
STOP_ROE=-999.0;TAKE_ROE=0.20;LEV=10.0;MARGIN_FRACTION=0.25;FEE=0.00045;LOCK_TRIGGER_ROE=0.15;LOCK_ROE=0.075;PAPER_RESET=100.0
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
  c.execute("create table if not exists event_features (id text primary key,ts text,source text,title text,symbol text,decision integer,confidence real,features text)")
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
      if roe>=LOCK_TRIGGER_ROE and not pos["locked"]:
       pos["locked"]=True;pos["stop"]=pos["entry"]*(1+pos["side"]*LOCK_ROE/LEV)
      if S["equity"]+pos["notional"]*move<=0 or (pos["locked"] and (p-pos["stop"])*pos["side"]<=0) or time.time()-pos["t"]>3600:
       reason="liquidation" if S["equity"]+pos["notional"]*move<=0 else "locked" if pos["locked"] and (p-pos["stop"])*pos["side"]<=0 else "timeout"
       pnl=pos["notional"]*move-pos["notional"]*FEE*2
       S["equity"]+=pnl;S["realized_pnl"]+=pnl;S["trades"]+=1
       if S["equity"]<=0:S["equity"]=PAPER_RESET
       with sqlite3.connect(DB) as c:c.execute("insert into trades(opened,closed,symbol,side,entry,exit,pnl,reason,headline) values(?,?,?,?,?,?,?,?,?)",(pos["opened"],now(),sym,pos["side"],pos["entry"],p,pnl,reason,pos["headline"]))
       del S["positions"][sym]
    S["_prices"]=valid
    hist=S.setdefault("_hist",{})
    for hs,hp in valid.items():
     q=hist.setdefault(hs,[]);q.append(hp)
     if len(q)>120:del q[:-120]
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
def deep_context(sym,prices):
 out={"symbol":sym,"price":prices.get(sym),"open_interest":None,"funding":None,"orderbook_imbalance":None,"market_momentum":None,"liquidation_map":"unavailable","whale_onchain":"unavailable","tokenomics":"unlock" if False else "unknown"}
 try:
  raw=json.loads(get(API,{"type":"metaAndAssetCtxs"}));meta,ctxs=raw[0],raw[1]
  names=[x.get("name") for x in meta.get("universe",[])]
  if sym in names:
   z=ctxs[names.index(sym)];out["open_interest"]=float(z.get("openInterest",0) or 0);out["funding"]=float(z.get("funding",0) or 0)
 except Exception:pass
 try:
  book=json.loads(get(API,{"type":"l2Book","coin":sym}));levels=book.get("levels",[])
  if len(levels)>=2:
   b=sum(float(x.get("sz",0)) for x in levels[0][:10]);a=sum(float(x.get("sz",0)) for x in levels[1][:10]);out["orderbook_imbalance"]=(b-a)/(b+a) if b+a else 0
 except Exception:pass
 hist=S.get("_hist",{}).get(sym,[])
 if len(hist)>=3:out["market_momentum"]=hist[-1]/hist[max(0,len(hist)-3)]-1
 return out

def decide(title,sym,base_side,prices):
 f=deep_context(sym,prices);lo=title.lower();f["tokenomics"]="unlock_event" if any(x in lo for x in ("unlock","vesting","token release")) else "normal"
 score=float(base_side)*1.5
 m=f.get("market_momentum");obi=f.get("orderbook_imbalance");fund=f.get("funding")
 if m is not None:score+=max(-1,min(1,m*200))
 if obi is not None:score+=max(-1,min(1,obi*2))
 if fund is not None:score+=max(-0.5,min(0.5,-fund*1000))
 if f["tokenomics"]=="unlock_event":score*=0.6
 side=1 if score>=0.75 else -1 if score<=-0.75 else 0
 return side,min(1.0,abs(score)/3.0),f

def record_event(ident,source,title,sym,base_side,prices):
 if not sym or sym not in prices:return 0
 side,conf,features=decide(title,sym,base_side,prices)
 with sqlite3.connect(DB) as c:c.execute("insert or replace into event_features values(?,?,?,?,?,?,?,?)",(ident,now(),source,title,sym,side,conf,json.dumps(features)))
 if side:open_signal(sym,side,title,prices)
 return side

def open_signal(sym,side,title,prices):
 if sym in prices and side and sym not in S["positions"] and len(S["positions"])<5 and S["equity"]>10:
  price=prices[sym];notional=S["equity"]*MARGIN_FRACTION*LEV
  S["positions"][sym]={"entry":price,"side":side,"notional":notional,"opened":now(),"t":time.time(),"headline":title,"locked":False,"stop":None}

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
     S["news_seen"]+=1;record_event(ident,"XOfficial",title,sym,side,prices)
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
     S["news_seen"]+=1;record_event(ident,"TruthSocialPublic",title,sym,side,prices)
  except Exception as e:
   with LOCK:S["sources"]["TruthSocialPublic"]={"ok":False,"last_check":now(),"error":str(e)[:140]}
  time.sleep(20)
def adapt():
 global STOP_ROE,TAKE_ROE
 while True:
  try:
   z=choose(DB,(-0.10,TAKE_ROE))
   with LOCK:
    if z.get("changed"):TAKE_ROE=float(z["take"])
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
      record_event(ident,source,title,sym,side,prices)
    with LOCK:S["sources"][source]={"ok":True,"last_check":now(),"new":count,"feed_items":len(items)}
   except Exception as e:
    with LOCK:
     S["errors"]+=1;S["last_error"]=source+": "+str(e)[:180]
     S["sources"][source]={"ok":False,"last_check":now(),"error":str(e)[:150]}
  time.sleep(60)
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path not in ("/","/health","/status","/trades","/news","/features"):
   self.send_error(404);return
  with LOCK:
   if self.path=="/trades":
    with sqlite3.connect(DB) as c:
     c.row_factory=sqlite3.Row;data={"trades":[dict(x) for x in c.execute("select * from trades order by id desc limit 100")]}
   elif self.path=="/features":
    with sqlite3.connect(DB) as c:
     c.row_factory=sqlite3.Row;data={"features":[dict(x) for x in c.execute("select * from event_features order by ts desc limit 100")]}
   elif self.path=="/news":
    with sqlite3.connect(DB) as c:
     c.row_factory=sqlite3.Row;data={"news":[dict(x) for x in c.execute("select ts,source,title,symbol,signal from news order by ts desc limit 50")]}
   else:data={k:v for k,v in S.items() if k!="_prices"};data["uptime_seconds"]=int(time.time()-START);data["warning"]="Free Render may sleep; /tmp SQLite data is ephemeral; feeds are not direct X/Truth Social streams; news timestamps are collection time; this is a simulation, not validated execution."
  body=json.dumps(data,ensure_ascii=False).encode()
  self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
if __name__=="__main__":
 init()
 threading.Thread(target=market,daemon=True).start()
 threading.Thread(target=news,daemon=True).start()
 threading.Thread(target=xnews,daemon=True).start()
 threading.Thread(target=adapt,daemon=True).start()
 threading.Thread(target=truthnews,daemon=True).start()
 ThreadingHTTPServer(("0.0.0.0",int(os.getenv("PORT","10000"))),Handler).serve_forever()
