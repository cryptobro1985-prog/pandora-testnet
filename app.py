import os,json,time,threading,urllib.request,urllib.parse,sqlite3,datetime,xml.etree.ElementTree as ET,re,hashlib,subprocess
import sqlite3,math,email.utils,secrets,signal,copy
import psycopg
from psycopg.rows import dict_row
from risk import evaluate_exit, risk_state
from engine_store import EngineStore, LeaseLost
from entry_guards import freshness, publication_epoch
from social_scrapers import poll as social_poll, SourceUnavailable
from public_social import read as public_social_read
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

WATCH=["elonmusk","realDonaldTrump","federalreserve","SECGov","USTreasury","WhiteHouse","coinbase","binance","saylor","cz_binance","VitalikButerin","Reuters","AP","CoinDesk","Cointelegraph","BNODesk","DeItaone","KobeissiLetter","WuBlockchain","Lookonchain","PeckShieldAlert"]
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
    if title:out.append({"id":hashlib.sha256((h+title).encode()).hexdigest(),"text":title,"source":"XPublicIndex","url":link,"created_at":it.findtext("pubDate")})
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
SHUTDOWN=threading.Event()
NEWS_MAX_AGE_SECONDS=float(os.getenv("NEWS_MAX_AGE_SECONDS","120"))
NEWS_POLL_SECONDS=float(os.getenv("NEWS_POLL_SECONDS","10"))
if not math.isfinite(NEWS_MAX_AGE_SECONDS) or NEWS_MAX_AGE_SECONDS<=0:raise ValueError("invalid news freshness window")
if not math.isfinite(NEWS_POLL_SECONDS) or NEWS_POLL_SECONDS<1:raise ValueError("invalid news poll interval")
S.update({"engine_active":False,"engine_error":None,"last_checkpoint":None,"last_market_error":None})
FEEDS={"FedOfficial":"https://www.federalreserve.gov/feeds/press_all.xml","SECOfficial":"https://www.sec.gov/news/pressreleases.rss","GoogleNewsCrypto":"https://news.google.com/rss/search?q=cryptocurrency+OR+bitcoin+OR+altcoin&hl=en-US&gl=US&ceid=US:en","GoogleNewsMarkets":"https://news.google.com/rss/search?q=crypto+SEC+OR+Federal+Reserve+OR+token+listing&hl=en-US&gl=US&ceid=US:en","Cointelegraph":"https://cointelegraph.com/rss","Decrypt":"https://decrypt.co/feed","CoinDesk":"https://www.coindesk.com/arc/outboundfeeds/rss/","CFTCOfficial":"https://www.cftc.gov/RSS/RSSGP/rssgp.xml","DOJNews":"https://www.justice.gov/feeds/justice-news.xml?type=All&component%5B436%5D=436&organization=All","TruthSocialSearch":"https://news.google.com/rss/search?q=site%3Atruthsocial.com+crypto&hl=en-US&gl=US&ceid=US:en","CoinSharesResearch":"https://news.google.com/rss/search?q=site%3Acoinshares.com%2Finsights%2Fresearch-data+crypto&hl=en-US&gl=US&ceid=US:en","BitwiseResearch":"https://news.google.com/rss/search?q=site%3Abitwiseinvestments.com%2Fcrypto-market-insights+crypto&hl=en-US&gl=US&ceid=US:en","ARKResearch":"https://news.google.com/rss/search?q=site%3Aark-invest.com+bitcoin+OR+crypto&hl=en-US&gl=US&ceid=US:en","GrayscaleResearch":"https://news.google.com/rss/search?q=site%3Aresearch.grayscale.com+crypto&hl=en-US&gl=US&ceid=US:en"}
POS=("surge","surges","approve","approved","approval","partnership","listing","adoption","buyback","breakout","bullish","launch","etf approved","rally","rallies","rebound","rebounds","record high","inflows","net inflow","gains","jumps","soars","upside")
NEG=("hack","hacked","exploit","lawsuit","delist","delisted","ban","banned","liquidation","liquidations","fraud","selloff","sell-off","bearish","crash","crashes","stolen","outflows","net outflow","falls","drops","slips","plunges","tumbles","declines")
# Symbols that are also ordinary English words/acronyms. Never map them from a bare word.
# They require an explicit crypto form/name so headlines like "not", "people", "move", "etc" cannot create trades.
AMBIGUOUS_SYMBOLS={"NOT","PEOPLE","MOVE","ETC"}
EXPLICIT_TOKEN_PATTERNS={
 "NOT":(r"\$NOT\b",r"\bNOTUSDT\b",r"\bNOTCOIN\b",r"\bNOT TOKEN\b"),
 "PEOPLE":(r"\$PEOPLE\b",r"\bPEOPLEUSDT\b",r"\bCONSTITUTIONDAO\b",r"\bPEOPLE TOKEN\b"),
 "MOVE":(r"\$MOVE\b",r"\bMOVEUSDT\b",r"\bMOVEMENT(?: NETWORK)?\b",r"\bMOVE TOKEN\b"),
 "ETC":(r"\$ETC\b",r"\bETCUSDT\b",r"\bETHEREUM CLASSIC\b",r"\bETC TOKEN\b")
}
# Source priors are experimental metadata for the one-week PAPER_ONLY study.
# They are logged and gently affect confidence/eligibility, but can never reverse news direction.
SOURCE_WEIGHTS={
 "FedOfficial":1.00,"SECOfficial":1.00,"CFTCOfficial":1.00,"DOJNews":0.95,
 "TruthSocialPublic":0.95,"XOfficial":0.90,"TruthArchive":0.80,
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
 # Neon transaction pooling rejects statement_timeout in startup options.
 return psycopg.connect(os.environ["DATABASE_URL"],autocommit=True,row_factory=dict_row,connect_timeout=5)
STORE=EngineStore(pg,FEE,PAPER_RESET)
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
  S["news_seen"]=c.execute("select count(*) as n from news_events").fetchone()["n"]
  S["trades"]=c.execute("select count(*) as n from trade_history").fetchone()["n"]
 STORE.migrate()
 _,positions=STORE.load(recover_legacy=False)
 S["positions"]=positions
def journal(kind,event_id,payload):
 with pg() as c:c.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,%s,%s,%s::jsonb)",(now(),event_id,kind,json.dumps(payload,default=str)))
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
def engine_coordinator():
 # On the first rollout the previous release has no lease support. Its Render
 # drain lasts 60s; wait 120s after starting the web listener before taking over.
 while not SHUTDOWN.is_set():
  S["_coordinator_heartbeat"]=time.time()
  try:
   grace=120 if not STORE.has_lease_record() else 0
   break
  except Exception as e:
   S["engine_error"]=str(e)[:180];SHUTDOWN.wait(5)
 else:return
 deadline=time.monotonic()+grace
 while not SHUTDOWN.is_set() and time.monotonic()<deadline:
  S["_coordinator_heartbeat"]=time.time()
  SHUTDOWN.wait(min(5,max(0,deadline-time.monotonic())))
 while not SHUTDOWN.is_set():
  S["_coordinator_heartbeat"]=time.time()
  try:
   if STORE.claim():
    if not S["engine_active"]:
     account,positions=STORE.load()
     for sym,pos in positions.items():STORE.save(sym,pos)
     with LOCK:
      S["positions"]=positions;S["equity"]=float(account["equity"]);S["realized_pnl"]=float(account["realized_pnl"])
      S["last_checkpoint"]=now()
     journal("engine_restored",None,{"positions":list(positions),"risk_checkpoints":True})
    S["engine_active"]=True;S["engine_error"]=None
   else:
    S["engine_active"]=False;S["engine_error"]="standby: another engine owns the lease"
  except Exception as e:
   S["engine_active"]=False;S["engine_error"]=str(e)[:180]
  SHUTDOWN.wait(5)
 S["engine_active"]=False
 try:STORE.release()
 except Exception:pass

