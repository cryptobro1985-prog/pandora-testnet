import os,json,time,threading,urllib.request,urllib.parse,sqlite3,datetime,xml.etree.ElementTree as ET,re,hashlib,subprocess
import sqlite3,math,email.utils,secrets
import psycopg
from psycopg.rows import dict_row
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
 if token:
  try:
   q="("+" OR ".join("from:"+x for x in WATCH)+") -is:retweet";url="https://api.x.com/2/tweets/search/recent?"+urllib.parse.urlencode({"query":q,"max_results":100,"tweet.fields":"created_at,author_id"})
   req=urllib.request.Request(url,headers={"Authorization":"Bearer "+token,"User-Agent":"PANDORA-paper/1"})
   with urllib.request.urlopen(req,timeout=15) as r:return json.load(r).get("data",[])
  except Exception:pass
 # credential-free public fallback: Google News indexes public x.com posts
 out=[]
 for h in WATCH:
  try:
   u="https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":"site:x.com/"+h,"hl":"en-US","gl":"US","ceid":"US:en"})
   root=ET.fromstring(get(u))
   for it in root.findall(".//item")[:8]:
    title=(it.findtext("title") or "").strip();link=(it.findtext("link") or "")
    if title:out.append({"id":hashlib.sha256((h+title).encode()).hexdigest(),"text":title,"source":"XPublicIndex","url":link})
  except Exception:pass
 return out[:100]

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
FEEDS={"FedOfficial":"https://www.federalreserve.gov/feeds/press_all.xml","SECOfficial":"https://www.sec.gov/news/pressreleases.rss","GoogleNewsCrypto":"https://news.google.com/rss/search?q=cryptocurrency+OR+bitcoin+OR+altcoin&hl=en-US&gl=US&ceid=US:en","GoogleNewsMarkets":"https://news.google.com/rss/search?q=crypto+SEC+OR+Federal+Reserve+OR+token+listing&hl=en-US&gl=US&ceid=US:en","Cointelegraph":"https://cointelegraph.com/rss","Decrypt":"https://decrypt.co/feed","CoinDesk":"https://www.coindesk.com/arc/outboundfeeds/rss/","CFTCOfficial":"https://www.cftc.gov/RSS/RSSGP/rssgp.xml","DOJNews":"https://www.justice.gov/feeds/justice-news.xml?type=All&component%5B436%5D=436&organization=All","TruthSocialSearch":"https://news.google.com/rss/search?q=site%3Atruthsocial.com+crypto&hl=en-US&gl=US&ceid=US:en","CoinSharesResearch":"https://news.google.com/rss/search?q=site%3Acoinshares.com%2Finsights%2Fresearch-data+crypto&hl=en-US&gl=US&ceid=US:en","BitwiseResearch":"https://news.google.com/rss/search?q=site%3Abitwiseinvestments.com%2Fcrypto-market-insights+crypto&hl=en-US&gl=US&ceid=US:en","ARKResearch":"https://news.google.com/rss/search?q=site%3Aark-invest.com+bitcoin+OR+crypto&hl=en-US&gl=US&ceid=US:en","GrayscaleResearch":"https://news.google.com/rss/search?q=site%3Aresearch.grayscale.com+crypto&hl=en-US&gl=US&ceid=US:en"}
POS=("surge","surges","approve","approved","approval","partnership","listing","adoption","buyback","breakout","bullish","launch","etf approved","rally","rallies","rebound","rebounds","record high","inflows","net inflow","gains","jumps","soars","upside")
NEG=("hack","hacked","exploit","lawsuit","delist","delisted","ban","banned","liquidation","liquidations","fraud","selloff","sell-off","bearish","crash","crashes","stolen","outflows","net outflow","falls","drops","slips","plunges","tumbles","declines")
# Symbols that are also ordinary English words/acronyms. Never map them from a bare word.
# They require an explicit crypto form/name so headlines like "not", "people", "move", "etc" cannot create trades.
AMBIGUOUS_SYMBOLS={"NOT","PEOPLE","MOVE","ETC"}
EXPLICIT_TOKEN_PATTERNS={
 "NOT":(r"\\$NOT\\b",r"\\bNOTUSDT\\b",r"\\bNOTCOIN\\b",r"\\bNOT TOKEN\\b"),
 "PEOPLE":(r"\\$PEOPLE\\b",r"\\bPEOPLEUSDT\\b",r"\\bCONSTITUTIONDAO\\b",r"\\bPEOPLE TOKEN\\b"),
 "MOVE":(r"\\$MOVE\\b",r"\\bMOVEUSDT\\b",r"\\bMOVEMENT(?: NETWORK)?\\b",r"\\bMOVE TOKEN\\b"),
 "ETC":(r"\\$ETC\\b",r"\\bETCUSDT\\b",r"\\bETHEREUM CLASSIC\\b",r"\\bETC TOKEN\\b")
}
# Source priors are experimental metadata for the one-week PAPER_ONLY study.
# They are logged and gently affect confidence/eligibility, but can never reverse news direction.
SOURCE_WEIGHTS={
 "FedOfficial":1.00,"SECOfficial":1.00,"CFTCOfficial":1.00,"DOJNews":0.95,
 "TruthSocialPublic":0.95,"XOfficial":0.90,
 "CoinSharesResearch":0.90,"BitwiseResearch":0.88,"ARKResearch":0.86,"GrayscaleResearch":0.88,
 "CoinDesk":0.84,"Decrypt":0.78,"Cointelegraph":0.74,
 "GoogleNewsMarkets":0.60,"GoogleNewsCrypto":0.55,"TruthSocialSearch":0.55
}
EVENT_RULES=[
 ("ETF_APPROVAL",1,("etf approved","approves spot","approval of spot","approved spot")),
 ("LISTING",1,("will list","listing of","lists ","listed on")),
 ("BUYBACK",1,("buyback","buy back","repurchase")),
 ("ADOPTION",1,("adoption","integrates","integration","partnership")),
 ("HACK",-1,("hack","hacked","exploit","stolen")),
 ("DELISTING",-1,("delist","delisted","delisting")),
 ("ENFORCEMENT",-1,("lawsuit","charges ","charged ","enforcement action")),
 ("SELL_OFF",-1,("selloff","sell-off","plunges","tumbles","crashes")),
 ("FUND_OUTFLOW",-1,("net outflow","outflows")),
 ("FUND_INFLOW",1,("net inflow","inflows"))
]
def classify_event(title,base_side):
 lo=title.lower()
 for event,side,terms in EVENT_RULES:
  if any(t in lo for t in terms):return event,side
 return ("DIRECTIONAL_NEWS" if base_side else "UNCLASSIFIED"),base_side
