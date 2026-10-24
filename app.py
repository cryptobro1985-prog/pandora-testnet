import os,json,time,threading,urllib.request,urllib.parse,sqlite3,datetime,xml.etree.ElementTree as ET,re,hashlib,subprocess
import sqlite3,math,email.utils,secrets,signal,copy,concurrent.futures
import websocket
import psycopg
from psycopg.rows import dict_row
from risk import evaluate_exit, risk_state
from engine_store import EngineStore, LeaseLost
from entry_guards import freshness, publication_epoch
from social_scrapers import poll as social_poll, SourceUnavailable
from truthbrush import Api as TruthApi
from public_social import read as public_social_read
from x_guest import read as guest_x_read
from x_list import fetch_list as x_list_fetch
from realtime_free import fetch_x as free_x_fetch, fetch_x_lookup as free_x_lookup_fetch, fetch_x_syndication as free_x_syndication_fetch, fetch_x_syndication as free_x_syn_fetch, fetch_x_vx as free_x_vx_fetch, fetch_truth as free_truth_fetch, fetch_truth_activitypub as free_truth_ap_fetch
from momentum_scanner import candidates as momentum_candidates
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

WATCH_GROUPS={
 "core":["elonmusk","realDonaldTrump","POTUS","WhiteHouse","JDVance","PressSec","Scavino47","federalreserve","SECGov","USTreasury","CFTC","DHSgov","SecScottBessent","Reuters","ReutersBiz","AP","APBusiness","BBCWorld","business","BNODesk","DeItaone","KobeissiLetter","financialjuice","LiveSquawk","CoinDesk","Cointelegraph","DecryptMedia","TheBlockCo","blockworks_","BitcoinMagazine","WuBlockchain","Lookonchain","PeckShieldAlert","CertiKAlert","whale_alert","arkham","DefiLlama","CoinGlass","coinbase","binance","Bybit_Official","hyperliquidX","saylor","cz_binance","VitalikButerin"],
 "news":["CNBC","zerohedge","unusual_whales","FirstSquawk","TreeNewsFeed","tier10k","WSJ","FT","ForbesCrypto"],
 "asset_managers":["BlackRock","iShares","Fidelity","DigitalAssets","ARKInvest","CathieDWood","Grayscale","Bitwise","vaneck_us","21Shares","CoinSharesCo","Hashdex","InvescoUS","WisdomTreeFunds","ProShares"],
 "crypto_funds":["galaxyhq","PanteraCapital","a16zcrypto","paradigm","multicoin","dragonfly_xyz","ElectricCapital","blockchaincap","PlaceholderVC","HaunVentures"],
 "market_makers":["wintermute_t","GSR_io","CumberlandSays","jumpcryptohq","JaneStreetGroup","FlowTraders","DRWTrading","FalconXNetwork","B2C2Group","keyrock","Citadel","citsecurities"],
 "exchanges":["CoinbaseAssets","OKX","krakenfx","Gemini","bitget","gate_io","MEXC","HTX_Global","DeribitOfficial","cryptocom"],
 "security":["zachxbt","SlowMist_Team","CyversAlerts","chainalysis","TRMLabs"],
 "influencers":["brian_armstrong","CryptoHayes","APompliano","RaoulGMI","cobie","jack","paoloardoino","davidsacks","NayibBukele"],
 "policy":["SenateBanking","FinancialCmte","TheJusticeDept","SpeakerJohnson"]
}
WATCH=[];WATCH_CATEGORY={}
for _category,_handles in WATCH_GROUPS.items():
 for _handle in _handles:
  if _handle not in WATCH:WATCH.append(_handle);WATCH_CATEGORY[_handle]=_category

def recent():
 token=os.getenv("X_BEARER_TOKEN","").strip()
 if token:
  out=[]
  for i in range(0,len(WATCH),20):
   try:
    batch=WATCH[i:i+20];q="("+" OR ".join("from:"+x for x in batch)+") -is:retweet"
    url="https://api.x.com/2/tweets/search/recent?"+urllib.parse.urlencode({"query":q,"max_results":100,"tweet.fields":"created_at,author_id"})
    req=urllib.request.Request(url,headers={"User-Agent":"PANDORA-paper/1","Authorization":"Bearer "+token})
    with urllib.request.urlopen(req,timeout=15) as r:out.extend(json.load(r).get("data",[]))
   except Exception:pass
  if out:return out[:500]
 # credential-free delayed index fallback
 out=[]
 for h in WATCH:
  try:
   u="https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":"site:x.com/"+h,"hl":"en-US","gl":"US","ceid":"US:en"})
   root=ET.fromstring(get(u))
   for it in root.findall(".//item")[:4]:
    title=(it.findtext("title") or "").strip();link=(it.findtext("link") or "")
    if title:out.append({"id":hashlib.sha256((h+title).encode()).hexdigest(),"text":title,"source":"XPublicIndex","url":link,"created_at":it.findtext("pubDate")})
  except Exception:pass
 return out[:300]

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
NEWS_POLL_SECONDS=float(os.getenv("NEWS_POLL_SECONDS","5"))
if not math.isfinite(NEWS_MAX_AGE_SECONDS) or NEWS_MAX_AGE_SECONDS<=0:raise ValueError("invalid news freshness window")
if not math.isfinite(NEWS_POLL_SECONDS) or NEWS_POLL_SECONDS<1:raise ValueError("invalid news poll interval")
S.update({"engine_active":False,"engine_error":None,"last_checkpoint":None,"last_market_error":None})
FEEDS={"FedOfficial":"https://www.federalreserve.gov/feeds/press_all.xml","SECOfficial":"https://www.sec.gov/news/pressreleases.rss","GoogleNewsCrypto":"https://news.google.com/rss/search?q=cryptocurrency+OR+bitcoin+OR+altcoin&hl=en-US&gl=US&ceid=US:en","GoogleNewsMarkets":"https://news.google.com/rss/search?q=crypto+SEC+OR+Federal+Reserve+OR+token+listing&hl=en-US&gl=US&ceid=US:en","Cointelegraph":"https://cointelegraph.com/rss","Decrypt":"https://decrypt.co/feed","CoinDesk":"https://www.coindesk.com/arc/outboundfeeds/rss/","CFTCOfficial":"https://www.cftc.gov/RSS/RSSGP/rssgp.xml","DOJNews":"https://www.justice.gov/feeds/justice-news.xml?type=All&component%5B436%5D=436&organization=All","TruthSocialSearch":"https://news.google.com/rss/search?q=site%3Atruthsocial.com+crypto&hl=en-US&gl=US&ceid=US:en","CoinSharesResearch":"https://news.google.com/rss/search?q=site%3Acoinshares.com%2Finsights%2Fresearch-data+crypto&hl=en-US&gl=US&ceid=US:en","BitwiseResearch":"https://news.google.com/rss/search?q=site%3Abitwiseinvestments.com%2Fcrypto-market-insights+crypto&hl=en-US&gl=US&ceid=US:en","ARKResearch":"https://news.google.com/rss/search?q=site%3Aark-invest.com+bitcoin+OR+crypto&hl=en-US&gl=US&ceid=US:en","GrayscaleResearch":"https://news.google.com/rss/search?q=site%3Aresearch.grayscale.com+crypto&hl=en-US&gl=US&ceid=US:en"}
# Fast public news sources and topical feeds; Google-indexed posts can be delayed.
FEEDS.update({
 "BBCWorld":"https://feeds.bbci.co.uk/news/world/rss.xml",
 "GuardianWorld":"https://www.theguardian.com/world/rss",
 "NPRWorld":"https://feeds.npr.org/1004/rss.xml",
 "AlJazeera":"https://www.aljazeera.com/xml/rss/all.xml",
 "WSJWorld":"https://feeds.a.dj.com/rss/RSSWorldNews.xml",
 "CNBCMarkets":"https://www.cnbc.com/id/100003114/device/rss/rss.html",
 "ECBOfficial":"https://www.ecb.europa.eu/rss/press.html",
 "GoogleNewsBreaking":"https://news.google.com/rss/search?q=breaking+world+news+markets&hl=en-US&gl=US&ceid=US:en",
 "GoogleNewsGeopolitics":"https://news.google.com/rss/search?q=conflict+sanctions+tariffs+war+blockade&hl=en-US&gl=US&ceid=US:en",
 "GoogleNewsOil":"https://news.google.com/rss/search?q=OPEC+oil+shipping+Hormuz+Suez&hl=en-US&gl=US&ceid=US:en",
 "GoogleNewsChina":"https://news.google.com/rss/search?q=China+Taiwan+trade+tariffs+markets&hl=en-US&gl=US&ceid=US:en",
 "GoogleNewsMacro":"https://news.google.com/rss/search?q=FOMC+Fed+CPI+inflation+rates&hl=en-US&gl=US&ceid=US:en",
 "GoogleNewsCryptoHack":"https://news.google.com/rss/search?q=crypto+exchange+hack+exploit+liquidation&hl=en-US&gl=US&ceid=US:en",
 "GoogleNewsCryptoPolicy":"https://news.google.com/rss/search?q=SEC+CFTC+crypto+regulation+ETF&hl=en-US&gl=US&ceid=US:en",
 "GoogleNewsTokenEvents":"https://news.google.com/rss/search?q=cryptocurrency+token+listing+unlock+delisting&hl=en-US&gl=US&ceid=US:en",
})
# Credential-free coverage of public X account mentions, with indexer delay.
# These are not authenticated X timelines; source status reports that distinction.
for _i in range(0,len(WATCH),4):
 _group=WATCH[_i:_i+4]
 FEEDS["XIndex:"+",".join(_group)]="https://news.google.com/rss/search?"+urllib.parse.urlencode({
  "q":"("+" OR ".join("site:x.com/"+h for h in _group)+")",
  "hl":"en-US","gl":"US","ceid":"US:en"
 })