def market():
 while not SHUTDOWN.is_set():
  S["_market_heartbeat"]=time.time()
  try:
   mids=json.loads(get(API,{"type":"allMids"}))
   valid={k:float(v) for k,v in mids.items() if re.match(r"^[A-Z0-9]{2,15}$",k) and math.isfinite(float(v)) and float(v)>0}
   if not valid:raise ValueError("empty market response")
   with LOCK:
    S["last_poll"]=now();S["_last_poll_epoch"]=time.time();S["market_count"]=len(valid);S["_prices"]=valid
    if S["engine_active"] and not SHUTDOWN.is_set():
     for sym,px in valid.items():
      if sym not in S["positions"]:continue
      pos,reason=evaluate_exit(S["positions"][sym],px,now())
      move=(px/pos["entry"]-1)*pos["side"]
      if S["equity"]+pos["notional"]*move<=0:reason="liquidation"
      # Retain an unsaved new extreme in memory if the database is temporarily
      # unavailable. Never delete a position or change equity before commit.
      S["positions"][sym]=pos
      if reason:
       result=STORE.close(sym,pos,px,reason)
       if result:
        S["equity"]=float(result["equity"]);S["realized_pnl"]=float(result["realized_pnl"]);S["trades"]+=1
       S["positions"].pop(sym,None)
      elif not STORE.save(sym,pos):
       S["positions"].pop(sym,None)
     S["last_checkpoint"]=now()
    stamp=time.time()
    for sym,px in valid.items():
     track=S.setdefault("_timeline",{}).setdefault(sym,[]);track.append((stamp,px))
     if len(track)>600:del track[:-600]
     hist=S.setdefault("_hist",{}).setdefault(sym,[]);hist.append(px)
     if len(hist)>120:del hist[:-120]
    S["last_market_error"]=None
  except LeaseLost as e:
   S["engine_active"]=False;S["engine_error"]=str(e)
  except Exception as e:
   S["errors"]+=1;S["last_market_error"]=str(e)[:180];S["last_error"]="market: "+str(e)[:180]
  S["_market_heartbeat"]=time.time()
  SHUTDOWN.wait(2)