def source_weight(source):return float(SOURCE_WEIGHTS.get(source,0.50))
STOP_ROE=-999.0;TAKE_ROE=0.20;LEV=25.0;MARGIN_FRACTION=0.10;FEE=0.00045;LOCK_TRIGGER_ROE=0.10;LOCK_ROE=0.075;PAPER_RESET=100.0;MIN_EXIT_ROE=0.075;TRAIL_ARM_ROE=0.12
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def pg():
 return psycopg.connect(os.environ["DATABASE_URL"],autocommit=True,row_factory=dict_row)
def pinit():
 with pg() as c:
  c.execute("create table if not exists account_state (id integer primary key, equity double precision not null, realized_pnl double precision not null, updated_at text not null)")
  c.execute("create table if not exists open_positions (symbol text primary key, side integer not null, entry double precision not null, notional double precision not null, opened text not null, opened_epoch double precision not null, headline text, locked boolean not null default false, stop double precision)")
  c.execute("alter table open_positions add column if not exists leverage double precision")
  c.execute("alter table open_positions add column if not exists margin double precision")
  c.execute("create table if not exists trade_history (id bigserial primary key, opened text, closed text, symbol text, side integer, entry double precision, exit double precision, pnl double precision, reason text, headline text)")
  c.execute("create table if not exists news_events (id text primary key, ts text, source text, title text, symbol text, signal integer)")
  c.execute("create table if not exists event_features (id text primary key, ts text, source text, title text, symbol text, decision integer, confidence double precision, features jsonb)")
  c.execute("create table if not exists market_snapshots (ts text, markets integer, equity double precision, positions integer)")
  c.execute("create table if not exists market_context_snapshots (ts text, symbol text, price double precision, context jsonb)")
  c.execute("alter table news_events add column if not exists published_at text")
  c.execute("alter table news_events add column if not exists source_url text")
  c.execute("alter table open_positions add column if not exists event_id text")
  c.execute("alter table trade_history add column if not exists event_id text")
  c.execute("create table if not exists audit_journal (id bigserial primary key, recorded_at text not null, event_id text, kind text not null, payload jsonb not null)")
  c.execute("create index if not exists audit_journal_event_idx on audit_journal(event_id,id)")
  row=c.execute("select equity,realized_pnl from account_state where id=1").fetchone()
  if row:
   S["equity"]=float(row["equity"]);S["realized_pnl"]=float(row["realized_pnl"])
  else:c.execute("insert into account_state(id,equity,realized_pnl,updated_at) values(1,%s,%s,%s)",(S["equity"],S["realized_pnl"],now()))
  for r in c.execute("select * from open_positions").fetchall():
   S["positions"][r["symbol"]]={"entry":float(r["entry"]),"side":int(r["side"]),"notional":float(r["notional"]),"opened":r["opened"],"t":float(r["opened_epoch"]),"headline":r["headline"] or "","locked":bool(r["locked"]),"stop":r["stop"],"leverage":float(r["leverage"] or LEV),"margin":float(r["margin"] or (float(r["notional"])/float(r["leverage"] or LEV))),"event_id":r.get("event_id")}