POS=("pump","pumping","surge","surges","approve","approved","approval","partnership","listing","adoption","buyback","breakout","bullish","launch","etf approved","rally","rallies","rebound","rebounds","record high","inflows","net inflow","gains","jumps","soars","upside")
NEG=("dump","dumping","hack","hacked","exploit","lawsuit","delist","delisted","ban","banned","liquidation","liquidations","fraud","selloff","sell-off","bearish","crash","crashes","stolen","outflows","net outflow","falls","drops","slips","plunges","tumbles","declines")
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
def source_weight(source):
 if source.startswith("XIndex:"):return 0.40
 if source.startswith("XOfficial:"):return 0.90
 return float(SOURCE_WEIGHTS.get(source,0.50))
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

def impulse_scan():
 # Independent price-impulse scanner; never blocks exit protection.
 while not SHUTDOWN.is_set():
  try:
   with LOCK:
    prices=dict(S.get("_prices",{}))
    history={k:list(v) for k,v in S.get("_timeline",{}).items()}
    volumes=dict(S.get("_day_volumes",{}))
   stamp=time.time()
   found=momentum_candidates(prices,history,volumes,stamp)
   with LOCK:
    S["sources"]["ImpulseScanner"]={"ok":bool(prices and volumes),"last_check":now(),"markets":len(prices),"liquid_markets":sum(v>=1000000 for v in volumes.values()),"candidates":len(found),"mode":"all_markets_2s_poll","error":None if prices and volumes else "missing_market_prices_or_24h_volumes"}
   for candidate in found[:12]:
    sym=candidate["symbol"]
    window=candidate["window"]
    bucket=int(stamp//max(30,window))
    ident=hashlib.sha256(("IMPULSE:"+sym+":"+str(candidate["side"])+":"+str(window)+":"+str(bucket)).encode()).hexdigest()
    title=("Market pump " if candidate["side"]>0 else "Market dump ")+sym+" "+str(candidate["change_pct"])+"% / "+str(window)+"s"
    ingest_event(ident,"ImpulseScanner",title,now(),None)
  except Exception as e:
   with LOCK:S["sources"]["ImpulseScanner"]={"ok":False,"last_check":now(),"error":str(e)[:140]}
  SHUTDOWN.wait(2)

def market_metadata():
 while not SHUTDOWN.is_set():
  try:
   raw=json.loads(get(API,{"type":"metaAndAssetCtxs"}))
   universe=raw[0].get("universe",[]);ctxs=raw[1]
   volumes={}
   for asset,ctx in zip(universe,ctxs):
    try:
     v=float(ctx.get("dayNtlVlm",0))
     if math.isfinite(v) and v>=0:volumes[asset["name"]]=v
    except (TypeError,ValueError,KeyError):continue
   with LOCK:
    S["_day_volumes"]=volumes
    S["sources"]["MarketMetadata"]={"ok":True,"last_check":now(),"markets":len(volumes)}
  except Exception as e:
   with LOCK:S["sources"]["MarketMetadata"]={"ok":False,"last_check":now(),"error":str(e)[:140]}
  SHUTDOWN.wait(25)

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
   out["liquidation_map"]={"type":"estimated_pressure_not_confirmed_liquidations","bid_depth_top10":b,"ask_depth_top10":a,"imbalance":out["orderbook_imbalance"],"data_source":"hyperliquid_l2_book"}
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
  elif sym in S["positions"] and S["positions"][sym]["side"]==side:reason="position_already_open"
  elif sym in S["positions"]:
   oldpos=S["positions"][sym]
   px=S["_prices"][sym]
   closed=STORE.close(sym,oldpos,px,"news_reversal")
   if closed is None:
    journal("entry_skipped",event_id,{"symbol":sym,"reason":"reversal_close_not_committed"})
    return False
   S["equity"]=float(closed["equity"]);S["realized_pnl"]=float(closed["realized_pnl"])
   S["trades"]+=1
   del S["positions"][sym]
   journal("news_reversal",event_id,{"symbol":sym,"new_side":side,"closed_side":oldpos["side"],"close_price":px})
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

def free_x_realtime():
 if os.getenv("X_STREAM_BEARER_TOKEN","").strip():return
 if os.getenv("X_AUTH_TOKEN","").strip() and os.getenv("X_CT0","").strip() and os.getenv("X_LIST_ID","").strip():return
 handles=list(WATCH);poll=max(4.0,float(os.getenv("X_FREE_POLL_SECONDS","4")))
 fx_primary=set(handles[:min(58,len(handles))])
 seen={};primed=set();state_lock=threading.Lock()
 next_due={h:time.monotonic()+i*poll/max(1,len(handles)) for i,h in enumerate(handles)}
 inflight={};ingest_futures=set()
 pool=concurrent.futures.ThreadPoolExecutor(max_workers=48,thread_name_prefix="x-realtime")
 ingest_pool=concurrent.futures.ThreadPoolExecutor(max_workers=8,thread_name_prefix="x-ingest")
 def fetch_one(handle):
  primary=("fx",free_x_fetch) if handle in fx_primary else ("xlookup",free_x_lookup_fetch)
  secondary=("xlookup",free_x_lookup_fetch) if primary[0]=="fx" else ("fx",free_x_fetch)
  errors=[]
  for backend,fn in (primary,secondary):
   try:return fn(handle),backend,backend!=primary[0],(" | ".join(errors) if errors else None)
   except Exception as exc:errors.append(backend+":"+str(exc)[:70])
  try:return guest_x_read(handle),"guest_graphql",True," | ".join(errors)
  except Exception as exc:errors.append("guest:"+str(exc)[:70])
  try:return free_x_syndication_fetch(handle),"syndication",True," | ".join(errors)
  except Exception as exc:errors.append("syndication:"+str(exc)[:70])
  try:return free_x_vx_fetch(handle),"vx",True," | ".join(errors)
  except Exception as exc:errors.append("vx:"+str(exc)[:70])
  raise RuntimeError(" | ".join(errors))
 try:
  while not SHUTDOWN.is_set():
   if not S["engine_active"]:
    SHUTDOWN.wait(0.5);continue
   now_m=time.monotonic()
   active={meta[0] for meta in inflight.values()}
   for handle in handles:
    if handle in active or now_m<next_due[handle]:continue
    fut=pool.submit(fetch_one,handle);inflight[fut]=(handle,now_m)
    next_due[handle]+=poll
    if next_due[handle]<now_m:next_due[handle]=now_m+poll
   done=[future for future in list(inflight) if future.done()]
   for future in done:
    handle,started=inflight.pop(future);name="XFree:"+handle
    try:
     posts,backend,fallback,primary_error=future.result()
     stamps=[publication_epoch(p.get("created_at")) for p in posts];stamps=[x for x in stamps if x is not None]
     latest_age=(time.time()-max(stamps)) if stamps else None
     with LOCK:
      S["sources"][name]={"ok":True,"degraded":bool(fallback),"mode":backend+"_4s_poll","backend":backend,
       "fallback_used":bool(fallback),"primary_error":primary_error,"category":WATCH_CATEGORY.get(handle),
       "last_check":now(),"posts":len(posts),"poll_seconds":poll,
       "latest_post_age_seconds":round(latest_age,1) if latest_age is not None else None,
       "realtime_verified":False,"consecutive_failures":0,"last_success_epoch":time.time()}
     ids=[str(p["id"]) for p in posts]
     with state_lock:
      if handle not in primed:
       seen[handle]=set(ids);primed.add(handle);fresh=[]
      else:
       old=seen.setdefault(handle,set());fresh=[p for p in posts if str(p["id"]) not in old];old.update(ids)
       if len(old)>200:seen[handle]=set(ids[:100])
     for p in sorted(fresh,key=lambda q:publication_epoch(q.get("created_at")) or 0):
      stamp=publication_epoch(p.get("created_at"));age=time.time()-stamp if stamp is not None else None
      if age is not None and 0<=age<=10:
       with LOCK:
        S["sources"][name]["realtime_verified"]=True
        S["sources"][name]["delivery_latency_seconds"]=round(age,2)
      ident=hashlib.sha256(("XFree:"+handle+":"+str(p["id"])).encode()).hexdigest()
      if len(ingest_futures)<500:
       ingest_futures.add(ingest_pool.submit(ingest_event,ident,"XOfficial:"+handle,p["text"],p.get("created_at"),p.get("url")))
    except Exception as exc:
     err=str(exc)[:220] if str(exc) else type(exc).__name__
     with LOCK:
      prev=S["sources"].get(name,{})
      failures=int(prev.get("consecutive_failures",0))+1
      last_success_epoch=float(prev.get("last_success_epoch",0) or 0)
      within_grace=bool(last_success_epoch and time.time()-last_success_epoch<=30 and failures<4)
      S["sources"][name]={"ok":within_grace,"degraded":True,"mode":"fx_xlookup_guest_syndication_4s",
       "category":WATCH_CATEGORY.get(handle),"last_check":now(),"error":err,
       "consecutive_failures":failures,"last_success_epoch":last_success_epoch or None}
   ingest_futures={future for future in ingest_futures if not future.done()}
   with LOCK:
    states=[S["sources"].get("XFree:"+h,{}) for h in handles]
    initialized=sum(bool(v) for v in states);good=sum(bool(v.get("ok")) for v in states)
    realtime=sum(bool(v.get("realtime_verified")) for v in states)
    backend_live={b:sum(1 for v in states if v.get("ok") and v.get("backend")==b) for b in ("fx","xlookup","guest_graphql","syndication","vx")}
    S["sources"]["XMonitor"]={"ok":initialized==len(handles) and good>=math.ceil(len(handles)*0.90),
     "all_accounts_ok":initialized==len(handles) and good==len(handles),
     "mode":"fx_xlookup_guest_parallel_4s_poll","last_check":now(),"accounts_ok":good,
     "accounts_initialized":initialized,"accounts_total":len(handles),
     "fx_primary":len(fx_primary),"xlookup_primary":len(handles)-len(fx_primary),
     "backend_live":backend_live,"poll_seconds":poll,"realtime_accounts_seen":realtime,
     "ingest_queue":len(ingest_futures),"realtime_verified":realtime>0}
   SHUTDOWN.wait(0.05)
 finally:
  pool.shutdown(wait=False,cancel_futures=True)
  ingest_pool.shutdown(wait=False,cancel_futures=True)

def x_list_realtime():
 auth=os.getenv("X_AUTH_TOKEN","").strip();ct0=os.getenv("X_CT0","").strip();list_id=os.getenv("X_LIST_ID","").strip()
 if not (auth and ct0 and list_id):return
 poll=max(4.0,float(os.getenv("X_LIST_POLL_SECONDS","4")))
 watched={h.lower():h for h in WATCH};seen=set();primed=False;backoff=poll
 ingest_pool=concurrent.futures.ThreadPoolExecutor(max_workers=8,thread_name_prefix="x-list-ingest")
 try:
  while not SHUTDOWN.is_set():
   if not S["engine_active"]:
    SHUTDOWN.wait(0.5);continue
   started=time.monotonic()
   try:
    posts=x_list_fetch(list_id,auth,ct0,count=100)
    current={str(p["id"]) for p in posts if str(p.get("handle","")).lower() in watched}
    if not primed:
     seen=set(current);primed=True;fresh=[]
    else:
     fresh=[p for p in posts if str(p.get("handle","")).lower() in watched and str(p["id"]) not in seen]
     seen.update(current)
     if len(seen)>2000:seen=set(list(current)[:1000])
    latencies=[]
    for p in sorted(fresh,key=lambda q:publication_epoch(q.get("created_at")) or 0):
     stamp=publication_epoch(p.get("created_at"));age=time.time()-stamp if stamp is not None else None
     if age is not None and age>=0:latencies.append(age)
     handle=watched.get(str(p.get("handle","")).lower(),str(p.get("handle") or "unknown"))
     ident=hashlib.sha256(("XList:"+str(p["id"])).encode()).hexdigest()
     ingest_pool.submit(ingest_event,ident,"XOfficial:"+handle,p["text"],p.get("created_at"),p.get("url"))
    latency=min(latencies) if latencies else None
    with LOCK:S["sources"]["XListMonitor"]={"ok":True,"mode":"authenticated_x_list_4s_poll","last_check":now(),"accounts_total":len(WATCH),"posts":len(posts),"poll_seconds":poll,"realtime_verified":bool(latency is not None and 0<=latency<=10),"delivery_latency_seconds":round(latency,2) if latency is not None else None}
    backoff=poll
   except Exception as exc:
    err=str(exc)[:180] if str(exc) else type(exc).__name__
    with LOCK:S["sources"]["XListMonitor"]={"ok":False,"mode":"authenticated_x_list_4s_poll","last_check":now(),"accounts_total":len(WATCH),"error":err,"realtime_verified":False}
    backoff=min(60,max(poll,backoff*1.8))
   SHUTDOWN.wait(max(0.05,backoff-(time.monotonic()-started)))
 finally:
  ingest_pool.shutdown(wait=False,cancel_futures=True)

def truth_stream_realtime():
 token=(os.getenv("TRUTH_STREAM_TOKEN","").strip() or os.getenv("TRUTHSOCIAL_TOKEN","").strip())
 if not token:
  username=os.getenv("TRUTHSOCIAL_USERNAME","").strip();password=os.getenv("TRUTHSOCIAL_PASSWORD","")
  if username and password:
   try:
    token=TruthApi(require_auth=True).get_auth_id(username,password)
    with LOCK:S["sources"]["TruthAuth"]={"ok":True,"mode":"user_password_to_oauth_token_in_memory","last_check":now(),"error":None}
   except Exception as exc:
    with LOCK:S["sources"]["TruthAuth"]={"ok":False,"mode":"user_password_to_oauth_token_in_memory","last_check":now(),"error":type(exc).__name__}
    return
  else:
   with LOCK:S["sources"]["TruthAuth"]={"ok":False,"mode":"user_oauth_required","last_check":now(),"error":"set_TRUTHSOCIAL_USERNAME_and_PASSWORD_or_TRUTH_STREAM_TOKEN"}
   return
 handles={h.strip().lower() for h in os.getenv("TRUTH_WATCH_HANDLES","realDonaldTrump,WhiteHouse,DanScavino,Kash,MelaniaTrump,SecWar,SpeakerJohnson,seckennedy").split(",") if h.strip()}
 url="wss://truthsocial.com/api/v1/streaming?stream=public:local"
 backoff=3
 while not SHUTDOWN.is_set():
  if not S["engine_active"]:
   SHUTDOWN.wait(2);continue
  ws=None
  try:
   ws=websocket.create_connection(url,header=["Authorization: Bearer "+token,"User-Agent: PANDORA-news-stream/1"],timeout=35)
   with LOCK:S["sources"]["TruthStream"]={"ok":True,"mode":"mastodon_websocket_public_local","last_check":now(),"accounts":len(handles),"realtime_verified":False}
   backoff=3
   while not SHUTDOWN.is_set():
    raw=ws.recv()
    if raw is None:raise RuntimeError("truth_stream_closed")
    if not raw:continue
    packet=json.loads(raw)
    if packet.get("event")!="update":continue
    payload=packet.get("payload")
    status=json.loads(payload) if isinstance(payload,str) else payload
    if not isinstance(status,dict):continue
    account=status.get("account") or {}
    handle=str(account.get("acct") or account.get("username") or "").split("@")[0]
    if handle.lower() not in handles:continue
    title=re.sub("<[^>]+>"," ",status.get("content") or "");title=re.sub(r"\s+"," ",title).strip()
    if not title:continue
    pub=status.get("created_at")
    stamp=publication_epoch(pub);age=time.time()-stamp if stamp is not None else None
    with LOCK:S["sources"]["TruthStream"]={"ok":True,"mode":"mastodon_websocket_public_local","last_check":now(),"accounts":len(handles),"last_handle":handle,"latest_post_age_seconds":round(age,2) if age is not None else None,"delivery_latency_seconds":round(age,2) if age is not None and age>=0 else None,"realtime_verified":bool(age is not None and 0<=age<=10)}
    ident=hashlib.sha256(("TruthStream:"+str(status.get("id") or status.get("url") or title)).encode()).hexdigest()
    ingest_event(ident,"TruthSocialPublic",title,pub,status.get("url"))
  except Exception as exc:
   err=str(exc)[:140] if str(exc) else type(exc).__name__
   with LOCK:S["sources"]["TruthStream"]={"ok":False,"mode":"mastodon_websocket_public_local","last_check":now(),"error":err,"realtime_verified":False}
   SHUTDOWN.wait(backoff);backoff=min(120,backoff*2)
  finally:
   try:
    if ws:ws.close()
   except Exception:pass

def free_truth_realtime():
 if (os.getenv("TRUTH_STREAM_TOKEN","").strip() or os.getenv("TRUTHSOCIAL_TOKEN","").strip()):return
 handles=[h.strip() for h in os.getenv("TRUTH_WATCH_HANDLES","realDonaldTrump,WhiteHouse,DanScavino,Kash,MelaniaTrump,SecWar,SpeakerJohnson,seckennedy").split(",") if h.strip()]
 poll=max(5.0,float(os.getenv("TRUTH_FREE_POLL_SECONDS","10")))
 seen={};ids_cache={}
 pool=concurrent.futures.ThreadPoolExecutor(max_workers=min(8,max(1,len(handles))),thread_name_prefix="truth-free")
 try:
  while not SHUTDOWN.is_set():
   if not S["engine_active"]:
    SHUTDOWN.wait(2);continue
   started=time.monotonic()
   futures={pool.submit(free_truth_fetch,h,ids_cache.get(h)):h for h in handles}
   for future in concurrent.futures.as_completed(futures):
    h=futures[future];name="TruthDirect:"+h
    try:
     account_id,posts,headers=future.result();ids_cache[h]=account_id
     stamps=[publication_epoch(p.get("created_at")) for p in posts];stamps=[x for x in stamps if x is not None]
     latest_age=(time.time()-max(stamps)) if stamps else None
     with LOCK:S["sources"][name]={"ok":True,"mode":"truth_rest_chrome_impersonation","last_check":now(),"posts":len(posts),"poll_seconds":poll,"latest_post_age_seconds":round(latest_age,1) if latest_age is not None else None,"realtime_verified":False,"ratelimit_remaining":headers.get("x-ratelimit-remaining")}
     ids=[str(p["id"]) for p in posts]
     if h not in seen:
      seen[h]=set(ids);continue
     old=seen[h];fresh=[p for p in posts if str(p["id"]) not in old];old.update(ids)
     if len(old)>200:seen[h]=set(ids[:100])
     for p in sorted(fresh,key=lambda q:publication_epoch(q.get("created_at")) or 0):
      age=time.time()-(publication_epoch(p.get("created_at")) or 0)
      if 0<=age<=10:
       with LOCK:S["sources"][name]["realtime_verified"]=True;S["sources"][name]["delivery_latency_seconds"]=round(age,2)
      ident=hashlib.sha256(("TruthDirect:"+h+":"+str(p["id"])).encode()).hexdigest()
      ingest_event(ident,"TruthSocialPublic",p["text"],p.get("created_at"),p.get("url"))
    except Exception as exc:
     rest_err=str(exc)[:100] if str(exc) else type(exc).__name__
     try:
      posts=free_truth_ap_fetch(h)
      stamps=[publication_epoch(p.get("created_at")) for p in posts];stamps=[x for x in stamps if x is not None]
      latest_age=(time.time()-max(stamps)) if stamps else None
      with LOCK:S["sources"][name]={"ok":True,"mode":"truth_activitypub_outbox","last_check":now(),"posts":len(posts),"poll_seconds":poll,"latest_post_age_seconds":round(latest_age,1) if latest_age is not None else None,"realtime_verified":False,"rest_error":rest_err}
      ids=[str(p["id"]) for p in posts]
      if h not in seen:seen[h]=set(ids);continue
      old=seen[h];fresh=[p for p in posts if str(p["id"]) not in old];old.update(ids)
      if len(old)>200:seen[h]=set(ids[:100])
      for p in sorted(fresh,key=lambda q:publication_epoch(q.get("created_at")) or 0):
       age=time.time()-(publication_epoch(p.get("created_at")) or 0)
       if 0<=age<=10:
        with LOCK:S["sources"][name]["realtime_verified"]=True;S["sources"][name]["delivery_latency_seconds"]=round(age,2)
       ident=hashlib.sha256(("TruthAP:"+h+":"+str(p["id"])).encode()).hexdigest()
       ingest_event(ident,"TruthSocialPublic",p["text"],p.get("created_at"),p.get("url"))
     except Exception as ap_exc:
      ap_err=str(ap_exc)[:100] if str(ap_exc) else type(ap_exc).__name__
      with LOCK:S["sources"][name]={"ok":False,"mode":"truth_rest_then_activitypub","last_check":now(),"error":rest_err+" | "+ap_err}
   with LOCK:
    states=[v for k,v in S["sources"].items() if k.startswith("TruthDirect:")]
    good=sum(bool(v.get("ok")) for v in states)
    S["sources"]["TruthSocialPublic"]={"ok":good>=max(1,int(len(handles)*0.75)),"mode":"direct_parallel_rest","last_check":now(),"accounts_ok":good,"accounts_total":len(handles),"poll_seconds":poll,"realtime_verified":any(v.get("realtime_verified") for v in states)}
   SHUTDOWN.wait(max(0.1,poll-(time.monotonic()-started)))
 finally:
  pool.shutdown(wait=False,cancel_futures=True)

def x_filtered_stream():
 # Official X stream, 1 connection for all watched accounts. Requires authorized token.
 token=os.getenv("X_STREAM_BEARER_TOKEN","").strip()
 if not token:return
 headers={"Authorization":"Bearer "+token,"User-Agent":"Pandora-news-stream/1","Accept":"application/json"}
 rules_url="https://api.x.com/2/tweets/search/stream/rules"
 stream_url="https://api.x.com/2/tweets/search/stream?tweet.fields=created_at,author_id"
 backoff=5
 while not SHUTDOWN.is_set():
  if not S["engine_active"]:
   SHUTDOWN.wait(3);continue
  try:
   req=urllib.request.Request(rules_url,headers=headers)
   with urllib.request.urlopen(req,timeout=12) as response:rules=json.load(response).get("data",[])
   own={r.get("tag"):r for r in rules if str(r.get("tag","")).startswith("pandora:")}
   existing={tag.split(":",1)[1] for tag in own}
   if set(WATCH)!=existing:
    if own:
     payload=json.dumps({"delete":{"ids":[r["id"] for r in own.values()]}}).encode()
     req=urllib.request.Request(rules_url,data=payload,headers={**headers,"Content-Type":"application/json"},method="POST")
     with urllib.request.urlopen(req,timeout=12) as response:response.read()
    for start in range(0,len(WATCH),20):
     chunk=WATCH[start:start+20]
     payload=json.dumps({"add":[{"value":"from:"+h+" -is:retweet","tag":"pandora:"+h} for h in chunk]}).encode()
     req=urllib.request.Request(rules_url,data=payload,headers={**headers,"Content-Type":"application/json"},method="POST")
     with urllib.request.urlopen(req,timeout=12) as response:response.read()
   req=urllib.request.Request(stream_url,headers=headers)
   with urllib.request.urlopen(req,timeout=90) as response:
    with LOCK:S["sources"]["XFilteredStream"]={"ok":True,"mode":"official_continuous_stream","last_check":now(),"accounts":len(WATCH),"realtime_verified":False}
    backoff=5
    for line in response:
     if SHUTDOWN.is_set():break
     if not line.strip():continue
     packet=json.loads(line)
     item=packet.get("data")
     if not isinstance(item,dict) or not item.get("id"):continue
     title=(item.get("text") or "").strip()
     if not title:continue
     pub=item.get("created_at")
     age=time.time()-publication_epoch(pub) if publication_epoch(pub) is not None else None
     with LOCK:S["sources"]["XFilteredStream"]={"ok":True,"mode":"official_continuous_stream","last_check":now(),"accounts":len(WATCH),"posts":S["sources"].get("XFilteredStream",{}).get("posts",0)+1,"latest_post_age_seconds":round(age,1) if age is not None else None,"realtime_verified":bool(age is not None and 0<=age<=10)}
     ident=hashlib.sha256(("XStream:"+str(item["id"])).encode()).hexdigest()
     ingest_event(ident,"XOfficial",title,pub,"https://x.com/i/status/"+str(item["id"]))
  except Exception as exc:
   error="http_"+str(exc.code) if hasattr(exc,"code") else type(exc).__name__
   with LOCK:S["sources"]["XFilteredStream"]={"ok":False,"mode":"official_continuous_stream","last_check":now(),"error":error,"realtime_verified":False}
   SHUTDOWN.wait(backoff)
   backoff=min(300,backoff*2)

def guest_x_worker():
 if os.getenv("X_STREAM_BEARER_TOKEN","").strip():return
 index=0
 while not SHUTDOWN.is_set():
  if not S["engine_active"]:
   SHUTDOWN.wait(3);continue
  handle=WATCH[index%len(WATCH)];index+=1
  name="XGuest:"+handle
  try:
   posts=guest_x_read(handle)
   stamps=[publication_epoch(p.get("created_at")) for p in posts]
   stamps=[t for t in stamps if t is not None]
   age=time.time()-max(stamps) if stamps else None
   with LOCK:S["sources"][name]={"ok":bool(posts and age is not None and age<=300),"transport_ok":bool(posts),"last_check":now(),"mode":"guest_graphql","posts":len(posts),"latest_post_age_seconds":round(age,1) if age is not None else None,"realtime_verified":bool(age is not None and age<=120),"error":"stale_timeline" if age is not None and age>300 else ("missing_timestamp" if age is None else None)}
   for p in posts:
    ident=hashlib.sha256(("XGuest:"+handle+":"+str(p["id"])).encode()).hexdigest()
    ingest_event(ident,"XOfficial",p["text"],p.get("created_at"),p.get("url"))
  except Exception as exc:
   error=("http_"+str(exc.code)) if hasattr(exc,"code") else type(exc).__name__
   with LOCK:S["sources"][name]={"ok":False,"last_check":now(),"mode":"guest_graphql","error":error}
   if error in ("http_429","http_403","http_401"):
    SHUTDOWN.wait(60)
  SHUTDOWN.wait(5)

def xnews():
 # An anonymous X news index is NOT a direct real-time X feed.
 # Report it as usable only if at least one indexed RSS feed responded.
 if not os.getenv("X_BEARER_TOKEN","").strip():
  while not SHUTDOWN.is_set():
   with LOCK:
    valid=[(k,v) for k,v in S["sources"].items() if k.startswith("XIndex:") and v.get("ok")]
    S["sources"]["XIndexMonitor"]={"ok":bool(valid),"last_check":now(),
     "mode":"guest_public_index_delayed","watch_accounts":len(WATCH),
     "responsive_feeds":len(valid),"total_feeds":sum(k.startswith("XIndex:") for k in FEEDS),
     "realtime_verified":False}
   SHUTDOWN.wait(30)
  return
 while not SHUTDOWN.is_set():
  try:
   posts=recent()
   with LOCK:S["sources"]["XIndexMonitor"]={"ok":True,"last_check":now(),
    "posts":len(posts),"mode":"official_api","watch_accounts":len(WATCH)}
   for p in posts:
    if SHUTDOWN.is_set():break
    title=(p.get("text") or "").strip()
    if not title:continue
    source=p.get("source","XOfficial")
    ident=hashlib.sha256((source+str(p.get("id",title))).encode()).hexdigest()
    ingest_event(ident,source,title,p.get("created_at"),p.get("url"))
  except Exception as e:
   with LOCK:S["sources"]["XIndexMonitor"]={"ok":False,"last_check":now(),"error":str(e)[:140]}
  SHUTDOWN.wait(20)

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
   try:
    archive=public_social_read("truth","realDonaldTrump")
    with LOCK:S["sources"]["TruthSocialPublic"]={"ok":False,"archive_available":bool(archive),"last_check":now(),"mode":"archive_fallback_not_direct","direct_ok":False,"direct_error":str(e)[:140],"posts":len(archive),"realtime_verified":False,"error":"direct_api_unavailable"}
    for p in archive:
     ident=hashlib.sha256(("TruthArchive"+str(p["id"])).encode()).hexdigest()
     ingest_event(ident,"TruthArchive",p["text"],p.get("created_at"),p.get("url"))
    delay=10 if archive else 30
   except Exception as backup_error:
    with LOCK:S["sources"]["TruthSocialPublic"]={"ok":False,"last_check":now(),"mode":"all_routes_failed","direct_error":str(e)[:140],"archive_error":type(backup_error).__name__}
    delay=min(300,max(10,delay*2))
  SHUTDOWN.wait(delay)

def social_reader(kind):
 source="XScrape" if kind=="x" else "Truthbrush"
 canonical="XOfficial" if kind=="x" else "TruthSocialPublic"
 handles=WATCH if kind=="x" else ["realDonaldTrump"]
 interval=5
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
 interval=5
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
 handles=[h.strip() for h in os.getenv("TRUTH_WATCH_HANDLES","realDonaldTrump").split(",") if h.strip()]
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
 base_poll=max(5,NEWS_POLL_SECONDS) if "news.google.com" not in url else max(60,NEWS_POLL_SECONDS)
 delay=base_poll
 while not SHUTDOWN.is_set():
  try:
   root=ET.fromstring(get(url));items=root.findall(".//item")[:30];count=0
   for item in reversed(items):
    if SHUTDOWN.is_set():break
    title=(item.findtext("title") or "").strip()
    if not title:continue
    ident=hashlib.sha256((source+title).encode()).hexdigest()
    count+=bool(ingest_event(ident,source,title,item.findtext("pubDate"),item.findtext("link")))
   with LOCK:S["sources"][source]={"ok":True,"last_check":now(),"new":count,"feed_items":len(items),"poll_seconds":base_poll,"mode":"indexed_delayed" if "news.google.com" in url else "rss_direct","realtime_verified":False}
   delay=base_poll
  except Exception as e:
   with LOCK:
    S["errors"]+=1;S["last_error"]=source+": "+str(e)[:180]
    S["sources"][source]={"ok":False,"last_check":now(),"error":str(e)[:150]}
   delay=min(300,max(base_poll,delay*2))
  SHUTDOWN.wait(delay)
def build_dashboard_snapshot():
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
 return {"mode":state["mode"],"balance":round(state["equity"],4),"unrealized_pnl":round(unreal,4),"total_equity":round(total,4),"realized_pnl":round(state["realized_pnl"],4),"account_started":account_started,"account_age_seconds":account_age_seconds,"account_roi_pct":round(account_roi,3),"positions":positions,"trades":trades,"news":newsrows,"features":feats,"sources":state["sources"],"errors":state["errors"],"last_error":state["last_error"],"news_seen":state["news_seen"],"market_count":state["market_count"],"last_poll":state["last_poll"],"uptime_seconds":int(time.time()-START),"engine_active":state["engine_active"],"engine_error":state["engine_error"],"last_checkpoint":state["last_checkpoint"],"last_market_error":state["last_market_error"],"news_max_age_seconds":NEWS_MAX_AGE_SECONDS,"market_structure_filter_active":False,"entry_rejections":dict(S.get("_entry_rejections",{})),"decision_counts":dict(S.get("_decision_counts",{})),"version":os.getenv("RENDER_GIT_COMMIT","risk-state-v2")}

def dashboard():
 with LOCK:
  cached=S.get("_dashboard_cache")
  if cached:return copy.deepcopy(cached)
  state={k:copy.deepcopy(v) for k,v in S.items() if not k.startswith("_")}
  prices=dict(S.get("_prices",{}))
 positions=[]
 unreal=0.0
 for sym,p in state["positions"].items():
  price=prices.get(sym,p["entry"])
  pnl=p["notional"]*(price/p["entry"]-1)*p["side"]-p["notional"]*FEE*2
  margin=float(p.get("margin",p["notional"]/max(1,float(p.get("leverage",LEV)))))
  unreal+=pnl
  positions.append({"symbol":sym,"side":"LONG" if p["side"]>0 else "SHORT",
   "entry":p["entry"],"mark":price,"notional_usd":round(p["notional"],2),
   "margin_usd":round(margin,2),"leverage":p.get("leverage",LEV),
   "roe_pct":round(pnl/margin*100,3) if margin else 0,"unrealized_pnl":round(pnl,4),
   "opened":p["opened"],"headline":p.get("headline","")})
 return {"mode":state["mode"],"balance":round(state["equity"],4),"unrealized_pnl":round(unreal,4),
  "total_equity":round(state["equity"]+unreal,4),"realized_pnl":round(state["realized_pnl"],4),
  "account_age_seconds":0,"account_roi_pct":round(((state["equity"]+unreal)/PAPER_RESET-1)*100,3),
  "positions":positions,"trades":[],"news":[],"features":[],"sources":state["sources"],
  "errors":state["errors"],"last_error":state["last_error"],"news_seen":state["news_seen"],
  "market_count":state["market_count"],"last_poll":state["last_poll"],
  "uptime_seconds":int(time.time()-START),"engine_active":state["engine_active"],
  "engine_error":state["engine_error"],"last_checkpoint":state["last_checkpoint"],
  "last_market_error":state["last_market_error"],"news_max_age_seconds":NEWS_MAX_AGE_SECONDS,
  "market_structure_filter_active":False,"version":os.getenv("RENDER_GIT_COMMIT","risk-state-v2")}

def operations_diagnostics():
 while not SHUTDOWN.is_set():
  try:
   health=health_state()
   with LOCK:
    report={"kind":"pandora_diagnostics","time":now(),"engine_active":S["engine_active"],
     "engine_error":S.get("engine_error"),"market_count":S.get("market_count"),
     "market_error":S.get("last_market_error"),"positions":len(S["positions"]),
     "trades":S.get("trades"),"news_seen":S.get("news_seen"),
     "sources_ok":sum(bool(x.get("ok")) for x in S["sources"].values()),
     "sources_failed":[k for k,v in S["sources"].items() if not v.get("ok")],
     "social_channels":{k:{"ok":v.get("ok"),"mode":v.get("mode"),"posts":v.get("posts"),"last_check":v.get("last_check"),"error":v.get("error"),"realtime_verified":v.get("realtime_verified"),"latest_post_age_seconds":v.get("latest_post_age_seconds"),"delivery_latency_seconds":v.get("delivery_latency_seconds"),"accounts_ok":v.get("accounts_ok"),"accounts_initialized":v.get("accounts_initialized"),"accounts_total":v.get("accounts_total"),"all_accounts_ok":v.get("all_accounts_ok"),"fx_primary":v.get("fx_primary"),"xlookup_primary":v.get("xlookup_primary")} for k,v in S["sources"].items() if k.startswith(("XFree:","XFilteredStream","XListMonitor","XMonitor","XIndexMonitor","TruthAuth","TruthStream","TruthDirect:","TruthSocialPublic"))},
     "entry_rejections":dict(S.get("_entry_rejections",{})),
     "risk_ready":health["risk_ready"]}
   print(json.dumps(report,ensure_ascii=False,default=str),flush=True)
  except Exception as e:print("diagnostics_error: "+str(e)[:180],flush=True)
  SHUTDOWN.wait(30)

def dashboard_cache_loop():
 while not SHUTDOWN.is_set():
  try:
   value=build_dashboard_snapshot()
   with LOCK:S["_dashboard_cache"]=value
  except Exception as exc:
   with LOCK:S["last_error"]="dashboard_cache: "+str(exc)[:150]
  SHUTDOWN.wait(5)

def html_dashboard(data):
 esc=lambda x:str(x).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
 age=data.get("account_age_seconds",0);age_txt="%dd %02dh %02dm"%(age//86400,(age%86400)//3600,(age%3600)//60)
 cards='<div class="grid"><b>MODE<br>%s</b><b>BALANCE<br>$ %s</b><b>P&L IF CLOSED NOW<br>$ %s</b><b>ACCOUNT IF CLOSED NOW<br>$ %s</b><b>ACCOUNT ROI<br>%s%%</b><b>ACCOUNT AGE<br>%s</b><b>POSITIONS<br>%s</b></div>'%(esc(data["mode"]),data["balance"],data["unrealized_pnl"],data["total_equity"],data["account_roi_pct"],age_txt,len(data["positions"]))
 pos="".join('<tr><td>%s</td><td>%s</td><td>$%s</td><td>$%s</td><td>%sx</td><td>%s</td><td>%s</td><td class="%s">%s%%</td><td class="%s">$%s</td><td>%s</td><td><button onclick="closePos(this.dataset.sym)" data-sym="%s">Close</button></td></tr>'%(esc(x["symbol"]),x["side"],x.get("margin_usd",0),x.get("notional_usd",0),x.get("leverage",LEV),x["entry"],x["mark"],"posv" if x.get("roe_pct",0)>=0 else "negv",x.get("roe_pct",0),"posv" if x["unrealized_pnl"]>=0 else "negv",x["unrealized_pnl"],esc(x["headline"]),esc(x["symbol"])) for x in data["positions"]) or '<tr><td colspan=11>No open positions</td></tr>'
 trs="".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(esc(x["closed"]),esc(x["symbol"]),"LONG" if x["side"]>0 else "SHORT",round(x["pnl"],4),esc(x["reason"])) for x in data["trades"]) or '<tr><td colspan=5>No closed trades</td></tr>'
 src="".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(esc(k),"OK" if v.get("ok") else "ERROR",esc(v.get("last_check","")),esc(v.get("error",""))) for k,v in data["sources"].items())
 news="".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(esc(x["ts"]),esc(x["source"]),esc(x["symbol"]),esc(x["signal"]),esc(x["title"])) for x in data["news"][:12])
 return '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>PANDORA LIVE</title><style>body{font-family:system-ui;background:#080b10;color:#e8edf5;margin:24px}h1{margin:0}.muted{color:#8b98aa}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:18px 0}.grid b{background:#111722;padding:16px;border-radius:12px}table{width:100%%;border-collapse:collapse;background:#0e141e;margin-bottom:22px}td,th{padding:9px;border-bottom:1px solid #202938;text-align:left;font-size:13px}th{color:#91a2b8}.posv{color:#49d17d;font-weight:700}.negv{color:#ff6262;font-weight:700}a{color:#8bc4ff}</style></head><body><h1>PANDORA LIVE</h1><div class="muted">Paper engine · dashboard refresh 5s · last market poll %s</div>%s<h2>Open positions</h2><button onclick="closePos(null)">Close Everything</button><button onclick="location.reload()">Refresh</button><p id="actionResult"></p><table><tr><th>Token</th><th>Side</th><th>Margin</th><th>Position</th><th>Lev</th><th>Entry</th><th>Mark</th><th>ROI%%</th><th>P&L</th><th>Trigger</th><th>Action</th></tr>%s</table><h2>Closed trades</h2><table><tr><th>Closed</th><th>Token</th><th>Side</th><th>PnL</th><th>Reason</th></tr>%s</table><h2>Sources</h2><table><tr><th>Source</th><th>Status</th><th>Checked</th><th>Error</th></tr>%s</table><h2>Latest news</h2><table><tr><th>Time</th><th>Source</th><th>Token</th><th>Raw signal</th><th>Headline</th></tr>%s</table><p>Errors: %s · Last error: %s</p><p><a href="/api/dashboard">JSON dashboard</a> · <a href="/features">Features</a> · <a href="/trades">Trades</a> · <a href="/news">News</a></p><script>let closing=false;setInterval(()=>{if(!closing&&document.visibilityState==="visible")location.reload()},5000);async function closePos(sym){if(closing||!confirm(sym?"Close "+sym+"?":"Close ALL positions?"))return;closing=true;const status=document.getElementById("actionResult");status.textContent="Processing close request...";try{const r=await fetch("/api/positions/close",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify(sym?{symbol:sym}:{all:true})});const result=await r.json();status.textContent=r.ok?"Close confirmed: "+JSON.stringify(result):"Close failed ("+r.status+"): "+JSON.stringify(result);if(r.ok){location.reload();return}}catch(e){status.textContent="Close request failed: "+String(e)}finally{closing=false}}</script></body></html>'''%(esc(data["last_poll"]),cards,pos,trs,src,news,data["errors"],esc(data["last_error"]))