def telemetry():
 # External context calls are slow and optional. They must never hold LOCK or
 # stall the price/exit loop, even if a source hangs or returns an error.
 while not SHUTDOWN.is_set():
  try:
   with LOCK:
    active=S["engine_active"];prices=dict(S.get("_prices",{}));symbols=list(S["positions"])
    count=S["market_count"];equity=S["equity"]
   if active:
    save_market_snapshot(now(),count,equity,len(symbols))
    for sym in symbols:
     if SHUTDOWN.is_set():break
     if sym in prices:
      sampled_at=now()
      context=deep_context(sym,prices)
      with LOCK:S.setdefault("_context_cache",{})[sym]={"epoch":time.time(),"context":context}
      save_market_context(sampled_at,sym,prices[sym],context)
  except Exception as e:S["last_error"]="telemetry: "+str(e)[:160]
  SHUTDOWN.wait(30)
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
 # Entry decisions use news and already cached optional features. No network
 # calls or market-structure confirmation may delay a fresh event.
 with LOCK:
  cached=S.get("_context_cache",{}).get(sym,{})
  hist=list(S.get("_hist",{}).get(sym,[]))
 age=time.time()-cached.get("epoch",0)
 context=cached.get("context",{}) if age<=60 else {}
 f={k:context.get(k) for k in ("orderbook_imbalance","funding","open_interest","day_volume")}
 f["cached_context_age_seconds"]=age if cached else None
 f["market_momentum"]=(hist[-1]/hist[-3]-1) if len(hist)>=3 else None
 f["market_structure_filter_active"]=False
 lo=title.lower();f["tokenomics"]="unlock_event" if any(x in lo for x in ("unlock","vesting","token release")) else "normal"
 score=float(base_side)*1.5
 # Market observations remain in the research journal, but cannot veto or
 # reverse a directional news event. Fresh news may break an existing trend.
 f["market_features_advisory_only"]=True
 if f["tokenomics"]=="unlock_event":score*=0.6
 if base_side>0:
  side=1 if score>=0.75 else 0
 elif base_side<0:
  side=-1 if score<=-0.75 else 0
 else:
  side=0
 f["news_direction"]=base_side;f["direction_guard"]=True
 return side,min(1.0,abs(score)/3.0),f