def journal(kind,event_id,payload):
 with pg() as c:c.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,%s,%s,%s::jsonb)",(now(),event_id,kind,json.dumps(payload,default=str)))
def save_account():
 with pg() as c:c.execute("insert into account_state(id,equity,realized_pnl,updated_at) values(1,%s,%s,%s) on conflict(id) do update set equity=excluded.equity,realized_pnl=excluded.realized_pnl,updated_at=excluded.updated_at",(S["equity"],S["realized_pnl"],now()))
def save_pos(sym):
 p=S["positions"][sym];lev=float(p.get("leverage",LEV));margin=float(p.get("margin",p["notional"]/lev))
 with pg() as c:c.execute("insert into open_positions(symbol,side,entry,notional,opened,opened_epoch,headline,locked,stop,leverage,margin,event_id) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict(symbol) do update set side=excluded.side,entry=excluded.entry,notional=excluded.notional,opened=excluded.opened,opened_epoch=excluded.opened_epoch,headline=excluded.headline,locked=excluded.locked,stop=excluded.stop,leverage=excluded.leverage,margin=excluded.margin,event_id=excluded.event_id",(sym,p["side"],p["entry"],p["notional"],p["opened"],p["t"],p["headline"],p["locked"],p["stop"],lev,margin,p.get("event_id")))
def close_persistent(sym,pos,px,pnl,reason):
 with pg() as c:
  with c.transaction():
   c.execute("insert into trade_history(opened,closed,symbol,side,entry,exit,pnl,reason,headline,event_id) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",(pos["opened"],now(),sym,pos["side"],pos["entry"],px,pnl,reason,pos["headline"],pos.get("event_id")))
   c.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,%s,%s,%s::jsonb)",(now(),pos.get("event_id"),"trade_closed",json.dumps({"symbol":sym,"side":pos["side"],"entry":pos["entry"],"exit":px,"notional":pos["notional"],"pnl":pnl,"reason":reason,"opened":pos["opened"]})))
   c.execute("delete from open_positions where symbol=%s",(sym,))
   c.execute("insert into account_state(id,equity,realized_pnl,updated_at) values(1,%s,%s,%s) on conflict(id) do update set equity=excluded.equity,realized_pnl=excluded.realized_pnl,updated_at=excluded.updated_at",(S["equity"],S["realized_pnl"],now()))
def persistent_trades(limit=100):
 with pg() as c:return c.execute("select * from trade_history order by id desc limit %s",(limit,)).fetchall()
def choose_persistent(current=(-0.10,0.20)):
 rows=persistent_trades(120);xs=[float(x["pnl"]) for x in reversed(rows)]
 if len(xs)<30:return {"stop":current[0],"take":current[1],"samples":len(xs),"changed":False}
 cut=max(20,int(len(xs)*0.7));train=xs[:cut];valid=xs[cut:]
 if sum(valid)<=0:return {"stop":current[0],"take":current[1],"samples":len(xs),"validation_pnl":sum(valid),"changed":False}
 cand=CANDIDATES[3] if sum(train)/len(train)>0 else CANDIDATES[1]
 return {"stop":cand[0],"take":cand[1],"samples":len(xs),"validation_pnl":sum(valid),"changed":cand!=current}
def save_news_event(ident,ts,source,title,symbol,signal,published_at=None,source_url=None):
 with pg() as c:
  with c.transaction():
   if c.execute("select 1 from news_events where id=%s",(ident,)).fetchone():return False
   c.execute("insert into news_events(id,ts,source,title,symbol,signal,published_at,source_url) values(%s,%s,%s,%s,%s,%s,%s,%s)",(ident,ts,source,title,symbol,signal,published_at,source_url))
   c.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,%s,%s,%s::jsonb)",(now(),ident,"news_received",json.dumps({"source":source,"title":title,"symbol":symbol,"raw_signal":signal,"published_at":published_at,"received_at":ts,"source_url":source_url})))
   return True
def save_event_feature(ident,ts,source,title,symbol,decision,confidence,features):
 with pg() as c:c.execute("insert into event_features(id,ts,source,title,symbol,decision,confidence,features) values(%s,%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict(id) do update set ts=excluded.ts,decision=excluded.decision,confidence=excluded.confidence,features=excluded.features",(ident,ts,source,title,symbol,decision,confidence,json.dumps(features)))
def save_market_snapshot(ts,markets,equity,positions):
 with pg() as c:c.execute("insert into market_snapshots(ts,markets,equity,positions) values(%s,%s,%s,%s)",(ts,markets,equity,positions))