def manual_close(symbol=None):
 with LOCK:
  targets=list(S["positions"]) if symbol is None else [symbol]
  results=[]
  for sym in targets:
   pos=S["positions"].get(sym)
   if not pos:
    results.append({"symbol":sym,"ok":False,"error":"position_not_found"});continue
   price=S.get("_prices",{}).get(sym) or pos.get("last_price")
   if not price:
    results.append({"symbol":sym,"ok":False,"error":"price_unavailable"});continue
   result=STORE.close(sym,pos,price,"manual_close_all" if symbol is None else "manual_close")
   if result is None:
    results.append({"symbol":sym,"ok":False,"error":"close_not_committed"});continue
   S["equity"]=float(result["equity"]);S["realized_pnl"]=float(result["realized_pnl"])
   S["trades"]+=1
   del S["positions"][sym]
   results.append({"symbol":sym,"ok":True,"price":price,"pnl":result["pnl"]})
  return {"ok":all(x["ok"] for x in results),"results":results}

class Handler(BaseHTTPRequestHandler):
 def do_POST(self):
  path=self.path.split("?")[0]
  if path!="/api/positions/close":
   self.send_error(404);return
  secret=os.getenv("PANDORA_CONTROL_TOKEN","").strip()
  auth=self.headers.get("Authorization","")
  cookie=self.headers.get("Cookie","")
  cookie_token=next((part.strip().split("=",1)[1] for part in cookie.split(";") if part.strip().startswith("pandora_access=")),"")
  if not secret or not (secrets.compare_digest(auth,"Bearer "+secret) or secrets.compare_digest(cookie_token,secret)):
   self.send_error(401);return
  try:
   length=int(self.headers.get("Content-Length","0"))
   if length<1 or length>1024:raise ValueError("invalid body")
   payload=json.loads(self.rfile.read(length))
   symbol=payload.get("symbol")
   if symbol is not None and (not isinstance(symbol,str) or not re.fullmatch(r"[A-Z0-9]{2,15}",symbol)):raise ValueError("invalid symbol")
   if symbol is None and payload.get("all") is not True:raise ValueError("explicit all required")
   result=manual_close(symbol)
   body=json.dumps(result).encode()
   self.send_response(200 if result["ok"] else 409)
  except (ValueError,TypeError):
   body=b'{"ok":false,"error":"bad_request"}'
   self.send_response(400)
  except Exception:
   body=b'{"ok":false,"error":"close_failed"}'
   self.send_response(500)
  self.send_header("Content-Type","application/json")
  self.send_header("Cache-Control","no-store")
  self.send_header("Content-Length",str(len(body)))
  self.end_headers();self.wfile.write(body)
 def do_HEAD(self):
  self.send_response(200);self.end_headers()
 def do_GET(self):
  path=self.path.split("?")[0]
  if path=="/" and "access" in urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query):
   supplied=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("access",[""])[0]
   secret=os.getenv("PANDORA_CONTROL_TOKEN","").strip()
   if not secret or not secrets.compare_digest(supplied,secret):
    self.send_error(403);return
   self.send_response(303)
   self.send_header("Location","/")
   self.send_header("Set-Cookie","pandora_access="+secret+"; HttpOnly; Secure; SameSite=Strict; Path=/")
   self.send_header("Cache-Control","no-store")
   self.send_header("Referrer-Policy","no-referrer")
   self.end_headers();return
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
  self.send_response(200);self.send_header("Content-Type",ctype);self.send_header("Cache-Control","no-store");self.send_header("Access-Control-Allow-Origin","*");self.send_header("Content-Length",str(len(body)));self.end_headers()
  try:self.wfile.write(body)
  except (BrokenPipeError,ConnectionResetError):pass