def reaction_shadow(sym,side,published_at,price,limit_bps=150.0):
 t=publication_epoch(published_at)
 if not t or not side or price is None:return {"available":False,"reason":"missing_timestamp_direction_or_price"}
 candidates=[(ts,px) for ts,px in S.get("_timeline",{}).get(sym,[]) if ts<=t and t-ts<=600]
 if not candidates:return {"available":False,"reason":"no_pre_publication_price"}
 ts,anchor=max(candidates)
 move=side*(price/anchor-1)*10000
 return {"available":True,"anchor_price":anchor,"anchor_epoch":ts,"move_bps":move,"threshold_bps":limit_bps,"would_skip":move>limit_bps}
def record_event(ident,source,title,sym,base_side,prices,published_at=None):
 fresh=freshness(published_at,time.time(),NEWS_MAX_AGE_SECONDS)
 if not fresh["allowed"]:
  save_event_feature(ident,now(),source,title,sym,0,0.0,{"freshness":fresh,"market_structure_filter_active":False})
  journal("decision",ident,{"symbol":sym,"side":0,"reason":fresh["reason"],"freshness":fresh,"published_at":published_at})
  return 0
 event_type,event_side=classify_event(title,base_side)
 weight=source_weight(source)
 # Explicit event classification may supply direction when the simple keyword score missed it.
 # It may not reverse an already directional headline.
 effective_side=base_side if base_side else event_side
 if not sym or sym not in prices:
  journal("decision",ident,{"symbol":sym,"raw_side":base_side,"event_side":event_side,"event_type":event_type,"source_weight":weight,"side":0,"reason":"no_tradable_market"})
  return 0
 side,conf,features=decide(title,sym,effective_side,prices)
 features["event_type"]=event_type;features["source_weight"]=weight;features["freshness"]=fresh
 # PAPER experiment: source prior changes confidence, not direction. Very weak sources need a clearer decision.
 conf=min(1.0,conf*weight)
 if side and weight<0.50:side=0
 save_event_feature(ident,now(),source,title,sym,side,conf,features)
 shadow=reaction_shadow(sym,side,published_at,prices.get(sym))
 journal("decision",ident,{"symbol":sym,"raw_side":base_side,"event_side":event_side,"effective_side":effective_side,"event_type":event_type,"source_weight":weight,"side":side,"confidence":conf,"price":prices.get(sym),"features":features,"reaction_shadow":shadow,"reaction_filter_active":False,"reason":"direction_guard_or_low_source_weight" if not side else "eligible"})
 if side:open_signal(sym,side,title,prices,ident,published_at)
 return side

def open_signal(sym,side,title,prices,event_id=None,published_at=None):
 with LOCK:
  fresh=freshness(published_at,time.time(),NEWS_MAX_AGE_SECONDS)
  reason=None
  if not fresh["allowed"]:reason=fresh["reason"]
  elif not S["engine_active"] or SHUTDOWN.is_set():reason="engine_not_active"
  elif not S.get("last_checkpoint") or time.time()-datetime.datetime.fromisoformat(S["last_checkpoint"]).timestamp()>15:reason="risk_checkpoint_stale"
  elif time.time()-S.get("_last_poll_epoch",0)>10:reason="stale_market_price"
  elif sym not in S.get("_prices",{}) or not side:reason="no_price_or_direction"
  elif sym in S["positions"]:reason="position_already_open"
  elif S["equity"]<=10:reason="equity_limit"
  if reason:
   journal("entry_skipped",event_id,{"symbol":sym,"reason":reason,"freshness":fresh});return False
  price=S["_prices"][sym];margin=S["equity"]*MARGIN_FRACTION
  used_margin=sum(float(x.get("margin",x["notional"]/float(x.get("leverage",LEV)))) for x in S["positions"].values())
  free_margin=max(0.0,S["equity"]-used_margin)
  if free_margin+1e-9<margin:
   journal("entry_skipped",event_id,{"symbol":sym,"reason":"free_margin","free_margin":free_margin,"required_margin":margin});return False
  notional=margin*LEV
  pos={"entry":price,"side":side,"notional":notional,"opened":now(),"t":time.time(),"headline":title,
       "locked":False,"stop":None,"peak":price,"trail_armed":False,"trail_stop":None,"history":[],
       "leverage":LEV,"margin":margin,"event_id":event_id}
  if not STORE.save(sym,pos,create=True):return False
  S["positions"][sym]=pos
  return True