def save_market_context(ts,symbol,price,context):
 with pg() as c:c.execute("insert into market_context_snapshots(ts,symbol,price,context) values(%s,%s,%s,%s::jsonb)",(ts,symbol,price,json.dumps(context)))
def export_rows(kind,after,limit):
 columns={"journal":("audit_journal","id"),"news":("news_events","id"),
          "features":("event_features","id"),"trades":("trade_history","id"),
          "positions":("open_positions","symbol")}
 if kind not in columns:raise ValueError("Unsupported export kind")
 table,key=columns[kind]
 cursor=int(after) if kind in ("journal","trades") else after
 with pg() as c:
  rows=c.execute(f"select * from {table} where {key}>%s order by {key} limit %s",(cursor,limit+1)).fetchall()
 return {"kind":kind,"rows":rows[:limit],"next_after":str(rows[limit-1][key]) if len(rows)>limit else None,"has_more":len(rows)>limit}
def persistent_news(limit=50):
 with pg() as c:return c.execute("select ts,source,title,symbol,signal from news_events order by ts desc limit %s",(limit,)).fetchall()
def persistent_features(limit=100):
 with pg() as c:return c.execute("select ts,source,title,symbol,decision,confidence,features from event_features order by ts desc limit %s",(limit,)).fetchall()
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
      pos=S["positions"][sym];lev=float(pos.get("leverage",LEV));move=(p/pos["entry"]-1)*pos["side"];roe=move*lev
      if roe>=LOCK_TRIGGER_ROE and not pos["locked"]:
       pos["locked"]=True;pos["stop"]=pos["entry"]*(1+pos["side"]*LOCK_ROE/lev);save_pos(sym)
      hist0=S.get("_hist",{}).get(sym,[]);pos["peak"]=max(pos.get("peak",p),p) if pos["side"]>0 else min(pos.get("peak",p),p);peakmove=(pos["peak"]/pos["entry"]-1)*pos["side"];peakroe=peakmove*lev;weak=(len(hist0)>=6 and ((pos["side"]>0 and p<max(hist0[-6:]) and hist0[-1]<hist0[-3]) or (pos["side"]<0 and p>min(hist0[-6:]) and hist0[-1]>hist0[-3])));giveback=max(0.0,peakroe-roe);rets=[abs(hist0[i]/hist0[i-1]-1)*lev for i in range(max(1,len(hist0)-20),len(hist0)) if hist0[i-1]>0];noise=(sum(rets)/len(rets)) if rets else 0.01;trail_gap=max(0.025,min(0.08,noise*3.0));profit_floor=max(MIN_EXIT_ROE,peakroe-trail_gap);trail_armed=peakroe>=TRAIL_ARM_ROE;adaptive_exit=trail_armed and roe<=profit_floor and weak
      if S["equity"]+pos["notional"]*move<=0 or adaptive_exit:
       reason="liquidation" if S["equity"]+pos["notional"]*move<=0 else "local_extreme_weakening"
       pnl=pos["notional"]*move-pos["notional"]*FEE*2
       S["equity"]+=pnl;S["realized_pnl"]+=pnl;S["trades"]+=1
       if S["equity"]<=0:S["equity"]=PAPER_RESET
       close_persistent(sym,pos,p,pnl,reason)
       del S["positions"][sym]
    S["_prices"]=valid
    timeline=S.setdefault("_timeline",{})
    stamp=time.time()
    for tsym,tprice in valid.items():
     track=timeline.setdefault(tsym,[]);track.append((stamp,tprice))
     if len(track)>600:del track[:-600]
    hist=S.setdefault("_hist",{})
    for hs,hp in valid.items():
     q=hist.setdefault(hs,[]);q.append(hp)
     if len(q)>120:del q[:-120]
    save_market_snapshot(now(),len(valid),S["equity"],len(S["positions"]))
    for csym in list(S["positions"].keys()):
     if csym in valid:save_market_context(now(),csym,valid[csym],deep_context(csym,valid))
  except Exception as e:
   with LOCK:S["errors"]+=1;S["last_error"]="market: "+str(e)[:180]
  time.sleep(2)
def detect(title,prices):
 upper=title.upper();lo=title.lower()
 mentions=[]
 for k in prices:
  if len(k)<3:continue
  if k in AMBIGUOUS_SYMBOLS:
   if any(re.search(p,upper) for p in EXPLICIT_TOKEN_PATTERNS.get(k,())):mentions.append(k)
  elif re.search(r"(?<![A-Z0-9])"+re.escape(k)+r"(?![A-Z0-9])",upper):
   mentions.append(k)
 # Macro/regulatory crypto headlines default only to BTC/ETH; never to an accidental word-like ticker.
 if not mentions:
  if any(w in lo for w in ("federal reserve","interest rates","inflation","bitcoin","crypto market","cryptocurrency market","sec")):mentions=["BTC","ETH"]
  else:return None,0
 score=sum(w in lo for w in POS)-sum(w in lo for w in NEG)
 return (mentions[0] if mentions else None),(1 if score>0 else -1 if score<0 else 0)