def health_state():
 stamp=time.time()
 age=stamp-S.get("_last_poll_epoch",0) if S.get("_last_poll_epoch") else None
 heartbeat=stamp-S.get("_market_heartbeat",stamp)
 checkpoint=S.get("last_checkpoint")
 checkpoint_age=stamp-datetime.datetime.fromisoformat(checkpoint).timestamp() if checkpoint else None
 coordinator_age=stamp-S.get("_coordinator_heartbeat",stamp)
 healthy=not SHUTDOWN.is_set() and heartbeat<45 and coordinator_age<45
 ready=healthy and S["engine_active"] and age is not None and age<10 and checkpoint_age is not None and checkpoint_age<15
 sources=dict(S.get("sources",{}))
 social={k:v for k,v in sources.items() if k.startswith(("XFree:","XFilteredStream","XMonitor","TruthStream","TruthDirect:","TruthSocialPublic"))}
 unavailable=[k for k,v in social.items() if not v.get("ok")]
 return {"healthy":healthy,"risk_ready":ready,"news_sources_total":len(sources),"news_sources_failed":sum(not v.get("ok",False) for v in sources.values()),"social_sources_failed":unavailable,"guest_x_realtime_verified":False,"news_24h_guaranteed":False,"engine_active":S["engine_active"],
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
 targets=[engine_coordinator,market,market_metadata,telemetry,xnews,adapt,free_x_realtime,x_list_realtime,free_truth_realtime,truth_stream_realtime,x_filtered_stream,dashboard_cache_loop,operations_diagnostics]
 targets += ([lambda:social_reader("x")] if os.getenv("X_SESSION_COOKIES","").strip() else [])
 targets += [lambda:social_reader("truth")] if os.getenv("TRUTHSOCIAL_TOKEN","").strip() else []
 workers=[threading.Thread(target=t,daemon=True,name=t.__name__) for t in targets]
 workers += [threading.Thread(target=news_feed,args=(name,url),daemon=True,name="feed:"+name) for name,url in FEEDS.items()]
 workers += [threading.Thread(target=public_social_reader,args=("x",handle),daemon=True,name="public-x:"+handle) for handle in WATCH] if os.getenv("ENABLE_PUBLIC_X_HTML","0")=="1" else []

 for worker in workers:worker.start()
 try:server.serve_forever()
 finally:
  SHUTDOWN.set();server.server_close()
  for worker in workers:worker.join(timeout=0.5)
  try:STORE.release()
  except Exception:pass