def ingest_event(ident,source,title,published_at=None,source_url=None):
 # No long-running source or analysis code owns the risk loop's lock.
 if not S["engine_active"] or SHUTDOWN.is_set():return False
 with LOCK:prices=dict(S.get("_prices",{}))
 sym,side=detect(title,prices)
 if not save_news_event(ident,now(),source,title,sym,side,published_at,source_url):return False
 with LOCK:S["news_seen"]+=1
 record_event(ident,source,title,sym,side,prices,published_at)
 return True

def xnews():
 while not SHUTDOWN.is_set():
  try:
   posts=recent()
   direct=bool(os.getenv("X_BEARER_TOKEN","").strip()) and not any(p.get("source")=="XPublicIndex" for p in posts)
   with LOCK:S["sources"]["XMonitor"]={"ok":True,"last_check":now(),"posts":len(posts),"mode":"official_api" if direct else "public_index_delayed","watch_accounts":len(WATCH)}
   for p in posts:
    if SHUTDOWN.is_set():break
    title=(p.get("text") or "").strip()
    if not title:continue
    source=p.get("source","XOfficial")
    ident=hashlib.sha256((source+str(p.get("id",title))).encode()).hexdigest()
    ingest_event(ident,source,title,p.get("created_at"),p.get("url"))
  except Exception as e:
   with LOCK:S["sources"]["XMonitor"]={"ok":False,"last_check":now(),"error":str(e)[:140]}
  SHUTDOWN.wait(10)

def truthnews():
 delay=10
 while not SHUTDOWN.is_set():
  try:
   posts=user_statuses("realDonaldTrump",30)
   with LOCK:S["sources"]["TruthSocialPublic"]={"ok":True,"last_check":now(),"posts":len(posts),"mode":"direct_public_api"};delay=10
   for p in reversed(posts):
    if SHUTDOWN.is_set():break
    title=re.sub("<[^>]+>"," ",p.get("content",""));title=re.sub(r"\s+"," ",title).strip()
    if not title:continue
    ident=hashlib.sha256(("TruthSocialPublic"+str(p.get("id",title))).encode()).hexdigest()
    ingest_event(ident,"TruthSocialPublic",title,p.get("created_at"),p.get("url"))
  except Exception as e:
   with LOCK:S["sources"]["TruthSocialPublic"]={"ok":False,"last_check":now(),"mode":"fallback_active","direct_ok":False,"direct_error":str(e)[:140],"fallback":"TruthSocialSearch"}
   delay=min(300,max(10,delay*2))
  SHUTDOWN.wait(delay)

def social_reader(kind):
 source="XScrape" if kind=="x" else "Truthbrush"
 canonical="XOfficial" if kind=="x" else "TruthSocialPublic"
 handles=WATCH if kind=="x" else ["realDonaldTrump"]
 interval=5 if kind=="x" else 10
 delay=interval
 while not SHUTDOWN.is_set():
  if not S["engine_active"]:
   SHUTDOWN.wait(2);continue
  started=time.time()
  try:
   posts=social_poll(kind,handles)
   published=[publication_epoch(p.get("created_at")) for p in posts]
   published=[p for p in published if p is not None]
   with LOCK:S["sources"][source]={"ok":True,"last_check":now(),"mode":"direct_scraper_polling",
    "posts":len(posts),"poll_seconds":interval,"request_seconds":round(time.time()-started,3),
    "latest_post_age_seconds":round(time.time()-max(published),1) if published else None}
   for p in reversed(posts):
    if SHUTDOWN.is_set():break
    title=p.get("text","").strip()
    if not title:continue
    ident=hashlib.sha256((canonical+str(p["id"])).encode()).hexdigest()
    ingest_event(ident,canonical,title,p.get("created_at"),p.get("url"))
   delay=interval
  except SourceUnavailable as exc:
   with LOCK:S["sources"][source]={"ok":False,"last_check":now(),"mode":"blocked",
    "error":str(exc),"fallback":"XMonitor" if kind=="x" else "TruthSocialSearch"}
   delay=60 if str(exc)=="needs_x_session" else min(300,max(interval,delay*2))
  except Exception:
   with LOCK:S["sources"][source]={"ok":False,"last_check":now(),"error":"reader_processing_failed"}
   delay=min(300,max(interval,delay*2))
  SHUTDOWN.wait(delay)