def hyperdata(path):
 try:return json.loads(get("http://127.0.0.1:8420"+path))
 except Exception:return None

def deep_context(sym,prices):
 out={"symbol":sym,"price":prices.get(sym),"open_interest":None,"oi_delta":None,"funding":None,"premium":None,"day_volume":None,"orderbook_imbalance":None,"spread_bps":None,"market_momentum":None,"market_regime":None,"breadth":None,"liquidation_map":"unavailable","whale_onchain":"unavailable","tokenomics":"unlock" if False else "unknown"}
 try:
  raw=json.loads(get(API,{"type":"metaAndAssetCtxs"}));meta,ctxs=raw[0],raw[1]
  names=[x.get("name") for x in meta.get("universe",[])]
  if sym in names:
   z=ctxs[names.index(sym)];out["open_interest"]=float(z.get("openInterest",0) or 0);out["funding"]=float(z.get("funding",0) or 0);out["premium"]=float(z.get("premium",0) or 0);out["day_volume"]=float(z.get("dayNtlVlm",0) or 0)
 except Exception:pass
 try:
  book=json.loads(get(API,{"type":"l2Book","coin":sym}));levels=book.get("levels",[])
  if len(levels)>=2:
   b=sum(float(x.get("sz",0)) for x in levels[0][:10]);a=sum(float(x.get("sz",0)) for x in levels[1][:10]);out["orderbook_imbalance"]=(b-a)/(b+a) if b+a else 0
 except Exception:pass
 hist=S.get("_hist",{}).get(sym,[])
 if len(hist)>=3:out["market_momentum"]=hist[-1]/hist[max(0,len(hist)-3)]-1
 try:
  of=hyperdata("/v1/orderflow/"+urllib.parse.quote(sym));fr=hyperdata("/v1/funding-rates/"+urllib.parse.quote(sym));ob=hyperdata("/v1/orderbook/"+urllib.parse.quote(sym));ls=hyperdata("/v1/long-short-ratio");liq=hyperdata("/v1/liquidations/stats?include_estimated=false");wh=hyperdata("/v1/whales");dz=hyperdata("/v1/positions/danger-zone")
  out["cross_exchange_orderflow"]=of;out["cross_exchange_funding"]=fr;out["cross_exchange_orderbook"]=ob;out["long_short_ratio"]=ls;out["confirmed_liquidations"]=liq;out["whale_positions"]=wh;out["liquidation_danger_zone"]=dz
 except Exception:pass
 return out

def decide(title,sym,base_side,prices):
 f=deep_context(sym,prices);lo=title.lower();f["tokenomics"]="unlock_event" if any(x in lo for x in ("unlock","vesting","token release")) else "normal"
 score=float(base_side)*1.5
 m=f.get("market_momentum");obi=f.get("orderbook_imbalance");fund=f.get("funding")
 if m is not None:score+=max(-1,min(1,m*200))
 if obi is not None:score+=max(-1,min(1,obi*2))
 if fund is not None:score+=max(-0.5,min(0.5,-fund*1000))
 if f["tokenomics"]=="unlock_event":score*=0.6
 if base_side>0:
  side=1 if score>=0.75 else 0
 elif base_side<0:
  side=-1 if score<=-0.75 else 0
 else:
  side=0
 f["news_direction"]=base_side;f["direction_guard"]=True
 return side,min(1.0,abs(score)/3.0),f

def publication_epoch(value):
 if not value:return None
 try:
  dt=datetime.datetime.fromisoformat(value.replace("Z","+00:00")) if "T" in value else email.utils.parsedate_to_datetime(value)
  return dt.timestamp() if dt.tzinfo else None
 except (ValueError,TypeError,OverflowError):return None
def reaction_shadow(sym,side,published_at,price,limit_bps=150.0):
 t=publication_epoch(published_at)
 if not t or not side or price is None:return {"available":False,"reason":"missing_timestamp_direction_or_price"}
 candidates=[(ts,px) for ts,px in S.get("_timeline",{}).get(sym,[]) if ts<=t and t-ts<=600]
 if not candidates:return {"available":False,"reason":"no_pre_publication_price"}
 ts,anchor=max(candidates)
 move=side*(price/anchor-1)*10000
 return {"available":True,"anchor_price":anchor,"anchor_epoch":ts,"move_bps":move,"threshold_bps":limit_bps,"would_skip":move>limit_bps}