def public_social_reader(kind,handle):
 source="XPublic:"+handle if kind=="x" else "TruthArchive"
 canonical="XOfficial" if kind=="x" else "TruthArchive"
 interval=5 if kind=="x" else 30
 delay=interval
 while not SHUTDOWN.is_set():
  if not S["engine_active"]:
   SHUTDOWN.wait(2);continue
  started=time.time()
  try:
   posts=public_social_read(kind,handle)
   stamps=[publication_epoch(p.get("created_at")) for p in posts]
   stamps=[p for p in stamps if p is not None]
   with LOCK:S["sources"][source]={"ok":True,"last_check":now(),"mode":"public_page_polling" if kind=="x" else "archive_polling_delay_unknown",
    "posts":len(posts),"poll_seconds":interval,"request_seconds":round(time.time()-started,3),
    "latest_post_age_seconds":round(time.time()-max(stamps),1) if stamps else None,"realtime_verified":False}
   for p in posts:
    if SHUTDOWN.is_set():break
    ident=hashlib.sha256((canonical+str(p["id"])).encode()).hexdigest()
    ingest_event(ident,canonical,p["text"],p.get("created_at"),p.get("url"))
   delay=interval
  except Exception as exc:
   code=getattr(exc,"code",None)
   with LOCK:S["sources"][source]={"ok":False,"last_check":now(),"error":"http_"+str(code) if code else type(exc).__name__}
   delay=min(300,max(60 if code==429 else interval,delay*2))
  SHUTDOWN.wait(delay)


def truth_watch():
 # Candidate handles are probed individually; nonexistent profiles are never counted as live.
 # A 403/429 pauses the whole pass to avoid hammering a blocked service.
 handles=list(dict.fromkeys(WATCH+["FoxNews","FoxBusiness","Newsmax","OANN","DanScavino"]))
 while not SHUTDOWN.is_set():
  for handle in handles:
   if SHUTDOWN.is_set():return
   if not S["engine_active"]:
    SHUTDOWN.wait(3);continue
   source="TruthWatch:"+handle
   try:
    posts=social_poll("truth",[handle])
    with LOCK:S["sources"][source]={"ok":True,"last_check":now(),"posts":len(posts),"mode":"direct_truth_reader","realtime_verified":False}
    for p in posts:
     title=p.get("text","").strip()
     if not title:continue
     ident=hashlib.sha256(("TruthSocialPublic"+str(p["id"])).encode()).hexdigest()
     ingest_event(ident,"TruthSocialPublic",title,p.get("created_at"),p.get("url"))
   except SourceUnavailable as exc:
    error=str(exc)
    with LOCK:S["sources"][source]={"ok":False,"last_check":now(),"error":error,"mode":"unavailable"}
    if error in ("truth_http_403","truth_http_429"):
     SHUTDOWN.wait(300)
     break
   except Exception as exc:
    with LOCK:S["sources"][source]={"ok":False,"last_check":now(),"error":type(exc).__name__}
   SHUTDOWN.wait(1)
  SHUTDOWN.wait(20)

def adapt():
 global STOP_ROE,TAKE_ROE
 while not SHUTDOWN.is_set():
  try:
   z=choose_persistent((-0.10,TAKE_ROE))
   with LOCK:
    if z.get("changed"):TAKE_ROE=float(z["take"])
    S["adaptive"]=z
  except Exception as e:
   with LOCK:S["last_error"]="adaptive: "+str(e)[:160]
  SHUTDOWN.wait(900)

def news_feed(source,url):
 # Independent workers avoid head-of-line blocking by slow RSS publishers.
 # Search indexes are discovery fallbacks, not claimed realtime firehoses.
 parsed=urllib.parse.urlsplit(url)
 if parsed.hostname=="news.google.com":
  query=urllib.parse.parse_qs(parsed.query)
  query["q"]=[query.get("q",[""])[0]+" when:1h"]
  url=urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query,doseq=True)))
 delay=NEWS_POLL_SECONDS
 while not SHUTDOWN.is_set():
  try:
   root=ET.fromstring(get(url));items=root.findall(".//item")[:30];count=0
   for item in reversed(items):
    if SHUTDOWN.is_set():break
    title=(item.findtext("title") or "").strip()
    if not title:continue
    ident=hashlib.sha256((source+title).encode()).hexdigest()
    count+=bool(ingest_event(ident,source,title,item.findtext("pubDate"),item.findtext("link")))
   with LOCK:S["sources"][source]={"ok":True,"last_check":now(),"new":count,"feed_items":len(items),"poll_seconds":NEWS_POLL_SECONDS}
   delay=NEWS_POLL_SECONDS
  except Exception as e:
   with LOCK:
    S["errors"]+=1;S["last_error"]=source+": "+str(e)[:180]
    S["sources"][source]={"ok":False,"last_check":now(),"error":str(e)[:150]}
   delay=min(300,max(NEWS_POLL_SECONDS,delay*2))
  SHUTDOWN.wait(delay)
def dashboard():
 with LOCK:
  state={k:copy.deepcopy(v) for k,v in S.items() if not k.startswith("_")}
  state["_prices"]=dict(S.get("_prices",{}))
 trades=[dict(x) for x in persistent_trades(100)]
 newsrows=[dict(x) for x in persistent_news(20)]
 feats=[dict(x) for x in persistent_features(10)]
 prices=state.get("_prices",{});positions=[];unreal=0.0
 for sym,p in state["positions"].items():
  px=prices.get(sym,p["entry"]);move=(px/p["entry"]-1)*p["side"];gross=p["notional"]*move;fees=p["notional"]*FEE+p["notional"]*(px/p["entry"])*FEE;pnl=gross-fees;lev=float(p.get("leverage",LEV));margin=float(p.get("margin",p["notional"]/lev));roi=(pnl/margin*100) if margin>0 else 0.0;unreal+=pnl
  positions.append({"symbol":sym,"side":"LONG" if p["side"]>0 else "SHORT","entry":p["entry"],"mark":px,"notional_usd":round(p["notional"],2),"margin_usd":round(margin,2),"leverage":lev,"roe_pct":round(roi,3),"unrealized_pnl":round(pnl,4),"opened":p["opened"],"headline":p["headline"],"protection_stop":p.get("stop"),"trailing_stop":p.get("trail_stop"),"peak":p.get("peak"),"trailing_armed":p.get("trail_armed",False),"last_evaluated_at":p.get("last_evaluated_at")})
 starts=[x.get("opened") for x in trades if x.get("opened")]+[x.get("opened") for x in positions if x.get("opened")]
 account_started=min(starts) if starts else now()
 try: account_age_seconds=max(0,int((datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(account_started.replace("Z","+00:00"))).total_seconds()))
 except Exception: account_age_seconds=0
 total=state["equity"]+unreal;account_roi=(total/PAPER_RESET-1)*100
 return {"mode":state["mode"],"balance":round(state["equity"],4),"unrealized_pnl":round(unreal,4),"total_equity":round(total,4),"realized_pnl":round(state["realized_pnl"],4),"account_started":account_started,"account_age_seconds":account_age_seconds,"account_roi_pct":round(account_roi,3),"positions":positions,"trades":trades,"news":newsrows,"features":feats,"sources":state["sources"],"errors":state["errors"],"last_error":state["last_error"],"news_seen":state["news_seen"],"market_count":state["market_count"],"last_poll":state["last_poll"],"uptime_seconds":int(time.time()-START),"engine_active":state["engine_active"],"engine_error":state["engine_error"],"last_checkpoint":state["last_checkpoint"],"last_market_error":state["last_market_error"],"news_max_age_seconds":NEWS_MAX_AGE_SECONDS,"market_structure_filter_active":False,"version":os.getenv("RENDER_GIT_COMMIT","risk-state-v2")}

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
  if path in ("/health","/health/risk"):
   data=health_state()
   code=200 if (data["healthy"] if path=="/health" else data["risk_ready"]) else 503
   body=json.dumps(data).encode()
   self.send_response(code);self.send_header("Content-Type","application/json; charset=utf-8")
   self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(body)))
   self.end_headers();self.wfile.write(body);return
  if path not in ("/","/status","/api/dashboard","/trades","/news","/features"):
   self.send_error(404);return
  # Dashboard database reads are deliberately outside the engine lock.
  if path=="/":
   body=html_dashboard(dashboard()).encode();ctype="text/html; charset=utf-8"
  elif path in ("/status","/api/dashboard"):
   body=json.dumps(dashboard(),ensure_ascii=False).encode();ctype="application/json; charset=utf-8"
  elif path=="/trades":
   body=json.dumps({"trades":[dict(x) for x in persistent_trades(1000)]},ensure_ascii=False).encode();ctype="application/json; charset=utf-8"
  elif path=="/features":
   body=json.dumps({"features":[dict(x) for x in persistent_features(100)]},ensure_ascii=False).encode();ctype="application/json; charset=utf-8"
  else:
   body=json.dumps({"news":[dict(x) for x in persistent_news(50)]},ensure_ascii=False).encode();ctype="application/json; charset=utf-8"
  self.send_response(200);self.send_header("Content-Type",ctype);self.send_header("Cache-Control","no-store");self.send_header("Access-Control-Allow-Origin","*");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)