def record_event(ident,source,title,sym,base_side,prices,published_at=None):
 event_type,event_side=classify_event(title,base_side)
 weight=source_weight(source)
 # Explicit event classification may supply direction when the simple keyword score missed it.
 # It may not reverse an already directional headline.
 effective_side=base_side if base_side else event_side
 if not sym or sym not in prices:
  journal("decision",ident,{"symbol":sym,"raw_side":base_side,"event_side":event_side,"event_type":event_type,"source_weight":weight,"side":0,"reason":"no_tradable_market"})
  return 0
 side,conf,features=decide(title,sym,effective_side,prices)
 features["event_type"]=event_type;features["source_weight"]=weight
 # PAPER experiment: source prior changes confidence, not direction. Very weak sources need a clearer decision.
 conf=min(1.0,conf*weight)
 if side and weight<0.50:side=0
 save_event_feature(ident,now(),source,title,sym,side,conf,features)
 shadow=reaction_shadow(sym,side,published_at,prices.get(sym))
 journal("decision",ident,{"symbol":sym,"raw_side":base_side,"event_side":event_side,"effective_side":effective_side,"event_type":event_type,"source_weight":weight,"side":side,"confidence":conf,"price":prices.get(sym),"features":features,"reaction_shadow":shadow,"reaction_filter_active":False,"reason":"direction_guard_or_low_source_weight" if not side else "eligible"})
 if side:open_signal(sym,side,title,prices,ident)
 return side

def open_signal(sym,side,title,prices,event_id=None):
 if sym not in prices or not side:
  journal("entry_skipped",event_id,{"symbol":sym,"reason":"no_price_or_direction"});return
 if sym in S["positions"]:
  journal("entry_skipped",event_id,{"symbol":sym,"reason":"position_already_open"});return
 if S["equity"]<=10:
  journal("entry_skipped",event_id,{"symbol":sym,"reason":"equity_limit"});return
 price=prices[sym];margin=S["equity"]*MARGIN_FRACTION;used_margin=sum(float(x.get("margin",x["notional"]/float(x.get("leverage",LEV)))) for x in S["positions"].values());free_margin=max(0.0,S["equity"]-used_margin)
 if free_margin+1e-9<margin:
  journal("entry_skipped",event_id,{"symbol":sym,"reason":"free_margin","free_margin":free_margin,"required_margin":margin});return
 notional=margin*LEV
 S["positions"][sym]={"entry":price,"side":side,"notional":notional,"opened":now(),"t":time.time(),"headline":title,"locked":False,"stop":None,"peak":price,"leverage":LEV,"margin":margin,"event_id":event_id}
 save_pos(sym)
 journal("trade_opened",event_id,{"symbol":sym,"side":side,"entry":price,"notional":notional,"margin":margin,"leverage":LEV,"headline":title})

def xnews():
 while True:
  try:
   posts=recent()
   with LOCK:S["sources"]["XMonitor"]={"ok":True,"last_check":now(),"posts":len(posts),"mode":"official_api" if os.getenv("X_BEARER_TOKEN","").strip() else "multi_source_public_fallback","watch_accounts":len(WATCH)}
   for p in posts:
    title=(p.get("text") or "").strip()
    if not title:continue
    ident=hashlib.sha256(("XOfficial"+str(p.get("id",title))).encode()).hexdigest()
    with LOCK:
     prices=S.get("_prices",{});sym,side=detect(title,prices)
     if not save_news_event(ident,now(),"XOfficial",title,sym,side,p.get("created_at"),p.get("url")):continue
     S["news_seen"]+=1;record_event(ident,"XOfficial",title,sym,side,prices,p.get("created_at"))
  except Exception as e:
   with LOCK:S["sources"]["XMonitor"]={"ok":False,"last_check":now(),"error":str(e)[:140]}
  time.sleep(10)
def truthnews():
 delay=10
 while True:
  try:
   posts=user_statuses("realDonaldTrump",30)
   with LOCK:S["sources"]["TruthSocialPublic"]={"ok":True,"last_check":now(),"posts":len(posts),"mode":"direct_public_api"};delay=10
   for p in reversed(posts):
    title=re.sub("<[^>]+>"," ",p.get("content",""));title=re.sub(r"\\s+"," ",title).strip()
    if not title:continue
    ident=hashlib.sha256(("TruthSocialPublic"+str(p.get("id",title))).encode()).hexdigest()
    with LOCK:
     prices=S.get("_prices",{});sym,side=detect(title,prices)
     if not save_news_event(ident,now(),"TruthSocialPublic",title,sym,side,p.get("created_at"),p.get("url")):continue
     S["news_seen"]+=1;record_event(ident,"TruthSocialPublic",title,sym,side,prices,p.get("created_at"))
  except Exception as e:
   with LOCK:S["sources"]["TruthSocialPublic"]={"ok":True,"last_check":now(),"mode":"fallback_active","direct_ok":False,"direct_error":str(e)[:140],"fallback":"TruthSocialSearch"};delay=min(300,max(10,delay*2))
  time.sleep(delay)
def adapt():
 global STOP_ROE,TAKE_ROE
 while True:
  try:
   z=choose_persistent((-0.10,TAKE_ROE))
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
      if not save_news_event(ident,now(),source,title,sym,side,item.findtext("pubDate"),item.findtext("link")):continue
      S["news_seen"]+=1;count+=1
      record_event(ident,source,title,sym,side,prices,item.findtext("pubDate"))
    with LOCK:S["sources"][source]={"ok":True,"last_check":now(),"new":count,"feed_items":len(items)}
   except Exception as e:
    with LOCK:
     S["errors"]+=1;S["last_error"]=source+": "+str(e)[:180]
     S["sources"][source]={"ok":False,"last_check":now(),"error":str(e)[:150]}
  time.sleep(60)
def dashboard():
 trades=[dict(x) for x in persistent_trades(100)]
 newsrows=[dict(x) for x in persistent_news(20)]
 feats=[dict(x) for x in persistent_features(10)]
 prices=S.get("_prices",{});positions=[];unreal=0.0
 for sym,p in S["positions"].items():
  px=prices.get(sym,p["entry"]);move=(px/p["entry"]-1)*p["side"];gross=p["notional"]*move;fees=p["notional"]*FEE+p["notional"]*(px/p["entry"])*FEE;pnl=gross-fees;lev=float(p.get("leverage",LEV));margin=float(p.get("margin",p["notional"]/lev));roi=(pnl/margin*100) if margin>0 else 0.0;unreal+=pnl
  positions.append({"symbol":sym,"side":"LONG" if p["side"]>0 else "SHORT","entry":p["entry"],"mark":px,"notional_usd":round(p["notional"],2),"margin_usd":round(margin,2),"leverage":lev,"roe_pct":round(roi,3),"unrealized_pnl":round(pnl,4),"opened":p["opened"],"headline":p["headline"]})
 starts=[x.get("opened") for x in trades if x.get("opened")]+[x.get("opened") for x in positions if x.get("opened")]
 account_started=min(starts) if starts else now()
 try: account_age_seconds=max(0,int((datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(account_started.replace("Z","+00:00"))).total_seconds()))
 except Exception: account_age_seconds=0
 total=S["equity"]+unreal;account_roi=(total/PAPER_RESET-1)*100
 return {"mode":S["mode"],"balance":round(S["equity"],4),"unrealized_pnl":round(unreal,4),"total_equity":round(total,4),"realized_pnl":round(S["realized_pnl"],4),"account_started":account_started,"account_age_seconds":account_age_seconds,"account_roi_pct":round(account_roi,3),"positions":positions,"trades":trades,"news":newsrows,"features":feats,"sources":S["sources"],"errors":S["errors"],"last_error":S["last_error"],"news_seen":S["news_seen"],"market_count":S["market_count"],"last_poll":S["last_poll"],"uptime_seconds":int(time.time()-START)}

def html_dashboard(data):
 esc=lambda x:str(x).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
 age=data.get("account_age_seconds",0);age_txt="%dd %02dh %02dm"%(age//86400,(age%86400)//3600,(age%3600)//60)
 cards='<div class="grid"><b>MODE<br>%s</b><b>BALANCE<br>$ %s</b><b>P&L IF CLOSED NOW<br>$ %s</b><b>ACCOUNT IF CLOSED NOW<br>$ %s</b><b>ACCOUNT ROI<br>%s%%</b><b>ACCOUNT AGE<br>%s</b><b>POSITIONS<br>%s</b></div>'%(esc(data["mode"]),data["balance"],data["unrealized_pnl"],data["total_equity"],data["account_roi_pct"],age_txt,len(data["positions"]))
 pos="".join('<tr><td>%s</td><td>%s</td><td>$%s</td><td>$%s</td><td>%sx</td><td>%s</td><td>%s</td><td class="%s">%s%%</td><td class="%s">$%s</td><td>%s</td></tr>'%(esc(x["symbol"]),x["side"],x.get("margin_usd",0),x.get("notional_usd",0),x.get("leverage",LEV),x["entry"],x["mark"],"posv" if x.get("roe_pct",0)>=0 else "negv",x.get("roe_pct",0),"posv" if x["unrealized_pnl"]>=0 else "negv",x["unrealized_pnl"],esc(x["headline"])) for x in data["positions"]) or '<tr><td colspan=10>No open positions</td></tr>'
 trs="".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(esc(x["closed"]),esc(x["symbol"]),"LONG" if x["side"]>0 else "SHORT",round(x["pnl"],4),esc(x["reason"])) for x in data["trades"]) or '<tr><td colspan=5>No closed trades</td></tr>'
 src="".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(esc(k),"OK" if v.get("ok") else "ERROR",esc(v.get("last_check","")),esc(v.get("error",""))) for k,v in data["sources"].items())
 news="".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(esc(x["ts"]),esc(x["source"]),esc(x["symbol"]),esc(x["signal"]),esc(x["title"])) for x in data["news"][:12])
 return '''<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="2"><meta name="viewport" content="width=device-width"><title>PANDORA LIVE</title><style>body{font-family:system-ui;background:#080b10;color:#e8edf5;margin:24px}h1{margin:0}.muted{color:#8b98aa}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:18px 0}.grid b{background:#111722;padding:16px;border-radius:12px}table{width:100%%;border-collapse:collapse;background:#0e141e;margin-bottom:22px}td,th{padding:9px;border-bottom:1px solid #202938;text-align:left;font-size:13px}th{color:#91a2b8}.posv{color:#49d17d;font-weight:700}.negv{color:#ff6262;font-weight:700}a{color:#8bc4ff}</style></head><body><h1>PANDORA LIVE</h1><div class="muted">Paper engine · live refresh 2s · last market poll %s</div>%s<h2>Open positions</h2><table><tr><th>Token</th><th>Side</th><th>Margin</th><th>Position</th><th>Lev</th><th>Entry</th><th>Mark</th><th>ROI%%</th><th>P&L</th><th>Trigger</th></tr>%s</table><h2>Closed trades</h2><table><tr><th>Closed</th><th>Token</th><th>Side</th><th>PnL</th><th>Reason</th></tr>%s</table><h2>Sources</h2><table><tr><th>Source</th><th>Status</th><th>Checked</th><th>Error</th></tr>%s</table><h2>Latest news</h2><table><tr><th>Time</th><th>Source</th><th>Token</th><th>Raw signal</th><th>Headline</th></tr>%s</table><p>Errors: %s · Last error: %s</p><p><a href="/api/dashboard">JSON dashboard</a> · <a href="/features">Features</a> · <a href="/trades">Trades</a> · <a href="/news">News</a></p></body></html>'''%(esc(data["last_poll"]),cards,pos,trs,src,news,data["errors"],esc(data["last_error"]))