def health_state():
 stamp=time.time()
 age=stamp-S.get("_last_poll_epoch",0) if S.get("_last_poll_epoch") else None
 heartbeat=stamp-S.get("_market_heartbeat",stamp)
 checkpoint=S.get("last_checkpoint")
 checkpoint_age=stamp-datetime.datetime.fromisoformat(checkpoint).timestamp() if checkpoint else None
 coordinator_age=stamp-S.get("_coordinator_heartbeat",stamp)
 healthy=not SHUTDOWN.is_set() and heartbeat<45 and coordinator_age<45
 ready=healthy and S["engine_active"] and age is not None and age<10 and checkpoint_age is not None and checkpoint_age<15
 return {"healthy":healthy,"risk_ready":ready,"engine_active":S["engine_active"],
         "market_age_seconds":age,"checkpoint_age_seconds":checkpoint_age,
         "engine_error":S["engine_error"],"last_market_error":S["last_market_error"],
         "news_max_age_seconds":NEWS_MAX_AGE_SECONDS,"market_structure_filter_active":False,
         "mode":S["mode"],"version":os.getenv("RENDER_GIT_COMMIT","risk-state-v2")}

if __name__=="__main__":
 try:subprocess.Popen(["hyperdata","api","--port","8420"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 except Exception as e:S["sources"]["HyperData"]={"ok":False,"error":str(e)[:120]}
 init();pinit()
 S["sources"]["PersistentPostgres"]={"ok":True,"last_check":now(),"mode":"primary_state_and_trade_history"}
 server=ThreadingHTTPServer(("0.0.0.0",int(os.getenv("PORT","10000"))),Handler)
 def shutdown(signum,frame):
  SHUTDOWN.set()
  threading.Thread(target=server.shutdown,daemon=True).start()
 signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
 targets=[engine_coordinator,market,telemetry,xnews,adapt,truthnews,truth_watch]
 targets += [lambda:social_reader("x"),lambda:social_reader("truth")]
 workers=[threading.Thread(target=t,daemon=True,name=t.__name__) for t in targets]
 workers += [threading.Thread(target=news_feed,args=(name,url),daemon=True,name="feed:"+name) for name,url in FEEDS.items()]
 workers += [threading.Thread(target=public_social_reader,args=("x",handle),daemon=True,name="public-x:"+handle) for handle in WATCH]
 workers += [threading.Thread(target=public_social_reader,args=("truth","realDonaldTrump"),daemon=True,name="truth-archive")]
 for worker in workers:worker.start()
 try:server.serve_forever()
 finally:
  SHUTDOWN.set();server.server_close()
  for worker in workers:worker.join(timeout=0.5)
  try:STORE.release()
  except Exception:pass