class Handler(BaseHTTPRequestHandler):
 def do_HEAD(self):
  self.send_response(200);self.end_headers()
 def do_GET(self):
  path=self.path.split("?")[0]
  if path=="/api/journal/export":
   token=os.getenv("JOURNAL_EXPORT_TOKEN","")
   auth=self.headers.get("Authorization","")
   if not token or not secrets.compare_digest(auth,"Bearer "+token):
    self.send_error(401);return
   try:
    args=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    kind=args.get("kind",["journal"])[0]
    after=args.get("after",["0" if kind in ("journal","trades") else ""])[0]
    limit=min(500,max(1,int(args.get("limit",["200"])[0])))
    body=json.dumps(export_rows(kind,after,limit),ensure_ascii=False,default=str).encode()
   except (ValueError,OverflowError):
    self.send_error(400);return
   except Exception:
    self.send_error(500);return
   self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8")
   self.send_header("Cache-Control","no-store");self.send_header("X-Content-Type-Options","nosniff")
   self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body);return
  if path not in ("/","/health","/status","/api/dashboard","/trades","/news","/features"):
   self.send_error(404);return
  with LOCK:
   if path=="/":
    body=html_dashboard(dashboard()).encode();ctype="text/html; charset=utf-8"
   elif path in ("/health","/status","/api/dashboard"):
    body=json.dumps(dashboard(),ensure_ascii=False).encode();ctype="application/json; charset=utf-8"
   elif path=="/trades":
    data={"trades":[dict(x) for x in persistent_trades(1000)]}
    body=json.dumps(data,ensure_ascii=False).encode();ctype="application/json; charset=utf-8"
   elif path=="/features":
    data={"features":[dict(x) for x in persistent_features(100)]}
    body=json.dumps(data,ensure_ascii=False).encode();ctype="application/json; charset=utf-8"
   else:
    data={"news":[dict(x) for x in persistent_news(50)]}
    body=json.dumps(data,ensure_ascii=False).encode();ctype="application/json; charset=utf-8"
  self.send_response(200);self.send_header("Content-Type",ctype);self.send_header("Cache-Control","no-store");self.send_header("Access-Control-Allow-Origin","*");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
if __name__=="__main__":
 try:subprocess.Popen(["hyperdata","api","--port","8420"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 except Exception as e:S["sources"]["HyperData"]={"ok":False,"error":str(e)[:120]}
 init()
 pinit()
 S["sources"]["PersistentPostgres"]={"ok":True,"last_check":now(),"mode":"primary_state_and_trade_history"}
 threading.Thread(target=market,daemon=True).start()
 threading.Thread(target=news,daemon=True).start()
 threading.Thread(target=xnews,daemon=True).start()
 threading.Thread(target=adapt,daemon=True).start()
 threading.Thread(target=truthnews,daemon=True).start()
 ThreadingHTTPServer(("0.0.0.0",int(os.getenv("PORT","10000"))),Handler).serve_forever()
