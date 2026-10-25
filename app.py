import os,json,time,threading,urllib.request,urllib.parse,sqlite3,datetime,xml.etree.ElementTree as ET,re,hashlib,subprocess,html as htmlmod
import sqlite3,math,email.utils,secrets,signal,copy,concurrent.futures
import websocket
import psycopg
from curl_cffi import requests as curl_requests
from psycopg.rows import dict_row
from risk import evaluate_exit, risk_state
from engine_store import EngineStore, LeaseLost
from entry_guards import freshness, publication_epoch
from social_scrapers import poll as social_poll, SourceUnavailable
from truthbrush import Api as TruthApi
from public_social import read as public_social_read
from x_guest import read as guest_x_read
from x_list import fetch_list as x_list_fetch
from x_page import fetch as free_x_page_fetch
from realtime_free import fetch_x as free_x_fetch, fetch_x_search as free_x_search_fetch, fetch_x_fixupx as free_x_fixupx_fetch, fetch_x_lookup as free_x_lookup_fetch, fetch_x_embed as free_x_embed_fetch, fetch_x_nitter as free_x_nitter_fetch, fetch_x_syndication as free_x_syndication_fetch, fetch_x_syndication as free_x_syn_fetch, fetch_x_vx as free_x_vx_fetch, fetch_truth as free_truth_fetch, fetch_truth_activitypub as free_truth_ap_fetch, fetch_truth_rss as free_truth_rss_fetch, fetch_trump_archive as free_trump_archive_fetch
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
 "critical":["elonmusk","realDonaldTrump","POTUS","WhiteHouse","SECGov","federalreserve","BlackRock","Fidelity","ARKInvest","Grayscale"]
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
API=os.getenv("HYPERLIQUID_INFO_API","https://api.hyperliquid.xyz/info").strip() or "https://api.hyperliquid.xyz/info"
DB="/tmp/pandora.sqlite3"
START=time.time()
S={"adaptive":{"samples":0,"changed":False},"mode":"PAPER_ONLY","orders_enabled":False,"last_poll":None,"market_count":0,"news_seen":0,"trades":0,"errors":0,"last_error":None,"sources":{},"positions":{},"equity":100.0,"realized_pnl":0.0,"pump_positions":{},"pump_equity":100.0,"pump_realized_pnl":0.0,"pump_trades":0,"whale_positions":{},"whale_equity":100.0,"whale_realized_pnl":0.0,"whale_trades":0}
LOCK=threading.RLock()
SHUTDOWN=threading.Event()
TRADE_LEVERAGE=max(1.0,min(50.0,float(os.getenv("TRADE_LEVERAGE","25"))))
TRADE_MARGIN_FRACTION=max(0.01,min(0.25,float(os.getenv("TRADE_MARGIN_FRACTION","0.10"))))
PAPER_TOPUP_STEP=max(10.0,float(os.getenv("PAPER_TOPUP_STEP","100")))
NEWS_MAX_AGE_SECONDS=float(os.getenv("NEWS_MAX_AGE_SECONDS","120"))
NEWS_POLL_SECONDS=float(os.getenv("NEWS_POLL_SECONDS","15"))
WHITEHOUSE_POLL_SECONDS=max(10.0,float(os.getenv("WHITEHOUSE_POLL_SECONDS","15")))
PUMP_SCAN_SECONDS=max(1.0,float(os.getenv("PUMP_SCAN_SECONDS","2")))
MARKET_METADATA_SECONDS=max(3.0,float(os.getenv("MARKET_METADATA_SECONDS","5")))
MICRO_ANALYSIS_THREADS=max(1,min(10,int(os.getenv("MICRO_ANALYSIS_THREADS","10"))))
LIQ_WHALE_SCAN_SECONDS=max(3.0,float(os.getenv("LIQ_WHALE_SCAN_SECONDS","3")))
LIQ_WHALE_MAX_DISTANCE_PCT=max(0.5,float(os.getenv("LIQ_WHALE_MAX_DISTANCE_PCT","1.5")))
LIQ_WHALE_MIN_USD=max(100000.0,float(os.getenv("LIQ_WHALE_MIN_USD","2000000")))
LIQ_WHALE_SCORE_MIN=max(50.0,float(os.getenv("LIQ_WHALE_SCORE_MIN","76")))
LIQ_WHALE_MAX_POSITION_AGE_SECONDS=max(30.0,float(os.getenv("LIQ_WHALE_MAX_POSITION_AGE_SECONDS","180")))
LIQ_WHALE_MIN_BY_SYMBOL={"BTC":5_000_000.0,"ETH":3_000_000.0,"SOL":2_000_000.0}
LIQ_WHALE_BASE_ENTRY_DISTANCE={"BTC":0.45,"ETH":0.60,"SOL":0.75}
LIQ_WHALE_LEV=TRADE_LEVERAGE
LIQ_WHALE_MARGIN_FRACTION=TRADE_MARGIN_FRACTION
LIQ_WHALE_SYMBOLS={"BTC","ETH","SOL"}
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
 "FTCrypto":"https://www.ft.com/crypto?format=rss",
 "TheBlockRSS":"https://www.theblock.co/rss.xml",
 "BitcoinMagazineRSS":"https://bitcoinmagazine.com/feed",
 "TheDefiant":"https://thedefiant.io/feed/",
 "Protos":"https://protos.com/feed",
})
SEARCH_INDEX_FEEDS={
 "GoogleNewsCrypto","GoogleNewsMarkets","TruthSocialSearch","CoinSharesResearch","BitwiseResearch","ARKResearch","GrayscaleResearch",
 "GoogleNewsBreaking","GoogleNewsGeopolitics","GoogleNewsOil","GoogleNewsChina","GoogleNewsMacro","GoogleNewsCryptoHack","GoogleNewsCryptoPolicy","GoogleNewsTokenEvents"
}
RESEARCH_PAGES={
 "CoinSharesResearch":"https://coinshares.com/insights/research-data/",
 "BitwiseResearch":"https://bitwiseinvestments.com/crypto-market-insights"
}
# Credential-free coverage of public X account mentions, with indexer delay.
# These are not authenticated X timelines; source status reports that distinction.
for _i in range(0,len(WATCH),4):
 _group=WATCH[_i:_i+4]
 FEEDS["XIndex:"+",".join(_group)]="https://news.google.com/rss/search?"+urllib.parse.urlencode({
  "q":"("+" OR ".join("site:x.com/"+h for h in _group)+")",
  "hl":"en-US","gl":"US","ceid":"US:en"
 })
POS=("pump","pumping","surge","surges","approve","approved","approval","partnership","listing","adoption","buyback","breakout","bullish","launch","etf approved","rally","rallies","rebound","rebounds","record high","inflows","net inflow","gains","jumps","soars","upside")
NEG=("dump","dumping","hack","hacked","exploit","lawsuit","delist","delisted","ban","banned","fraud","selloff","sell-off","bearish","crash","crashes","stolen","outflows","net outflow","falls","drops","slips","plunges","tumbles","declines")
# Symbols that are also ordinary English words/acronyms. Never map them from a bare word.
# They require an explicit crypto form/name so headlines like "not", "people", "move", "etc" cannot create trades.
AMBIGUOUS_SYMBOLS={"NOT","PEOPLE","MOVE","ETC","TRUMP","MELANIA"}
EXPLICIT_TOKEN_PATTERNS={
 "NOT":(r"\$NOT\b",r"\bNOTUSDT\b",r"\bNOTCOIN\b",r"\bNOT TOKEN\b"),
 "PEOPLE":(r"\$PEOPLE\b",r"\bPEOPLEUSDT\b",r"\bCONSTITUTIONDAO\b",r"\bPEOPLE TOKEN\b"),
 "MOVE":(r"\$MOVE\b",r"\bMOVEUSDT\b",r"\bMOVEMENT(?: NETWORK)?\b",r"\bMOVE TOKEN\b"),
 "ETC":(r"\$ETC\b",r"\bETCUSDT\b",r"\bETHEREUM CLASSIC\b",r"\bETC TOKEN\b"),
 "TRUMP":(r"\$TRUMP\b",r"\bTRUMPUSDT\b",r"\bTRUMP TOKEN\b",r"\bTRUMP MEMECOIN\b",r"\bOFFICIAL TRUMP\b.{0,20}\bTOKEN\b"),
 "MELANIA":(r"\$MELANIA\b",r"\bMELANIAUSDT\b",r"\bMELANIA TOKEN\b",r"\bMELANIA MEMECOIN\b")
}
# Source priors are experimental metadata for the one-week PAPER_ONLY study.
# They are logged and gently affect confidence/eligibility, but can never reverse news direction.
SOURCE_WEIGHTS={
 "FedOfficial":1.00,"SECOfficial":1.00,"CFTCOfficial":1.00,"DOJNews":0.95,"WhiteHouseOfficial":1.00,
 "TruthSocialPublic":0.95,"XOfficial":0.90,"TruthArchive":0.80,
 "CoinSharesResearch":0.90,"BitwiseResearch":0.88,"ARKResearch":0.86,"GrayscaleResearch":0.88,
 "CoinDesk":0.84,"Decrypt":0.78,"Cointelegraph":0.74,"FTCrypto":0.88,"TheBlockRSS":0.84,"BitcoinMagazineRSS":0.76,"TheDefiant":0.74,"Protos":0.72,
 "GoogleNewsMarkets":0.60,"GoogleNewsCrypto":0.55,"TruthSocialSearch":0.55
}
NON_MARKET_PATTERNS=(
 r"\\b(?:giveaway|sweepstakes|contest|competition)\\b",
 r"\\b(?:winner|winners|won|prize|award|awards)\\b",
 r"\\b(?:congratulations|congrats)\\b",
 r"\\b(?:tickets?|merch|merchandise)\\b",
 r"\\b(?:podcast|webinar|meetup)\\b",
)
def is_non_market_news(title):
 lo=title.lower()
 # Promotional/community posts are journalled but can never open/reverse a trade.
 return any(re.search(p,lo,re.I) for p in NON_MARKET_PATTERNS)

LIQUIDATION_NEWS_PATTERNS=(
 r"\bliquidat(?:e|ed|es|ing|ion|ions)\b",
 r"\bliq(?:uidation)?\s+(?:level|levels|price|prices|cluster|clusters|zone|zones)\b",
 r"\b(?:longs?|shorts?)\s+(?:could|may|might|set to|at risk to|risk being)?\s*be?\s*liquidat",
 r"\bforced\s+liquidation\b",
 r"\bliquidation\s+cascade\b",
)
def is_liquidation_news(title):
 # Liquidation headlines are research evidence only. Trading responsibility
 # belongs exclusively to WhaleLiquidationScanner, which reads live position,
 # distance, order-flow and book data rather than reacting to a reposted headline.
 return any(re.search(p,title,re.I) for p in LIQUIDATION_NEWS_PATTERNS)

MARKET_WIDE_TERMS=("war","airstrike","missile","invasion","sanctions","tariff","trade war","blockade","suez","hormuz","oil","opec","recession","government shutdown","debt ceiling","ceasefire","truce","peace deal","rate cut","rate hike","fomc","cpi","pce","jobs report","nonfarm payrolls","china","taiwan")
EVENT_RULES=[
 ("RISK_ON_DEESCALATION",1,("ceasefire","truce","peace deal","peace agreement","de-escalation","sanctions lifted","tariffs reduced","tariff relief")),
 ("MONETARY_EASING",1,("rate cut","cuts rates","dovish pivot","quantitative easing")),
 ("RISK_OFF_GEOPOLITICS",-1,("airstrike","missile strike","military strike","major operations","military operations","resuming operations","resume operations","attack","attacks","strikes","invasion","war escalates","escalation","escalates","blockade","sanctions announced","sanctions tightened","tariffs imposed","tariff hike","government shutdown","sovereign default")),
 ("MONETARY_TIGHTENING",-1,("rate hike","raises rates","hawkish pivot","higher for longer")),
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
PRICE_ACTION_ONLY_TERMS=("surge","surges","soars","jumps","rally","rallies","gains","falls","drops","slips","plunges","tumbles","declines","selloff","sell-off","crashes","crash")
CAUSAL_EVENT_TYPES={"RISK_ON_DEESCALATION","MONETARY_EASING","RISK_OFF_GEOPOLITICS","MONETARY_TIGHTENING","ETF_APPROVAL","LISTING","BUYBACK","ADOPTION","HACK","DELISTING","ENFORCEMENT","FUND_OUTFLOW","FUND_INFLOW"}
def is_price_action_only_news(title,event_type):
 lo=title.lower()
 return event_type not in CAUSAL_EVENT_TYPES and any(term in lo for term in PRICE_ACTION_ONLY_TERMS)
def source_weight(source):
 if source.startswith("XIndex:"):base=0.40
 elif source.startswith("XOfficial:"):base=0.90
 elif source.startswith("TruthSocialPublic"):base=0.95
 else:base=float(SOURCE_WEIGHTS.get(source,0.50))
 learned=S.get("adaptive",{}).get("source_multipliers",{}) if S.get("mode")=="PAPER_ONLY" else {}
 return max(0.20,min(1.00,base*float(learned.get(source,1.0))))
def source_freshness_window(source):
 if source.startswith("XOfficial:") or source.startswith("TruthSocialPublic"):
  return min(35.0,NEWS_MAX_AGE_SECONDS)
 if source in ("FedOfficial","SECOfficial","CFTCOfficial","DOJNews"):
  return min(90.0,NEWS_MAX_AGE_SECONDS)
 return NEWS_MAX_AGE_SECONDS

STOP_ROE=-999.0;TAKE_ROE=0.20;LEV=25.0;MARGIN_FRACTION=0.10;FEE=0.00045;LOCK_TRIGGER_ROE=0.10;LOCK_ROE=0.075;PAPER_RESET=100.0;MIN_EXIT_ROE=0.075;TRAIL_ARM_ROE=0.12
PUMP_LEV=TRADE_LEVERAGE;PUMP_MARGIN_FRACTION=TRADE_MARGIN_FRACTION;PUMP_MAX_POSITIONS=10;PUMP_STOP_ROE=-0.06;PUMP_TAKE_ROE=0.14;PUMP_TRAIL_ARM_ROE=0.09;PUMP_TRAIL_GAP_ROE=0.035;PUMP_MAX_HOLD_SECONDS=900
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def pg():
 # Neon transaction pooling rejects statement_timeout in startup options.
 return psycopg.connect(os.environ["DATABASE_URL"],autocommit=True,row_factory=dict_row,connect_timeout=5)
STORE=EngineStore(pg,FEE,PAPER_RESET)
def pinit():
 with pg() as c:
  c.execute("create table if not exists account_state (id integer primary key, equity double precision not null, realized_pnl double precision not null, updated_at text not null)")
  c.execute("alter table account_state add column if not exists contributed_capital double precision not null default 100")
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
  c.execute("alter table trade_history add column if not exists strategy text")
  c.execute("alter table trade_history add column if not exists score double precision")
  c.execute("alter table trade_history add column if not exists features jsonb")
  c.execute("update trade_history set strategy='news' where strategy is null")
  c.execute("create table if not exists audit_journal (id bigserial primary key, recorded_at text not null, event_id text, kind text not null, payload jsonb not null)")
  c.execute("create table if not exists pump_signal_journal (id text primary key, ts text not null, symbol text, side integer, score double precision, action text, features jsonb)")
  c.execute("create table if not exists bad_signal_feedback (id bigserial primary key, recorded_at text not null, event_id text, symbol text, headline text, reason text, payload jsonb)")
  c.execute("create table if not exists operator_actions (action_id text primary key, completed_at text not null, payload jsonb not null)")
  c.execute("create table if not exists pump_positions (symbol text primary key, side integer not null, entry double precision not null, notional double precision not null, margin double precision not null, leverage double precision not null, opened text not null, opened_epoch double precision not null, peak_roe double precision not null default 0, score double precision not null default 0, features jsonb not null default '{}'::jsonb)")
  c.execute("create table if not exists pump_trade_history (id bigserial primary key, opened text, closed text, symbol text, side integer, entry double precision, exit double precision, pnl double precision, reason text, score double precision, features jsonb)")
  c.execute("create table if not exists learning_snapshots (id bigserial primary key, recorded_at text not null, samples integer not null, payload jsonb not null)")
  c.execute("create table if not exists whale_liq_positions (symbol text primary key, side integer not null, entry double precision not null, notional double precision not null, margin double precision not null, leverage double precision not null, opened text not null, opened_epoch double precision not null, peak_roe double precision not null default 0, score double precision not null default 0, features jsonb not null default '{}'::jsonb)")
  c.execute("create table if not exists whale_liq_trade_history (id bigserial primary key, opened text, closed text, symbol text, side integer, entry double precision, exit double precision, pnl double precision, reason text, score double precision, features jsonb)")
  c.execute("create table if not exists whale_liq_signal_journal (id text primary key, ts text not null, symbol text, side integer, score double precision, action text, features jsonb)")
  c.execute("create table if not exists account_capacity_snapshots (id bigserial primary key, ts text not null, equity double precision not null, contributed_capital double precision not null, used_margin double precision not null, free_margin double precision not null, margin_utilization_pct double precision not null, news_positions integer not null, pump_positions integer not null, whale_positions integer not null, total_positions integer not null, entry_margin_fraction double precision not null)")

  c.execute("create index if not exists audit_journal_event_idx on audit_journal(event_id,id)")
  row=c.execute("select equity,realized_pnl,contributed_capital from account_state where id=1").fetchone()
  if row:
   S["equity"]=float(row["equity"]);S["realized_pnl"]=float(row["realized_pnl"]);S["contributed_capital"]=float(row["contributed_capital"] or PAPER_RESET)
  else:
   c.execute("insert into account_state(id,equity,realized_pnl,updated_at,contributed_capital) values(1,%s,%s,%s,%s)",(S["equity"],S["realized_pnl"],now(),PAPER_RESET))
   S["contributed_capital"]=PAPER_RESET
  S["news_seen"]=c.execute("select count(*) as n from news_events").fetchone()["n"]
  S["trades"]=c.execute("select count(*) as n from trade_history").fetchone()["n"]
  S["pump_equity"]=S["equity"];S["pump_realized_pnl"]=S["realized_pnl"]
  S["pump_trades"]=c.execute("select count(*) as n from trade_history where strategy='pump_dump'").fetchone()["n"]
  ppositions={}
  for r in c.execute("select * from pump_positions").fetchall():
   ppositions[r["symbol"]]={"side":int(r["side"]),"entry":float(r["entry"]),"notional":float(r["notional"]),"margin":float(r["margin"]),"leverage":float(r["leverage"]),"opened":r["opened"],"t":float(r["opened_epoch"]),"peak_roe":float(r["peak_roe"] or 0),"score":float(r["score"] or 0),"features":r["features"] or {}}
  S["pump_positions"]=ppositions
  S["whale_equity"]=S["equity"];S["whale_realized_pnl"]=S["realized_pnl"]
  S["whale_trades"]=c.execute("select count(*) as n from trade_history where strategy='whale_liquidation'").fetchone()["n"]
  wpositions={}
  for r in c.execute("select * from whale_liq_positions").fetchall():
   wpositions[r["symbol"]]={"side":int(r["side"]),"entry":float(r["entry"]),"notional":float(r["notional"]),"margin":float(r["margin"]),"leverage":float(r["leverage"]),"opened":r["opened"],"t":float(r["opened_epoch"]),"peak_roe":float(r["peak_roe"] or 0),"score":float(r["score"] or 0),"features":r["features"] or {}}
  S["whale_positions"]=wpositions
 STORE.migrate()
 _,positions=STORE.load(recover_legacy=False)
 S["positions"]=positions
def journal(kind,event_id,payload):
 with pg() as c:c.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,%s,%s,%s::jsonb)",(now(),event_id,kind,json.dumps(payload,default=str)))
def persistent_trades(limit=100):
 with pg() as c:return c.execute("select * from trade_history order by id desc limit %s",(limit,)).fetchall()
def build_learning_snapshot():
 # Statistical PAPER learning. It records outcomes broadly, but automatic
 # adaptation stays intentionally bounded to NEWS source confidence.
 with pg() as c:
  rows=c.execute("""select n.source,count(*) as n,
      sum(case when t.pnl>0 then 1 else 0 end) as wins,
      avg(t.pnl) as avg_pnl,sum(t.pnl) as total_pnl
    from trade_history t join news_events n on n.id=t.event_id
    where t.event_id is not null group by n.source order by count(*) desc""").fetchall()
  strategy=c.execute("""select coalesce(strategy,'news') as strategy,count(*) as n,
      sum(case when pnl>0 then 1 else 0 end) as wins,avg(pnl) as avg_pnl,sum(pnl) as total_pnl
    from trade_history group by 1 order by 1""").fetchall()
  event_types=c.execute("""select coalesce(f.features->>'event_type','unknown') as event_type,count(*) as n,
      sum(case when t.pnl>0 then 1 else 0 end) as wins,avg(t.pnl) as avg_pnl,sum(t.pnl) as total_pnl
    from trade_history t join event_features f on f.id=t.event_id
    where t.event_id is not null group by 1 order by n desc""").fetchall()
  pump=c.execute("""select case when score<84 then '<84' when score<90 then '84-90' else '90+' end as bucket,count(*) as n,
      sum(case when pnl>0 then 1 else 0 end) as wins,avg(pnl) as avg_pnl,sum(pnl) as total_pnl
    from trade_history where strategy='pump_dump' group by 1 order by 1""").fetchall()
  whale=c.execute("""select case when score<76 then '<76' when score<85 then '76-85' else '85+' end as bucket,count(*) as n,
      sum(case when pnl>0 then 1 else 0 end) as wins,avg(pnl) as avg_pnl,sum(pnl) as total_pnl,
      avg(nullif(features->>'distance_pct','')::double precision) as avg_distance_pct,
      avg(nullif(features->>'liquidation_flow_to_depth','')::double precision) as avg_flow_to_depth
    from trade_history where strategy='whale_liquidation' group by 1 order by 1""").fetchall()
  funding=c.execute("""select count(*) as topups,
      coalesce(sum((payload->>'amount')::double precision),0) as amount
    from audit_journal where kind='paper_capital_topup'""").fetchone()
  capacity=c.execute("""select count(*) as samples,
      coalesce(max(total_positions),0) as max_positions,
      coalesce(max(margin_utilization_pct),0) as max_utilization_pct,
      coalesce(avg(margin_utilization_pct),0) as avg_utilization_pct,
      coalesce(percentile_cont(0.95) within group(order by margin_utilization_pct),0) as p95_utilization_pct,
      coalesce(max(used_margin),0) as peak_used_margin,
      coalesce(max(contributed_capital),100) as max_contributed_capital
    from account_capacity_snapshots""").fetchone()
 multipliers={};source_stats={};total_samples=0
 for r in rows:
  n=int(r["n"] or 0);wins=int(r["wins"] or 0);avg=float(r["avg_pnl"] or 0);total=float(r["total_pnl"] or 0)
  total_samples+=n;wr=(wins/n) if n else 0.0;mult=1.0
  if n>=10:
   edge=(wr-0.5)*0.20
   if avg>0:edge+=0.02
   elif avg<0:edge-=0.02
   mult=max(0.90,min(1.10,1.0+edge))
  multipliers[str(r["source"])]=round(mult,4)
  source_stats[str(r["source"])]={"samples":n,"wins":wins,"win_rate":round(wr,4),"avg_pnl":avg,"total_pnl":total,"multiplier":round(mult,4)}
 total_samples=sum(int(x["n"] or 0) for x in strategy)
 payload={"mode":"PAPER_ONLY","source_multipliers":multipliers,"source_stats":source_stats,
          "strategy_stats":[dict(x) for x in strategy],"event_type_stats":[dict(x) for x in event_types],
          "pump_score_buckets":[dict(x) for x in pump],"whale_score_buckets":[dict(x) for x in whale],
          "funding":{"topups":int(funding["topups"] or 0),"amount":float(funding["amount"] or 0)},
          "capacity":{"samples":int(capacity["samples"] or 0),"max_positions":int(capacity["max_positions"] or 0),
            "max_utilization_pct":float(capacity["max_utilization_pct"] or 0),"avg_utilization_pct":float(capacity["avg_utilization_pct"] or 0),
            "p95_utilization_pct":float(capacity["p95_utilization_pct"] or 0),"peak_used_margin":float(capacity["peak_used_margin"] or 0),
            "max_contributed_capital":float(capacity["max_contributed_capital"] or PAPER_RESET),
            "current_margin_fraction_pct":TRADE_MARGIN_FRACTION*100.0,
            "observed_no_topup_fraction_ceiling_pct":round(90.0/max(1,int(capacity["max_positions"] or 1)),2)},
          "generated_at":now(),"policy":"conservative_news_source_reweight_n10_other_strategies_observation_only"}
 return total_samples,payload

def save_learning_snapshot():
 samples,payload=build_learning_snapshot()
 with pg() as c:
  c.execute("insert into learning_snapshots(recorded_at,samples,payload) values(%s,%s,%s::jsonb)",
            (now(),samples,json.dumps(payload,default=str)))
 with LOCK:S["adaptive"]={"samples":samples,"changed":True,**payload}
 journal("learning_snapshot",None,{"samples":samples,"source_count":len(payload["source_stats"]),
         "pump_buckets":len(payload["pump_score_buckets"]),"whale_buckets":len(payload["whale_score_buckets"]),
         "strategy_count":len(payload["strategy_stats"]),"policy":payload["policy"]})
 return payload

def load_latest_learning():
 try:
  with pg() as c:
   row=c.execute("select samples,payload from learning_snapshots order by id desc limit 1").fetchone()
  if row:
   with LOCK:S["adaptive"]={"samples":int(row["samples"]),**(row["payload"] or {})}
 except Exception:pass

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
def save_capacity_snapshot():
 with LOCK:
  equity=float(S.get("equity",0) or 0);contributed=float(S.get("contributed_capital",PAPER_RESET) or PAPER_RESET)
  used=float(_shared_used_margin());free=max(0.0,equity-used)
  news_n=len(S.get("positions",{}));pump_n=len(S.get("pump_positions",{}));whale_n=len(S.get("whale_positions",{}))
  util=(used/equity*100.0) if equity>0 else 0.0
 with pg() as c:c.execute("""insert into account_capacity_snapshots
  (ts,equity,contributed_capital,used_margin,free_margin,margin_utilization_pct,news_positions,pump_positions,whale_positions,total_positions,entry_margin_fraction)
  values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
  (now(),equity,contributed,used,free,util,news_n,pump_n,whale_n,news_n+pump_n+whale_n,TRADE_MARGIN_FRACTION))
def save_market_context(ts,symbol,price,context):
 with pg() as c:c.execute("insert into market_context_snapshots(ts,symbol,price,context) values(%s,%s,%s,%s::jsonb)",(ts,symbol,price,json.dumps(context)))
def export_rows(kind,after,limit):
 columns={"journal":("audit_journal","id"),"news":("news_events","id"),
          "features":("event_features","id"),"trades":("trade_history","id"),
          "positions":("open_positions","symbol"),"pump_signals":("pump_signal_journal","id"),
          "pump_trades":("pump_trade_history","id"),"learning":("learning_snapshots","id"),
          "whale_signals":("whale_liq_signal_journal","id"),"whale_trades":("whale_liq_trade_history","id"),
          "capacity":("account_capacity_snapshots","id")}
 if kind not in columns:raise ValueError("Unsupported export kind")
 table,key=columns[kind]
 cursor=int(after) if kind in ("journal","trades","pump_trades","learning","whale_trades","capacity") else after
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

def operator_one_shot_actions():
 action_id=os.getenv("PANDORA_ONE_SHOT_ACTION_ID","").strip()
 symbol=os.getenv("PANDORA_ONE_SHOT_CLOSE_SYMBOL","").strip().upper()
 close_reason=os.getenv("PANDORA_ONE_SHOT_CLOSE_REASON","operator_one_shot_close").strip() or "operator_one_shot_close"
 feedback_reason=os.getenv("PANDORA_ONE_SHOT_FEEDBACK_REASON","").strip()
 if not action_id or not symbol:return
 while not SHUTDOWN.is_set():
  try:
   with pg() as c:
    if c.execute("select 1 from operator_actions where action_id=%s",(action_id,)).fetchone():return
   with LOCK:
    active=S["engine_active"];pos=copy.deepcopy(S["positions"].get(symbol));price=S.get("_prices",{}).get(symbol)
   if not active or not pos or not price:
    SHUTDOWN.wait(1);continue
   feedback={"action_id":action_id,"symbol":symbol,"headline":pos.get("headline"),"event_id":pos.get("event_id"),
             "entry":pos.get("entry"),"side":pos.get("side"),"mark":price,"reason":close_reason}
   if feedback_reason:
    with pg() as c:
     c.execute("insert into bad_signal_feedback(recorded_at,event_id,symbol,headline,reason,payload) values(%s,%s,%s,%s,%s,%s::jsonb)",
      (now(),pos.get("event_id"),symbol,pos.get("headline"),feedback_reason,json.dumps(feedback)))
   result=manual_close(symbol,close_reason)
   with pg() as c:
    c.execute("insert into operator_actions(action_id,completed_at,payload) values(%s,%s,%s::jsonb) on conflict(action_id) do nothing",
      (action_id,now(),json.dumps({"feedback":feedback,"close_result":result})))
   journal("operator_position_closed",pos.get("event_id"),{"feedback":feedback,"close_result":result})
   return
  except Exception as exc:
   S["last_error"]="operator_action: "+str(exc)[:160]
   SHUTDOWN.wait(2)


def _shared_used_margin():
 total=0.0
 for book in (S.get("positions",{}),S.get("pump_positions",{}),S.get("whale_positions",{})):
  for p in book.values():
   lev=max(1.0,float(p.get("leverage",TRADE_LEVERAGE)))
   total+=float(p.get("margin",float(p.get("notional",0))/lev))
 total+=sum(float(x or 0) for x in S.get("_entry_reservations",{}).values())
 return total

def _symbol_open_anywhere(symbol):
 return symbol in S.get("positions",{}) or symbol in S.get("pump_positions",{}) or symbol in S.get("whale_positions",{})

def _reserve_shared_entry(symbol):
 with LOCK:
  reservations=S.setdefault("_entry_reservations",{})
  if _symbol_open_anywhere(symbol) or symbol in reservations:
   return False,0.0,"symbol_already_open_shared_account",0.0
  reservations[symbol]=0.0
  try:
   while True:
    equity=float(S["equity"])
    margin=max(0.01,max(0.0,equity)*TRADE_MARGIN_FRACTION)
    used=_shared_used_margin()
    free=max(0.0,equity-used)
    if equity>0 and free+1e-9>=margin:
     reservations[symbol]=margin
     return True,margin,None,free
    topup=PAPER_TOPUP_STEP
    with pg() as db:
     with db.transaction():
      STORE.fence(db)
      row=db.execute("""update account_state
        set equity=equity+%s,contributed_capital=contributed_capital+%s,updated_at=%s
        where id=1 returning equity,realized_pnl,contributed_capital""",
        (topup,topup,now())).fetchone()
      db.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'paper_capital_topup',%s::jsonb)",
        (now(),json.dumps({"amount":topup,"reason":"insufficient_free_margin","symbol":symbol,
          "used_margin_before":used,"free_margin_before":free,"target_margin_before":margin,
          "equity_after":float(row["equity"]),"contributed_capital_after":float(row["contributed_capital"]),
          "current_margin_fraction_pct":TRADE_MARGIN_FRACTION*100.0,
          "open_positions_total":len(S.get("positions",{}))+len(S.get("pump_positions",{}))+len(S.get("whale_positions",{}))},default=str)))
    S["equity"]=float(row["equity"]);S["realized_pnl"]=float(row["realized_pnl"])
    S["contributed_capital"]=float(row["contributed_capital"])
  except Exception:
   reservations.pop(symbol,None)
   raise

def _release_shared_entry(symbol):
 with LOCK:S.setdefault("_entry_reservations",{}).pop(symbol,None)

def pump_open(symbol,side,price,score,features):
 if side not in (-1,1) or not price:return False
 with LOCK:
  if not S["engine_active"] or len(S["pump_positions"])>=3:return False
 reserved,margin,reason,free=_reserve_shared_entry(symbol)
 if not reserved:
  journal("entry_skipped",None,{"strategy":"pump_dump","symbol":symbol,"reason":reason,"free_margin":free})
  return False
 try:
  notional=margin*TRADE_LEVERAGE;opened=now();epoch=time.time()
  pos={"side":side,"entry":float(price),"notional":notional,"margin":margin,"leverage":TRADE_LEVERAGE,"opened":opened,"t":epoch,"peak_roe":0.0,"score":float(score),"features":features}
  with pg() as db:
   with db.transaction():
    STORE.fence(db)
    row=db.execute("""insert into pump_positions(symbol,side,entry,notional,margin,leverage,opened,opened_epoch,peak_roe,score,features)
     values(%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s::jsonb) on conflict(symbol) do nothing returning symbol""",
     (symbol,side,price,notional,margin,TRADE_LEVERAGE,opened,epoch,float(score),json.dumps(features,default=str))).fetchone()
    if not row:return False
    db.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'pump_trade_opened',%s::jsonb)",
     (now(),json.dumps({"strategy":"pump_dump","symbol":symbol,"side":side,"entry":price,"score":score,"margin":margin,"notional":notional,"leverage":TRADE_LEVERAGE},default=str)))
  with LOCK:S["pump_positions"][symbol]=pos
  return True
 finally:_release_shared_entry(symbol)

def pump_close(symbol,price,reason):
 with LOCK:pos=copy.deepcopy(S["pump_positions"].get(symbol))
 if not pos or not price:return None
 pnl=pos["notional"]*(float(price)/pos["entry"]-1)*pos["side"]-pos["notional"]*FEE*2
 with pg() as c:
  with c.transaction():
   STORE.fence(c)
   row=c.execute("delete from pump_positions where symbol=%s and opened=%s returning symbol",(symbol,pos["opened"])).fetchone()
   if not row:return None
   account=c.execute("update account_state set equity=equity+%s,realized_pnl=realized_pnl+%s,updated_at=%s where id=1 returning equity,realized_pnl",
    (pnl,pnl,now())).fetchone()
   features=json.dumps(pos.get("features",{}),default=str)
   c.execute("""insert into trade_history(opened,closed,symbol,side,entry,exit,pnl,reason,headline,event_id,strategy,score,features)
    values(%s,%s,%s,%s,%s,%s,%s,%s,%s,null,'pump_dump',%s,%s::jsonb)""",
    (pos["opened"],now(),symbol,pos["side"],pos["entry"],price,pnl,reason,"PUMP_DUMP",pos.get("score",0),features))
   c.execute("""insert into pump_trade_history(opened,closed,symbol,side,entry,exit,pnl,reason,score,features)
    values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
    (pos["opened"],now(),symbol,pos["side"],pos["entry"],price,pnl,reason,pos.get("score",0),features))
   c.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'pump_trade_closed',%s::jsonb)",
    (now(),json.dumps({"strategy":"pump_dump","symbol":symbol,"side":pos["side"],"entry":pos["entry"],"exit":price,"pnl":pnl,"reason":reason},default=str)))
 with LOCK:
  S["pump_positions"].pop(symbol,None);S["equity"]=float(account["equity"]);S["realized_pnl"]=float(account["realized_pnl"])
  S["pump_equity"]=S["equity"];S["pump_realized_pnl"]=S["realized_pnl"];S["pump_trades"]+=1;S["trades"]+=1
 return {"pnl":pnl,"equity":float(account["equity"])}

def pump_mark_positions(prices):
 # Universal exit policy: confirmed local extreme + weakening only.
 with LOCK:
  positions=copy.deepcopy(S["pump_positions"])
  timelines={k:list(v) for k,v in S.get("_timeline",{}).items()}
 for sym,pos in positions.items():
  px=prices.get(sym)
  if not px:continue
  entry=float(pos["entry"]);side=int(pos["side"]);lev=float(pos["leverage"])
  prior_peak_roe=float(pos.get("peak_roe",0) or 0)
  peak_price=entry*(1+(prior_peak_roe/lev)*side)
  probe=copy.deepcopy(pos);probe["peak"]=peak_price
  probe["history"]=[float(r[1]) for r in timelines.get(sym,[])[-120:] if len(r)>=2]
  evaluated,reason=evaluate_exit(probe,float(px),now())
  peak_price=float(evaluated.get("peak",entry));peak=(peak_price/entry-1)*side*lev
  with LOCK:
   if sym in S["pump_positions"]:
    S["pump_positions"][sym]["last_exit_check"]=evaluated.get("last_exit_check")
    S["pump_positions"][sym]["last_price"]=float(px);S["pump_positions"][sym]["peak_roe"]=peak
  if reason:
   pump_close(sym,px,"local_extreme_weakening");continue
  if peak!=float(pos.get("peak_roe",0)):
   with pg() as db:
    with db.transaction():
     STORE.fence(db);db.execute("update pump_positions set peak_roe=%s where symbol=%s and opened=%s",(peak,sym,pos["opened"]))

def whale_liq_open(symbol,side,price,score,features):
 if S.get("mode")!="PAPER_ONLY" or S.get("orders_enabled") or side not in (-1,1) or not price:return False
 with LOCK:
  if not S["engine_active"]:return False
 reserved,margin,reason,free=_reserve_shared_entry(symbol)
 if not reserved:
  journal("entry_skipped",None,{"strategy":"whale_liquidation","symbol":symbol,"reason":reason,"free_margin":free})
  return False
 try:
  notional=margin*TRADE_LEVERAGE;opened=now();epoch=time.time()
  pos={"side":side,"entry":float(price),"notional":notional,"margin":margin,"leverage":TRADE_LEVERAGE,"opened":opened,"t":epoch,"peak_roe":0.0,"score":float(score),"features":features}
  with pg() as db:
   with db.transaction():
    STORE.fence(db)
    row=db.execute("""insert into whale_liq_positions(symbol,side,entry,notional,margin,leverage,opened,opened_epoch,peak_roe,score,features)
     values(%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s::jsonb) on conflict(symbol) do nothing returning symbol""",
     (symbol,side,price,notional,margin,TRADE_LEVERAGE,opened,epoch,float(score),json.dumps(features,default=str))).fetchone()
    if not row:return False
    db.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'whale_liq_trade_opened',%s::jsonb)",
     (now(),json.dumps({"strategy":"whale_liquidation","symbol":symbol,"side":side,"entry":price,"score":score,"margin":margin,"notional":notional,"leverage":TRADE_LEVERAGE,"features":features},default=str)))
  with LOCK:S["whale_positions"][symbol]=pos
  return True
 finally:_release_shared_entry(symbol)

def whale_liq_close(symbol,price,reason):
 with LOCK:pos=copy.deepcopy(S["whale_positions"].get(symbol))
 if not pos or not price:return None
 pnl=pos["notional"]*(float(price)/pos["entry"]-1)*pos["side"]-pos["notional"]*FEE*2
 with pg() as c:
  with c.transaction():
   STORE.fence(c)
   row=c.execute("delete from whale_liq_positions where symbol=%s and opened=%s returning symbol",(symbol,pos["opened"])).fetchone()
   if not row:return None
   account=c.execute("update account_state set equity=equity+%s,realized_pnl=realized_pnl+%s,updated_at=%s where id=1 returning equity,realized_pnl",
    (pnl,pnl,now())).fetchone()
   features=json.dumps(pos.get("features",{}),default=str)
   c.execute("""insert into trade_history(opened,closed,symbol,side,entry,exit,pnl,reason,headline,event_id,strategy,score,features)
    values(%s,%s,%s,%s,%s,%s,%s,%s,%s,null,'whale_liquidation',%s,%s::jsonb)""",
    (pos["opened"],now(),symbol,pos["side"],pos["entry"],price,pnl,reason,"WHALE_LIQUIDATION",pos.get("score",0),features))
   c.execute("""insert into whale_liq_trade_history(opened,closed,symbol,side,entry,exit,pnl,reason,score,features)
    values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
    (pos["opened"],now(),symbol,pos["side"],pos["entry"],price,pnl,reason,pos.get("score",0),features))
   c.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'whale_liq_trade_closed',%s::jsonb)",
    (now(),json.dumps({"strategy":"whale_liquidation","symbol":symbol,"side":pos["side"],"entry":pos["entry"],"exit":price,"pnl":pnl,"reason":reason},default=str)))
 with LOCK:
  S["whale_positions"].pop(symbol,None);S["equity"]=float(account["equity"]);S["realized_pnl"]=float(account["realized_pnl"])
  S["whale_equity"]=S["equity"];S["whale_realized_pnl"]=S["realized_pnl"];S["whale_trades"]+=1;S["trades"]+=1
 return {"pnl":pnl,"equity":float(account["equity"])}

def whale_liq_mark_positions(prices):
 with LOCK:
  positions=copy.deepcopy(S["whale_positions"]);timelines={k:list(v) for k,v in S.get("_timeline",{}).items()}
 for sym,pos in positions.items():
  px=prices.get(sym)
  if not px:continue
  entry=float(pos["entry"]);side=int(pos["side"]);lev=float(pos["leverage"])
  with LOCK:ctx=copy.deepcopy(S.get("_pump_ctx",{}).get(sym,{}))
  mark=float(ctx.get("mark_price",0) or 0) or float(px)
  features=copy.deepcopy(pos.get("features",{}));liq=float(features.get("liquidation_price",0) or 0);victim=str(features.get("victim_side","")).lower()
  reached=bool(liq>0 and ((victim=="long" and mark<=liq) or (victim=="short" and mark>=liq)))
  features_changed=False
  if reached and not features.get("liquidation_level_reached_at"):
   features["liquidation_level_reached_at"]=now();features["liquidation_level_reached_mark"]=mark;features_changed=True
   journal("whale_liq_level_reached",None,{"symbol":sym,"victim_side":victim,"liquidation_price":liq,"mark_price":mark,"entry":entry})
  if features.get("liquidation_level_reached_at") and liq>0:
   post_bps=max(0.0,side*(mark/liq-1.0)*10000.0)
   if post_bps>float(features.get("post_liq_max_favorable_bps",0) or 0):
    features["post_liq_max_favorable_bps"]=round(post_bps,2);features_changed=True
  if features_changed:
   with LOCK:
    if sym in S["whale_positions"]:S["whale_positions"][sym]["features"]=features
   with pg() as db:
    with db.transaction():
     STORE.fence(db);db.execute("update whale_liq_positions set features=%s::jsonb where symbol=%s and opened=%s",(json.dumps(features,default=str),sym,pos["opened"]))
   pos["features"]=features
  roe=(float(px)/entry-1)*side*lev;peak=max(float(pos.get("peak_roe",0) or 0),roe)
  peak_price=entry*(1+(peak/lev)*side)
  probe=copy.deepcopy(pos);probe["peak"]=peak_price;probe["history"]=[float(r[1]) for r in timelines.get(sym,[])[-120:] if len(r)>=2]
  evaluated,reason=evaluate_exit(probe,float(px),now())
  new_peak=float(evaluated.get("peak",entry));peak=(new_peak/entry-1)*side*lev
  with LOCK:
   if sym in S["whale_positions"]:
    S["whale_positions"][sym]["peak_roe"]=peak
    S["whale_positions"][sym]["last_exit_check"]=evaluated.get("last_exit_check")
    S["whale_positions"][sym]["last_price"]=float(px)
  if reason:
   whale_liq_close(sym,float(px),"local_extreme_weakening");continue
  with pg() as c:
   with c.transaction():
    STORE.fence(c);c.execute("update whale_liq_positions set peak_roe=%s where symbol=%s and opened=%s",(peak,sym,pos["opened"]))

def _whale_liq_book(symbol):
 try:
  book=json.loads(get(API,{"type":"l2Book","coin":symbol}));levels=book.get("levels",[])
  if len(levels)<2:return None
  bids,asks=levels[0][:10],levels[1][:10]
  bid_depth=sum(float(x.get("sz",0) or 0)*float(x.get("px",0) or 0) for x in bids)
  ask_depth=sum(float(x.get("sz",0) or 0)*float(x.get("px",0) or 0) for x in asks)
  bp=float(bids[0].get("px",0) or 0) if bids else 0.0
  ap=float(asks[0].get("px",0) or 0) if asks else 0.0
  mid=(bp+ap)/2 if bp and ap else 0.0
  return {"imbalance":(bid_depth-ask_depth)/(bid_depth+ask_depth) if bid_depth+ask_depth else 0.0,
          "bid_depth_usd":bid_depth,"ask_depth_usd":ask_depth,
          "spread_bps":((ap-bp)/mid*10000) if mid else 9999.0}
 except Exception:return None

def _whale_liq_cvd(symbol):
 try:
  flow=hyperdata("/v1/orderflow/"+urllib.parse.quote(symbol)) or {}
  snaps=flow.get("snapshots") or flow.get("timeframes") or {}
  one=snaps.get("1m") if isinstance(snaps,dict) else None
  if isinstance(one,dict):
   cvd=float(one.get("cvd",0) or 0);buy=float(one.get("buy_volume",0) or 0);sell=float(one.get("sell_volume",0) or 0)
   denom=buy+sell
   return cvd,(buy-sell)/denom if denom else 0.0,one.get("coverage")
  cvd=float(flow.get("cumulative_cvd",0) or 0)
  return cvd,0.0,None
 except Exception:return 0.0,0.0,None

def whale_liquidation_scan():
 last_signal={};streaks={}
 pool=concurrent.futures.ThreadPoolExecutor(max_workers=MICRO_ANALYSIS_THREADS,thread_name_prefix="whale-micro")
 def analyze_position(p,prices,history,contexts,stamp):
  try:
   sym=str(p.get("symbol","")).upper()
   if sym not in LIQ_WHALE_SYMBOLS or sym not in prices:return None
   size=float(p.get("size_usd",0) or 0)
   if size<max(LIQ_WHALE_MIN_USD,LIQ_WHALE_MIN_BY_SYMBOL.get(sym,LIQ_WHALE_MIN_USD)):return None
   scanned=float(p.get("scanned_at",0) or 0);position_age=(stamp-scanned) if scanned else 999999.0
   if position_age>LIQ_WHALE_MAX_POSITION_AGE_SECONDS:return None
   victim=str(p.get("side","")).lower();side=-1 if victim=="long" else 1 if victim=="short" else 0
   if not side:return None
   ctx=contexts.get(sym,{})
   book_px=float(prices[sym]);mark=float(ctx.get("mark_price",0) or 0) or book_px
   liq=float(p.get("liq_price",0) or 0)
   if liq<=0:return None
   if victim=="long" and liq>=mark:return None
   if victim=="short" and liq<=mark:return None
   mark_dist=abs(mark-liq)/mark*100
   if mark_dist<0.08 or mark_dist>LIQ_WHALE_MAX_DISTANCE_PCT:return None
   rows_t=history.get(sym,[])
   r15=_timeline_return(rows_t,stamp,15,book_px);r60=_timeline_return(rows_t,stamp,60,book_px)
   if r15 is None or r60 is None:return None
   book=_whale_liq_book(sym);cvd,flow_imb,coverage=_whale_liq_cvd(sym)
   if not book:return None
   imb=float(book.get("imbalance",0) or 0);spread=float(book.get("spread_bps",9999) or 9999)
   forced_flow=size*0.20
   impact_depth=float(book.get("bid_depth_usd" if victim=="long" else "ask_depth_usd",0) or 0)
   impact_ratio=forced_flow/max(1.0,impact_depth)
   base=LIQ_WHALE_BASE_ENTRY_DISTANCE.get(sym,0.60)
   extra=0.0
   if impact_ratio>=0.50:extra+=0.15
   if impact_ratio>=1.00:extra+=0.20
   if impact_ratio>=2.00:extra+=0.20
   dynamic_entry=min(LIQ_WHALE_MAX_DISTANCE_PCT,base+extra)
   if mark_dist>dynamic_entry:return None
   burst=float(ctx.get("volume_burst_ratio",0) or 0)
   vol_z=ctx.get("volume_rate_z")
   oi_raw=float(ctx.get("oi_delta_60s",0) or 0);oi_abs=abs(oi_raw)
   trend_ok=(side*r15>=0.0004 and side*r60>=0.0008)
   book_ok=(side*imb>=0.06 and spread<=12)
   flow_ok=(side*flow_imb>=0.08)
   participation_ok=(burst>=1.5 or (vol_z is not None and float(vol_z)>=2.5))
   oi_ok=oi_abs>=0.0025
   impact_ok=impact_ratio>=0.35
   confirmations=sum([book_ok,flow_ok,participation_ok,oi_ok,impact_ok])
   pressure_ok=confirmations>=3
   score=20.0
   score+=max(0.0,22.0*(1.0-mark_dist/max(dynamic_entry,0.01)))
   score+=min(18.0,5.0+max(0.0,math.log10(size/max(1.0,LIQ_WHALE_MIN_BY_SYMBOL.get(sym,LIQ_WHALE_MIN_USD))))*10.0)
   score+=min(15.0,impact_ratio*7.5)
   if side*r15>=0.0004:score+=8
   if side*r60>=0.0008:score+=10
   if book_ok:score+=8
   if flow_ok:score+=8
   if participation_ok:score+=5
   if oi_ok:score+=4
   features={"engine":"whale_liquidation_hunt_v2","symbol":sym,"side":side,"victim_side":victim,
     "whale_address":p.get("address"),"whale_size_usd":size,"forced_flow_first_slice_usd":forced_flow,
     "liquidation_price":liq,"book_price":book_px,"mark_price":mark,"distance_pct":mark_dist,
     "reported_distance_pct":p.get("distance_pct"),"dynamic_entry_distance_pct":dynamic_entry,
     "position_age_seconds":position_age,"r15":r15,"r60":r60,"orderbook_imbalance":imb,
     "bid_depth_usd":book.get("bid_depth_usd"),"ask_depth_usd":book.get("ask_depth_usd"),
     "spread_bps":spread,"liquidation_flow_to_depth":impact_ratio,"cvd_1m":cvd,
     "flow_imbalance":flow_imb,"flow_coverage":coverage,"volume_burst_ratio":burst,
     "volume_rate_z":vol_z,"oi_delta_60s":oi_raw,"micro_confirmations":confirmations,
     "score":round(min(100.0,score),2),"trend_ok":trend_ok,"pressure_ok":pressure_ok}
   return features
  except Exception:return None
 try:
  while not SHUTDOWN.is_set():
   try:
    with LOCK:
     active=S["engine_active"];prices=dict(S.get("_prices",{}));history={k:list(v) for k,v in S.get("_timeline",{}).items()};contexts=copy.deepcopy(S.get("_pump_ctx",{}))
    if not active:
     SHUTDOWN.wait(0.5);continue
    data=hyperdata("/v1/positions/danger-zone?threshold="+urllib.parse.quote(str(LIQ_WHALE_MAX_DISTANCE_PCT))) or {}
    rows=data.get("positions",[]) if isinstance(data,dict) else []
    stamp=time.time()
    futures=[pool.submit(analyze_position,p,prices,history,contexts,stamp) for p in rows]
    candidates=[]
    for f in concurrent.futures.as_completed(futures):
     x=f.result()
     if x:candidates.append(x)
    candidates.sort(key=lambda x:(x["score"],x["liquidation_flow_to_depth"],x["whale_size_usd"]),reverse=True)
    present=set()
    qualified=[]
    for x in candidates:
     key=(x["symbol"],int(x["side"]));present.add(key);streaks[key]=streaks.get(key,0)+1
     x["confirmation_streak"]=streaks[key]
     if x["score"]>=LIQ_WHALE_SCORE_MIN and x["trend_ok"] and x["pressure_ok"] and x["confirmation_streak"]>=2:
      qualified.append(x)
    for key in list(streaks):
     if key not in present:streaks.pop(key,None)
    for x in qualified:
     sym=x["symbol"];side=int(x["side"])
     opened=whale_liq_open(sym,side,prices[sym],x["score"],x)
     action="OPENED" if opened else "QUALIFIED"
     key=(sym,side,action)
     if stamp-last_signal.get(key,0)<15:continue
     last_signal[key]=stamp
     ident=hashlib.sha256(("WHALELIQ2:"+sym+":"+str(side)+":"+str(int(stamp//15))+":"+action).encode()).hexdigest()
     with pg() as db:
      db.execute("""insert into whale_liq_signal_journal(id,ts,symbol,side,score,action,features)
       values(%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict(id) do nothing""",
       (ident,now(),sym,side,float(x["score"]),action,json.dumps(x,default=str)))
     journal("whale_liq_signal",None,{"symbol":sym,"side":side,"score":x["score"],"action":action,
       "distance_pct":x["distance_pct"],"dynamic_entry_distance_pct":x["dynamic_entry_distance_pct"],
       "whale_size_usd":x["whale_size_usd"],"liquidation_price":x["liquidation_price"],
       "liquidation_flow_to_depth":x["liquidation_flow_to_depth"]})
    with LOCK:
     S["sources"]["WhaleLiquidationScanner"]={"ok":True,"last_check":now(),"mode":"adaptive_mark_price_liquidation_hunt_v2",
       "symbols":sorted(LIQ_WHALE_SYMBOLS),"scan_seconds":LIQ_WHALE_SCAN_SECONDS,"max_scan_distance_pct":LIQ_WHALE_MAX_DISTANCE_PCT,
       "base_entry_distance_pct":LIQ_WHALE_BASE_ENTRY_DISTANCE,"min_whale_usd":LIQ_WHALE_MIN_BY_SYMBOL,
       "max_position_age_seconds":LIQ_WHALE_MAX_POSITION_AGE_SECONDS,"analysis_threads":MICRO_ANALYSIS_THREADS,
       "danger_positions":len(rows),"eligible_candidates":len(candidates),"qualified_candidates":len(qualified),
       "top_candidates":candidates[:5],"paper_positions":len(S["whale_positions"]),"shared_account_equity":round(S["equity"],4),
       "paper_trades":S["whale_trades"],"error":None}
   except Exception as exc:
    with LOCK:S["sources"]["WhaleLiquidationScanner"]={"ok":False,"last_check":now(),"mode":"adaptive_mark_price_liquidation_hunt_v2","analysis_threads":MICRO_ANALYSIS_THREADS,"error":str(exc)[:180]}
   SHUTDOWN.wait(LIQ_WHALE_SCAN_SECONDS)
 finally:pool.shutdown(wait=False,cancel_futures=True)

def flatten_news_for_regime(reason,prices):
 with LOCK:items=[(sym,copy.deepcopy(pos)) for sym,pos in S["positions"].items()]
 closed=[]
 for sym,pos in items:
  px=prices.get(sym) or pos.get("last_price")
  if not px:continue
  result=STORE.close(sym,pos,px,reason)
  if result:
   with LOCK:
    S["equity"]=float(result["equity"]);S["realized_pnl"]=float(result["realized_pnl"]);S["trades"]+=1;S["positions"].pop(sym,None)
   closed.append(sym)
 if closed:journal("market_regime_flatten",None,{"reason":reason,"symbols":closed})
 return closed

def _timeline_return(rows,stamp,age,current):
 candidates=[r for r in rows if len(r)>=2 and age-20<=stamp-float(r[0])<=age+25]
 if not candidates:return None
 t,p=min(candidates,key=lambda r:abs((stamp-float(r[0]))-age))
 try:return float(current)/float(p)-1
 except Exception:return None

def market_regime(prices,history,volumes,stamp):
 rows=[]
 for sym,px in prices.items():
  if volumes.get(sym,0)<5_000_000:continue
  r60=_timeline_return(history.get(sym,[]),stamp,60,px);r180=_timeline_return(history.get(sym,[]),stamp,180,px)
  if r60 is None:continue
  rows.append({"symbol":sym,"r60":r60,"r180":r180 if r180 is not None else r60})
 if len(rows)<20:return {"mode":"NORMAL","count":len(rows),"candidates":[]}
 avg60=sum(x["r60"] for x in rows)/len(rows);avg180=sum(x["r180"] for x in rows)/len(rows)
 down60=sum(x["r60"]<=-0.0025 for x in rows)/len(rows);up60=sum(x["r60"]>=0.0025 for x in rows)/len(rows)
 down180=sum(x["r180"]<=-0.005 for x in rows)/len(rows);up180=sum(x["r180"]>=0.005 for x in rows)/len(rows)
 mode="NORMAL";side=0
 if (down60>=0.60 and avg60<=-0.0022) or (down180>=0.65 and avg180<=-0.0055):mode="MARKET_DUMP";side=-1
 elif (up60>=0.60 and avg60>=0.0022) or (up180>=0.65 and avg180>=0.0055):mode="MARKET_PUMP";side=1
 candidates=[]
 if side:
  ranked=sorted((x for x in rows if side*x["r60"]>0),key=lambda x:side*x["r60"],reverse=True)
  for x in ranked[:PUMP_MAX_POSITIONS]:
   score=min(100,60+abs(x["r60"])*4000+abs(x["r180"])*1200)
   candidates.append({"symbol":x["symbol"],"side":side,"score":round(score,2),"r60_pct":round(x["r60"]*100,3),"r180_pct":round(x["r180"]*100,3),"regime":mode,"exhaustion":False})
 return {"mode":mode,"side":side,"count":len(rows),"avg60":avg60,"avg180":avg180,"down60":down60,"up60":up60,"down180":down180,"up180":up180,"candidates":candidates}

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
      # PAPER_ONLY exits are universal: confirmed local extreme + weakening.
      # No strategy-specific TP/SL/timer or account-equity flatten may bypass it.
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
   if S["engine_active"]:
    pump_mark_positions(valid);whale_liq_mark_positions(valid)
  except LeaseLost as e:
   S["engine_active"]=False;S["engine_error"]=str(e)
  except Exception as e:
   S["errors"]+=1;S["last_market_error"]=str(e)[:180];S["last_error"]="market: "+str(e)[:180]
  S["_market_heartbeat"]=time.time()
  SHUTDOWN.wait(2)

def impulse_scan():
 last_signal={};streaks={}
 pool=concurrent.futures.ThreadPoolExecutor(max_workers=MICRO_ANALYSIS_THREADS,thread_name_prefix="pump-micro")
 def enrich(candidate):
  candidate=dict(candidate);sym=candidate["symbol"];side=int(candidate["side"])
  try:
   book=json.loads(get(API,{"type":"l2Book","coin":sym}));levels=book.get("levels",[])
   if len(levels)<2:return None
   bids,asks=levels[0][:10],levels[1][:10]
   bd=sum(float(x.get("sz",0) or 0)*float(x.get("px",0) or 0) for x in bids)
   ad=sum(float(x.get("sz",0) or 0)*float(x.get("px",0) or 0) for x in asks)
   imb=(bd-ad)/(bd+ad) if bd+ad else 0.0
   bp=float(bids[0]["px"]) if bids else 0.0;ap=float(asks[0]["px"]) if asks else 0.0
   mid=(bp+ap)/2 if bp and ap else 0.0;spread=(ap-bp)/mid*10000 if mid else 9999.0
   candidate["orderbook_imbalance"]=round(imb,4);candidate["spread_bps"]=round(spread,2)
   candidate["book_depth_usd"]=round(bd+ad,2)
  except Exception as exc:
   candidate["book_error"]=str(exc)[:100];return None
  try:
   flow=hyperdata("/v1/orderflow/"+urllib.parse.quote(sym)) or {}
   snaps=flow.get("snapshots") or flow.get("timeframes") or {}
   one=snaps.get("1m") if isinstance(snaps,dict) else None
   if isinstance(one,dict):
    buy=float(one.get("buy_volume",0) or 0);sell=float(one.get("sell_volume",0) or 0);cvd=float(one.get("cvd",0) or 0)
    candidate["cvd_1m"]=cvd;candidate["flow_imbalance"]=(buy-sell)/(buy+sell) if buy+sell else 0.0
    candidate["flow_coverage"]=one.get("coverage")
   else:
    candidate["cvd_1m"]=float(flow.get("cumulative_cvd",0) or 0);candidate["flow_imbalance"]=0.0;candidate["flow_coverage"]=None
  except Exception:
   candidate["cvd_1m"]=0.0;candidate["flow_imbalance"]=0.0;candidate["flow_coverage"]=None
  imb=float(candidate.get("orderbook_imbalance",0) or 0);flow_imb=float(candidate.get("flow_imbalance",0) or 0)
  spread=float(candidate.get("spread_bps",9999) or 9999);oi=abs(float(candidate.get("oi_delta_60s",0) or 0))
  vol_z=candidate.get("volume_rate_z")
  book_ok=side*imb>=0.15 and spread<=15
  flow_ok=side*flow_imb>=0.08
  oi_ok=oi>=0.003
  abnormal_ok=(vol_z is not None and float(vol_z)>=3.0) or float(candidate.get("volume_burst_ratio",0) or 0)>=3.0
  confirmations=sum([book_ok,flow_ok,oi_ok,abnormal_ok])
  candidate["book_ok"]=book_ok;candidate["flow_ok"]=flow_ok;candidate["oi_ok"]=oi_ok;candidate["abnormal_volume_ok"]=abnormal_ok
  candidate["micro_confirmations"]=confirmations
  if book_ok:candidate["score"]=min(100,float(candidate["score"])+8)
  if flow_ok:candidate["score"]=min(100,float(candidate["score"])+8)
  if oi_ok:candidate["score"]=min(100,float(candidate["score"])+5)
  if abnormal_ok:candidate["score"]=min(100,float(candidate["score"])+5)
  return candidate if confirmations>=3 and spread<=15 else None
 try:
  while not SHUTDOWN.is_set():
   try:
    with LOCK:
     active=S["engine_active"];prices=dict(S.get("_prices",{}));history={k:list(v) for k,v in S.get("_timeline",{}).items()}
     volumes=dict(S.get("_day_volumes",{}));contexts=copy.deepcopy(S.get("_pump_ctx",{}))
    if not active:
     SHUTDOWN.wait(0.5);continue
    stamp=time.time()
    found=momentum_candidates(prices,history,volumes,stamp,minimum_day_volume=5_000_000.0,contexts=contexts)
    futures=[pool.submit(enrich,x) for x in found[:20]]
    enriched=[]
    for f in concurrent.futures.as_completed(futures):
     x=f.result()
     if x:enriched.append(x)
    now_keys=set();qualified=[]
    for x in enriched:
     key=(x["symbol"],int(x["side"]));now_keys.add(key);streaks[key]=streaks.get(key,0)+1
     x["confirmation_streak"]=streaks[key]
     if x["score"]>=84 and x["confirmation_streak"]>=3:qualified.append(x)
    for key in list(streaks):
     if key not in now_keys:streaks.pop(key,None)
    qualified.sort(key=lambda x:x["score"],reverse=True)
    for candidate in qualified[:3]:
     sym=candidate["symbol"];side=int(candidate["side"])
     opened=bool(prices.get(sym)) and pump_open(sym,side,prices[sym],candidate["score"],candidate)
     action="OPENED" if opened else "QUALIFIED"
     bucket=int(stamp//15);ident=hashlib.sha256(("PUMP3:"+sym+":"+str(side)+":"+str(bucket)+":"+action).encode()).hexdigest()
     if stamp-last_signal.get((sym,side,action),0)<15:continue
     last_signal[(sym,side,action)]=stamp
     with pg() as db:
      db.execute("""insert into pump_signal_journal(id,ts,symbol,side,score,action,features)
        values(%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict(id) do nothing""",
        (ident,now(),sym,side,float(candidate["score"]),action,json.dumps(candidate,default=str)))
    with LOCK:
     S["sources"]["PumpDumpScanner"]={"ok":bool(prices and volumes),"last_check":now(),"markets":len(prices),
       "liquid_markets":sum(v>=5_000_000 for v in volumes.values()),"raw_candidates":len(found),"micro_confirmed":len(enriched),
       "qualified_candidates":len(qualified),"top_candidates":qualified[:5],"mode":"high_conviction_paper_v3",
       "scan_seconds":PUMP_SCAN_SECONDS,"min_day_volume":5_000_000,"entry_score_min":84,"confirmation_scans":3,
       "analysis_threads":MICRO_ANALYSIS_THREADS,"paper_positions":len(S["pump_positions"]),
       "shared_account_equity":round(S["equity"],4),"market_regime":{"mode":"ADVISORY_ONLY"},
       "error":None if prices and volumes else "missing_market_prices_or_metadata"}
   except Exception as exc:
    with LOCK:S["sources"]["PumpDumpScanner"]={"ok":False,"last_check":now(),"mode":"high_conviction_paper_v3","analysis_threads":MICRO_ANALYSIS_THREADS,"error":str(exc)[:180]}
   SHUTDOWN.wait(PUMP_SCAN_SECONDS)
 finally:pool.shutdown(wait=False,cancel_futures=True)

def market_metadata():
 while not SHUTDOWN.is_set():
  try:
   raw=json.loads(get(API,{"type":"metaAndAssetCtxs"}))
   universe=raw[0].get("universe",[]);ctxs=raw[1]
   volumes={};pump_ctx={};stamp=time.time()
   with LOCK:
    prev_ctx=copy.deepcopy(S.get("_pump_ctx",{}));baselines=copy.deepcopy(S.get("_volume_baseline",{}))
   new_baselines={}
   for asset,ctx in zip(universe,ctxs):
    try:
     name=asset["name"];v=float(ctx.get("dayNtlVlm",0) or 0);oi=float(ctx.get("openInterest",0) or 0)
     funding=float(ctx.get("funding",0) or 0);premium=float(ctx.get("premium",0) or 0)
     mark=float(ctx.get("markPx",0) or 0);oracle=float(ctx.get("oraclePx",0) or 0)
     if math.isfinite(v) and v>=0:volumes[name]=v
     old=prev_ctx.get(name,{})
     dt=max(1.0,stamp-float(old.get("epoch",stamp)))
     oi_old=float(old.get("open_interest",oi) or oi);vol_old=float(old.get("day_volume",v) or v)
     oi_delta=(oi/oi_old-1) if oi_old>0 else 0.0
     vol_delta=max(0.0,v-vol_old);rate=vol_delta/dt
     expected=max(1.0,v/86400.0*dt);burst=vol_delta/expected if expected>0 else 0.0
     base=baselines.get(name,{});n=int(base.get("n",0));mean=float(base.get("mean",rate) or rate);var=float(base.get("var",0) or 0)
     z=(rate-mean)/math.sqrt(var) if n>=12 and var>1e-12 else None
     alpha=2.0/(min(n+1,60)+1.0);delta=rate-mean
     mean2=mean+alpha*delta;var2=max(0.0,(1-alpha)*(var+alpha*delta*delta))
     new_baselines[name]={"n":min(10000,n+1),"mean":mean2,"var":var2}
     pump_ctx[name]={"epoch":stamp,"open_interest":oi,"day_volume":v,"funding":funding,"premium":premium,
       "mark_price":mark,"oracle_price":oracle,"oi_delta_60s":oi_delta*(60.0/dt),
       "volume_burst_ratio":burst,"volume_rate_usd_per_sec":rate,"volume_rate_z":z,
       "volume_baseline_samples":n}
    except (TypeError,ValueError,KeyError,ZeroDivisionError):continue
   with LOCK:
    S["_day_volumes"]=volumes;S["_pump_ctx"]=pump_ctx;S["_volume_baseline"]=new_baselines
    S["sources"]["MarketMetadata"]={"ok":True,"last_check":now(),"markets":len(volumes)}
  except Exception as e:
   with LOCK:S["sources"]["MarketMetadata"]={"ok":False,"last_check":now(),"error":str(e)[:140]}
  SHUTDOWN.wait(MARKET_METADATA_SECONDS)

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
    save_capacity_snapshot()
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
  elif any(w in lo for w in MARKET_WIDE_TERMS):mentions=["BTC"]
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
 fresh_window=source_freshness_window(source)
 fresh=freshness(published_at,time.time(),fresh_window)
 if not fresh["allowed"]:
  save_event_feature(ident,now(),source,title,sym,0,0.0,{"freshness":fresh,"freshness_window_seconds":fresh_window,"market_structure_filter_active":False})
  journal("decision",ident,{"symbol":sym,"side":0,"reason":fresh["reason"],"freshness":fresh,"freshness_window_seconds":fresh_window,"published_at":published_at})
  return 0
 event_type,event_side=classify_event(title,base_side)
 if is_price_action_only_news(title,event_type):
  feature={"delegated_to":"PumpDumpScanner","reason":"price_action_report_not_news_trigger","event_type":event_type,
           "source":source,"published_at":published_at,"symbol":sym}
  save_event_feature(ident,now(),source,title,sym,0,0.0,feature)
  journal("delegated_price_action_news",ident,{"source":source,"title":title,"symbol":sym,
    "event_type":event_type,"reason":"handled_by_pump_dump_scanner"})
  return 0
 weight=source_weight(source);effective_side=base_side if base_side else event_side
 if not sym or sym not in prices:
  journal("decision",ident,{"symbol":sym,"raw_side":base_side,"event_side":event_side,"event_type":event_type,"source_weight":weight,"side":0,"reason":"no_tradable_market"})
  return 0
 side,conf,features=decide(title,sym,effective_side,prices)
 features["event_type"]=event_type;features["source_weight"]=weight;features["freshness"]=fresh
 features["freshness_window_seconds"]=fresh_window
 conf=min(1.0,conf*weight)
 if side and weight<0.50:side=0
 reaction_limit=100.0 if sym in ("BTC","ETH") else 150.0
 shadow=reaction_shadow(sym,side,published_at,prices.get(sym),reaction_limit)
 late=bool(side and shadow.get("available") and shadow.get("would_skip"))
 if late:side=0
 features["reaction_shadow"]=shadow;features["reaction_filter_active"]=True
 save_event_feature(ident,now(),source,title,sym,side,conf if side else 0.0,features)
 reason="news_already_priced" if late else ("direction_guard_or_low_source_weight" if not side else "eligible")
 journal("decision",ident,{"symbol":sym,"raw_side":base_side,"event_side":event_side,"effective_side":effective_side,
   "event_type":event_type,"source_weight":weight,"side":side,"confidence":conf if side else 0.0,
   "price":prices.get(sym),"features":features,"reaction_shadow":shadow,"reaction_filter_active":True,"reason":reason})
 if side:open_signal(sym,side,title,prices,ident,published_at,source)
 return side

def open_signal(sym,side,title,prices,event_id=None,published_at=None,source=""):
 fresh_window=source_freshness_window(source)
 fresh=freshness(published_at,time.time(),fresh_window)
 reason=None
 with LOCK:
  if not fresh["allowed"]:reason=fresh["reason"]
  elif not S["engine_active"] or SHUTDOWN.is_set():reason="engine_not_active"
  elif not S.get("last_checkpoint") or time.time()-datetime.datetime.fromisoformat(S["last_checkpoint"]).timestamp()>15:reason="risk_checkpoint_stale"
  elif time.time()-S.get("_last_poll_epoch",0)>10:reason="stale_market_price"
  elif sym not in S.get("_prices",{}) or not side:reason="no_price_or_direction"
 if reason:
  journal("entry_skipped",event_id,{"strategy":"news","symbol":sym,"reason":reason,"freshness":fresh,"freshness_window_seconds":fresh_window});return False
 reserved,margin,reason,free=_reserve_shared_entry(sym)
 if not reserved:
  journal("entry_skipped",event_id,{"strategy":"news","symbol":sym,"reason":reason,"freshness":fresh,"free_margin":free});return False
 try:
  with LOCK:price=S["_prices"][sym]
  notional=margin*TRADE_LEVERAGE
  pos={"entry":price,"side":side,"notional":notional,"opened":now(),"t":time.time(),"headline":title,
       "locked":False,"stop":None,"peak":price,"trail_armed":False,"trail_stop":None,"history":[],
       "leverage":TRADE_LEVERAGE,"margin":margin,"event_id":event_id}
  if not STORE.save(sym,pos,create=True):return False
  with LOCK:S["positions"][sym]=pos
  return True
 finally:_release_shared_entry(sym)

def ingest_event(ident,source,title,published_at=None,source_url=None):
 # No long-running source or analysis code owns the risk loop's lock.
 if not S["engine_active"] or SHUTDOWN.is_set():return False
 with LOCK:prices=dict(S.get("_prices",{}))
 sym,side=detect(title,prices)
 non_market=is_non_market_news(title)
 liquidation_news=is_liquidation_news(title)
 if non_market or liquidation_news:side=0
 if not save_news_event(ident,now(),source,title,sym,side,published_at,source_url):return False
 with LOCK:S["news_seen"]+=1
 if non_market:
  journal("ignored_non_market_news",ident,{"source":source,"title":title,"symbol":sym,"reason":"promotional_or_non_market_event"})
  return True
 if liquidation_news:
  feature={"delegated_to":"WhaleLiquidationScanner","reason":"liquidation_news_not_tradeable","source":source,
           "published_at":published_at,"source_url":source_url,"symbol":sym}
  save_event_feature(ident,now(),source,title,sym,0,0.0,feature)
  journal("delegated_liquidation_news",ident,{"source":source,"title":title,"symbol":sym,
    "reason":"handled_by_whale_liquidation_scanner","published_at":published_at,"source_url":source_url})
  return True
 record_event(ident,source,title,sym,side,prices,published_at)
 return True

def free_x_realtime():
 handles=list(WATCH)
 poll=max(4.0,float(os.getenv("X_ALL_POLL_SECONDS","4")))
 probe_poll=max(60.0,float(os.getenv("X_PROBE_POLL_SECONDS","120")))
 seen={};primed=set();state_lock=threading.Lock()
 failures={h:0 for h in handles};last_success={};x_error_log_at={}
 disabled={h:False for h in handles};probe_due={}
 backends=("fx","xlookup","fixupx","vx")
 backend_idx={h:(sum(ord(ch) for ch in h)%len(backends)) for h in handles}

 # Bootstrap gradually instead of firing 128 requests in one burst. Once an
 # account proves readable it joins the 4-second active pool.
 base=time.monotonic()
 next_due={h:base+((sum(ord(ch) for ch in h)%2000)/100.0) for h in handles}
 inflight={};ingest_futures=set()
 pool=concurrent.futures.ThreadPoolExecutor(max_workers=min(48,len(handles)),thread_name_prefix="x-realtime")
 ingest_pool=concurrent.futures.ThreadPoolExecutor(max_workers=8,thread_name_prefix="x-ingest")
 with LOCK:
  S["sources"]["XMonitor"]={"ok":True,"degraded":True,"mode":"active_4s_probe_pool_starting",
   "last_check":now(),"accounts_ok":0,"accounts_initialized":0,"accounts_total":len(handles),
   "target_poll_seconds":poll,"probe_poll_seconds":probe_poll,"scan_workers":pool._max_workers,"error":None}

 def fetch_one(handle):
  idx=backend_idx.get(handle,0)%len(backends);backend=backends[idx]
  if backend=="fx":posts=free_x_fetch(handle,timeout=2.6,attempts=1)
  elif backend=="xlookup":posts=free_x_lookup_fetch(handle,timeout=2.6)
  elif backend=="fixupx":posts=free_x_fixupx_fetch(handle,timeout=2.6)
  else:posts=free_x_vx_fetch(handle,timeout=2.6)
  return posts,backend

 try:
  while not SHUTDOWN.is_set():
   if not S["engine_active"]:
    SHUTDOWN.wait(0.25);continue
   now_m=time.monotonic();active_inflight={meta[0] for meta in inflight.values()}
   active_due=[h for h in handles if not disabled[h] and h not in active_inflight and now_m>=next_due[h]]
   probe_due_now=[h for h in handles if disabled[h] and h not in active_inflight and now_m>=probe_due.get(h,now_m+probe_poll)]
   active_due.sort(key=lambda h:next_due[h]);probe_due_now.sort(key=lambda h:probe_due.get(h,0))
   available=max(0,pool._max_workers-len(inflight))

   # Protect the 4-second working pool. Probes get at most four slots and never
   # starve active accounts.
   probe_slots=min(4,len(probe_due_now),available)
   active_slots=max(0,available-probe_slots)
   selected=[(h,False) for h in active_due[:active_slots]]
   selected += [(h,True) for h in probe_due_now[:probe_slots]]
   if len(selected)<available:
    selected += [(h,False) for h in active_due[active_slots:active_slots+available-len(selected)]]

   for handle,is_probe in selected:
    try:
     fut=pool.submit(fetch_one,handle);inflight[fut]=(handle,now_m,is_probe)
     if is_probe:probe_due[handle]=now_m+probe_poll
     else:next_due[handle]=now_m+poll
    except Exception as exc:
     with LOCK:S["sources"]["XMonitor"]={"ok":False,"degraded":True,"mode":"active_4s_probe_pool",
      "last_check":now(),"accounts_total":len(handles),"error":"submit:"+str(exc)[:160]}

   done=[future for future in list(inflight) if future.done()]
   for future in done:
    handle,started,is_probe=inflight.pop(future);name="XFree:"+handle
    try:
     posts,backend=future.result()
     failures[handle]=0;disabled[handle]=False;last_success[handle]=time.time()
     next_due[handle]=time.monotonic()+poll
     stamps=[publication_epoch(p.get("created_at")) for p in posts];stamps=[x for x in stamps if x is not None]
     latest_age=(time.time()-max(stamps)) if stamps else None
     with LOCK:
      S["sources"][name]={"ok":True,"degraded":False,"disabled":False,"mode":backend+"_4s_poll",
       "backend":backend,"category":WATCH_CATEGORY.get(handle),"last_check":now(),"posts":len(posts),
       "poll_seconds":poll,"latest_post_age_seconds":round(latest_age,1) if latest_age is not None else None,
       "last_request_seconds":round(time.monotonic()-started,2),"consecutive_failures":0,
       "last_success_epoch":time.time(),"rate_limited":False}
     ids=[str(p["id"]) for p in posts]
     with state_lock:
      if handle not in primed:
       seen[handle]=set(ids);primed.add(handle);fresh=[]
      else:
       old=seen.setdefault(handle,set());fresh=[p for p in posts if str(p["id"]) not in old];old.update(ids)
       if len(old)>200:seen[handle]=set(ids[:100])
     for p in sorted(fresh,key=lambda q:publication_epoch(q.get("created_at")) or 0):
      stamp=publication_epoch(p.get("created_at"));age=time.time()-stamp if stamp is not None else None
      ident=hashlib.sha256(("XFree:"+handle+":"+str(p["id"])).encode()).hexdigest()
      if len(ingest_futures)<400:
       ingest_futures.add(ingest_pool.submit(ingest_event,ident,"XOfficial:"+handle,p["text"],p.get("created_at"),p.get("url")))
      if age is not None and 0<=age<=15:
       with LOCK:
        if name in S["sources"]:
         S["sources"][name]["delivery_latency_seconds"]=round(age,2)
    except Exception as exc:
     err=str(exc)[:220] if str(exc) else type(exc).__name__
     failures[handle]=failures.get(handle,0)+1
     backend_idx[handle]=(backend_idx.get(handle,0)+1)%len(backends)
     limited=any(x in err.lower() for x in ("429","rate.limit","too many requests"))
     prev_success=last_success.get(handle,0)
     # One transient failure gets another backend on the next 4s turn. A second
     # failure, or any rate-limit, moves the account to the low-rate probe pool.
     should_probe=limited or failures[handle]>=2
     if should_probe:
      disabled[handle]=True
      probe_due[handle]=time.monotonic()+(180 if limited else probe_poll)
     else:
      next_due[handle]=time.monotonic()+poll
     with LOCK:
      S["sources"][name]={"ok":bool(prev_success and time.time()-prev_success<=60),"degraded":True,
       "disabled":disabled[handle],"mode":"probe_pool" if disabled[handle] else "backend_rotate",
       "category":WATCH_CATEGORY.get(handle),"last_check":now(),"error":err,
       "consecutive_failures":failures[handle],"last_success_epoch":prev_success or None,
       "rate_limited":limited,"retry_after_seconds":(180 if limited else probe_poll) if disabled[handle] else poll,
       "last_request_seconds":round(time.monotonic()-started,2)}
     if time.time()-x_error_log_at.get(handle,0)>=120:
      x_error_log_at[handle]=time.time()
      try:journal("source_error",None,{"source":"X","handle":handle,"error":err,"rate_limited":limited,
       "pool":"probe" if disabled[handle] else "active"})
      except Exception:pass

   ingest_futures={future for future in ingest_futures if not future.done()}
   with LOCK:
    now_wall=time.time()
    initialized=sum(bool(S["sources"].get("XFree:"+h)) for h in handles)
    working=[h for h in handles if last_success.get(h) and now_wall-last_success[h]<=120]
    active_handles=[h for h in working if not disabled[h]]
    recent=[h for h in active_handles if now_wall-last_success[h]<=max(12,poll*3)]
    disabled_count=sum(disabled.values())
    rate_limited=sum(bool(S["sources"].get("XFree:"+h,{}).get("rate_limited")) for h in handles)
    # Health means the active working pool is being serviced now. Unavailable
    # accounts are reported as probe-pool, not as a total X outage.
    required=max(3,math.ceil(max(1,len(active_handles))*0.35))
    healthy=bool(recent and len(recent)>=required)
    key_handles=["elonmusk","realDonaldTrump","federalreserve","SECGov","BlackRock","Fidelity","ARKInvest","Grayscale"]
    key_status={h:{"ok":bool(S["sources"].get("XFree:"+h,{}).get("ok")),
                   "active":h in active_handles,
                   "mode":S["sources"].get("XFree:"+h,{}).get("mode"),
                   "error":S["sources"].get("XFree:"+h,{}).get("error")} for h in key_handles}
    S["sources"]["XMonitor"]={"ok":healthy,
     "mode":"active_4s_probe_pool","last_check":now(),"accounts_ok":len(active_handles),
     "accounts_initialized":initialized,"accounts_total":len(handles),"active_accounts":len(active_handles),
     "scan_label":"SCANNING %s / %s"%(len(active_handles),len(handles)),"key_accounts":key_status,
     "disabled_retry_accounts":disabled_count,"recently_polled_accounts":len(recent),
     "target_poll_seconds":poll,"probe_poll_seconds":probe_poll,
     "backend_accounts":{b:sum(1 for h in active_handles if backends[backend_idx.get(h,0)%len(backends)]==b) for b in backends},
     "ingest_queue":len(ingest_futures),"inflight_accounts":len(inflight),
     "queued_active_accounts":len(active_due),"queued_probe_accounts":len(probe_due_now),
     "scan_workers":pool._max_workers,"realtime_verified":healthy,
     "rate_limited_accounts":rate_limited,"last_successful_poll_epoch":max(last_success.values()) if last_success else None}
   SHUTDOWN.wait(0.03)
 except Exception as exc:
  with LOCK:S["sources"]["XMonitor"]={"ok":False,"degraded":True,"mode":"active_4s_probe_pool",
   "last_check":now(),"accounts_total":len(handles),"error":"worker_crash:"+str(exc)[:180]}
 finally:
  pool.shutdown(wait=False,cancel_futures=True);ingest_pool.shutdown(wait=False,cancel_futures=True)


CRITICAL_X_HANDLES=list(WATCH)

def x_critical_realtime():
 handles=list(CRITICAL_X_HANDLES)
 poll=max(4.0,float(os.getenv("X_CRITICAL_POLL_SECONDS","4")))
 seen={};primed=set();last_success={};backend_used={};last_error={};inflight={}
 pool=concurrent.futures.ThreadPoolExecutor(max_workers=len(handles),thread_name_prefix="x-critical")
 ingest_pool=concurrent.futures.ThreadPoolExecutor(max_workers=4,thread_name_prefix="x-critical-ingest")
 next_due={h:time.monotonic() for h in handles}
 def fetch_one(handle):
  errors=[]
  chain=[
   ("syndication",lambda:free_x_syndication_fetch(handle,timeout=2.2)),
   ("embed",lambda:free_x_embed_fetch(handle,timeout=2.2)),
   ("fx",lambda:free_x_fetch(handle,timeout=2.2,attempts=1)),
   ("xlookup",lambda:free_x_lookup_fetch(handle,timeout=2.2)),
   ("fixupx",lambda:free_x_fixupx_fetch(handle,timeout=2.2)),
   ("nitter",lambda:free_x_nitter_fetch(handle,timeout=2.2)),
   ("vx",lambda:free_x_vx_fetch(handle,timeout=2.2)),
  ]
  for name,fn in chain:
   try:
    posts=fn()
    if posts:return posts,name
    errors.append(name+":empty")
   except Exception as exc:
    errors.append(name+":"+str(exc)[:70])
  raise RuntimeError(" | ".join(errors)[:420])
 with LOCK:
  _xcrit={"ok":False,"mode":"dedicated_critical_pool_starting","last_check":now(),
   "accounts_ok":0,"accounts_total":len(handles),"scan_label":"SCANNING 0 / %s"%len(handles),
   "target_poll_seconds":poll,"key_accounts":{h:{"ok":False,"active":False} for h in handles},"error":None}
  S["sources"]["XCriticalMonitor"]=copy.deepcopy(_xcrit);S["sources"]["XMonitor"]=copy.deepcopy(_xcrit)
 try:
  while not SHUTDOWN.is_set():
   if not S["engine_active"]:
    SHUTDOWN.wait(0.2);continue
   mono=time.monotonic();active={meta[0] for meta in inflight.values()}
   for h in handles:
    if h in active or mono<next_due[h]:continue
    inflight[pool.submit(fetch_one,h)]=(h,mono);next_due[h]=mono+poll
   done=[f for f in list(inflight) if f.done()]
   for fut in done:
    h,started=inflight.pop(fut);src="XCritical:"+h
    try:
     posts,backend=fut.result();last_success[h]=time.time();backend_used[h]=backend;last_error.pop(h,None)
     ids=[str(p["id"]) for p in posts]
     if h not in primed:
      seen[h]=set(ids);primed.add(h);fresh=[]
     else:
      old=seen.setdefault(h,set());fresh=[p for p in posts if str(p["id"]) not in old];old.update(ids)
      if len(old)>250:seen[h]=set(ids[:120])
     latencies=[]
     for p in sorted(fresh,key=lambda q:publication_epoch(q.get("created_at")) or 0):
      stamp=publication_epoch(p.get("created_at"));age=time.time()-stamp if stamp is not None else None
      if age is not None and age>=0:latencies.append(age)
      ident=hashlib.sha256(("XFree:"+h+":"+str(p["id"])).encode()).hexdigest()
      ingest_pool.submit(ingest_event,ident,"XOfficial:"+h,p["text"],p.get("created_at"),p.get("url"))
     latency=min(latencies) if latencies else None
     with LOCK:S["sources"][src]={"ok":True,"active":True,"mode":backend+"_critical_4s","backend":backend,
      "last_check":now(),"posts":len(posts),"poll_seconds":poll,"last_request_seconds":round(time.monotonic()-started,2),
      "delivery_latency_seconds":round(latency,2) if latency is not None else None,
      "realtime_verified":bool(latency is not None and 0<=latency<=10),"error":None}
    except Exception as exc:
     err=str(exc)[:420];last_error[h]=err
     with LOCK:S["sources"][src]={"ok":False,"active":False,"mode":"critical_fallback_chain","last_check":now(),
      "poll_seconds":poll,"last_request_seconds":round(time.monotonic()-started,2),"error":err}
   with LOCK:
    wall=time.time()
    status={h:{"ok":bool(last_success.get(h) and wall-last_success[h]<=max(12,poll*3)),
               "active":bool(last_success.get(h) and wall-last_success[h]<=max(12,poll*3)),
               "backend":backend_used.get(h),"last_success_epoch":last_success.get(h),
               "error":last_error.get(h)} for h in handles}
    ok_count=sum(v["ok"] for v in status.values())
    _xcrit={"ok":ok_count==len(handles),"mode":"dedicated_critical_pool","last_check":now(),
      "accounts_ok":ok_count,"accounts_initialized":len(handles),"accounts_total":len(handles),"active_accounts":ok_count,
      "scan_label":"SCANNING %s / %s"%(ok_count,len(handles)),"target_poll_seconds":poll,
      "key_accounts":status,"scan_workers":len(handles),"realtime_verified":ok_count==len(handles),
      "error":None if ok_count==len(handles) else "partial_critical_coverage"}
    S["sources"]["XCriticalMonitor"]=copy.deepcopy(_xcrit);S["sources"]["XMonitor"]=copy.deepcopy(_xcrit)
   SHUTDOWN.wait(0.05)
 finally:
  pool.shutdown(wait=False,cancel_futures=True);ingest_pool.shutdown(wait=False,cancel_futures=True)

def x_list_realtime():
 auth=os.getenv("X_AUTH_TOKEN","").strip();ct0=os.getenv("X_CT0","").strip();list_id=os.getenv("X_LIST_ID","").strip()
 if not (auth and ct0 and list_id):return
 poll=max(8.0,float(os.getenv("X_LIST_POLL_SECONDS","10")))
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
   # Authenticated websocket is optional; public 4s scanner remains primary.
   return
 handles={h.strip().lower() for h in os.getenv("TRUTH_WATCH_HANDLES","realDonaldTrump,WhiteHouse,DanScavino,Kash,MelaniaTrump,SecWar,SpeakerJohnson,seckennedy,TulsiGabbard").split(",") if h.strip()}
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

def fetch_truth_relay(handle):
 base=os.getenv("TRUTH_RELAY_URL","").strip().rstrip("/")
 token=os.getenv("TRUTH_RELAY_TOKEN","").strip()
 if not base:raise RuntimeError("truth_relay_not_configured")
 url=base+"/truth?"+urllib.parse.urlencode({"handle":handle,"token":token})
 req=urllib.request.Request(url,headers={"User-Agent":"PANDORA-truth-relay-client/1","Accept":"application/json"})
 with urllib.request.urlopen(req,timeout=6) as r:data=json.load(r)
 if not data.get("ok"):raise RuntimeError("truth_relay_failed:"+" | ".join(data.get("errors") or []))
 posts=data.get("posts") or []
 if not posts:raise RuntimeError("truth_relay_empty")
 return posts,str(data.get("backend") or "relay")

def free_truth_realtime():
 # Public Truth Social scanner: no account/token required. Each account has its own
 # 4-second cadence and falls back from public REST to ActivityPub independently.
 handles=[h.strip() for h in os.getenv("TRUTH_WATCH_HANDLES","realDonaldTrump,WhiteHouse,DanScavino,Kash,MelaniaTrump,SecWar,SpeakerJohnson,seckennedy").split(",") if h.strip()]
 poll=max(8.0,float(os.getenv("TRUTH_FREE_POLL_SECONDS","10")))
 seen={};ids_cache={};next_due={h:time.monotonic() for h in handles};inflight={}
 backoff_until={};last_success={};error_log_at={}
 pool=concurrent.futures.ThreadPoolExecutor(max_workers=max(1,len(handles)),thread_name_prefix="truth-public")
 def fetch_one(handle):
  errors=[]
  if os.getenv("TRUTH_RELAY_URL","").strip():
   try:
    posts,relay_backend=fetch_truth_relay(handle)
    return ids_cache.get(handle),posts,{},"relay_"+relay_backend,True,None
   except Exception as exc:errors.append("relay:"+str(exc)[:100])
  try:
   account_id,posts,headers=free_truth_fetch(handle,ids_cache.get(handle))
   return account_id,posts,headers,"public_rest",False,None
  except Exception as exc:errors.append("rest:"+str(exc)[:100])
  try:
   posts=free_truth_ap_fetch(handle)
   return ids_cache.get(handle),posts,{},"activitypub",True," | ".join(errors)
  except Exception as exc:errors.append("activitypub:"+str(exc)[:100])
  try:
   posts=free_truth_rss_fetch(handle)
   return ids_cache.get(handle),posts,{},"profile_rss",True," | ".join(errors)
  except Exception as exc:errors.append("rss:"+str(exc)[:100])
  # Delayed Trump archives are intentionally NOT part of the trading scanner.
  # If direct REST/ActivityPub/profile RSS all fail, report the source unavailable
  # rather than presenting an hour-old archive as realtime.
  raise RuntimeError(" | ".join(errors))
 try:
  while not SHUTDOWN.is_set():
   if not S["engine_active"]:
    SHUTDOWN.wait(0.5);continue
   now_m=time.monotonic();active={meta[0] for meta in inflight.values()}
   for h in handles:
    if h in active or now_m<next_due[h] or now_m<backoff_until.get(h,0):continue
    fut=pool.submit(fetch_one,h);inflight[fut]=(h,now_m);next_due[h]=now_m+poll
   done=[f for f in list(inflight) if f.done()]
   for future in done:
    h,started=inflight.pop(future);name="TruthDirect:"+h
    try:
     account_id,posts,headers,backend,fallback,primary_error=future.result()
     if account_id:ids_cache[h]=account_id
     backoff_until.pop(h,None);last_success[h]=time.time()
     stamps=[publication_epoch(p.get("created_at")) for p in posts];stamps=[x for x in stamps if x is not None]
     latest_age=time.time()-max(stamps) if stamps else None
     with LOCK:S["sources"][name]={"ok":True,"degraded":fallback,"mode":backend+"_adaptive_poll","backend":backend,"fallback_used":fallback,"primary_error":primary_error,"last_check":now(),"posts":len(posts),"poll_seconds":poll,"last_request_seconds":round(time.monotonic()-started,2),"latest_post_age_seconds":round(latest_age,1) if latest_age is not None else None,"realtime_verified":False,"last_success_epoch":time.time()}
     ids=[str(p["id"]) for p in posts]
     if h not in seen:
      seen[h]=set(ids);fresh=[]
     else:
      old=seen[h];fresh=[p for p in posts if str(p["id"]) not in old];old.update(ids)
      if len(old)>300:seen[h]=set(ids[:150])
     for p in sorted(fresh,key=lambda q:publication_epoch(q.get("created_at")) or 0):
      age=time.time()-(publication_epoch(p.get("created_at")) or 0)
      if 0<=age<=10:
       with LOCK:S["sources"][name]["realtime_verified"]=True;S["sources"][name]["delivery_latency_seconds"]=round(age,2)
      ident=hashlib.sha256(("TruthPublic:"+h+":"+str(p["id"])).encode()).hexdigest()
      ingest_event(ident,"TruthSocialPublic:"+h,p["text"],p.get("created_at"),p.get("url"))
    except Exception as exc:
     err=str(exc)[:220] if str(exc) else type(exc).__name__;lo=err.lower()
     limited=any(x in lo for x in ("429","rate.limit","too many requests"))
     backoff=60 if limited else 8
     backoff_until[h]=time.monotonic()+backoff
     with LOCK:S["sources"][name]={"ok":False,"degraded":True,"mode":"public_rest_activitypub_4s","last_check":now(),"error":err,"rate_limited":limited,"retry_after_seconds":backoff,"last_request_seconds":round(time.monotonic()-started,2)}
     # Persist source failures without flooding Postgres every 4 seconds.
     if time.time()-error_log_at.get(h,0)>=60:
      error_log_at[h]=time.time()
      try:journal("source_error",None,{"source":"TruthSocialPublic","handle":h,"error":err,"rate_limited":limited,"retry_after_seconds":backoff})
      except Exception:pass
   with LOCK:
    states=[S["sources"].get("TruthDirect:"+h,{}) for h in handles]
    initialized=sum(bool(v) for v in states);good=sum(bool(v.get("ok")) for v in states);rt=sum(bool(v.get("realtime_verified")) for v in states)
    truth_healthy=initialized==len(handles) and good>=max(1,math.ceil(len(handles)*0.75))
    S["sources"]["TruthMonitor"]={"ok":truth_healthy,"degraded":not truth_healthy,"all_accounts_ok":initialized==len(handles) and good==len(handles),"mode":"public_parallel_adaptive_poll","last_check":now(),"accounts_ok":good,"accounts_initialized":initialized,"accounts_total":len(handles),"poll_seconds":poll,"scan_workers":pool._max_workers,"inflight_accounts":len(inflight),"backoff_accounts":sum(1 for h in handles if time.monotonic()<backoff_until.get(h,0)),"realtime_accounts_seen":rt,"realtime_verified":rt>0,"last_successful_poll_epoch":max(last_success.values()) if last_success else None}
   SHUTDOWN.wait(0.05)
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
 load_latest_learning()
 last_day=None
 while not SHUTDOWN.is_set():
  try:
   day=datetime.datetime.now(datetime.timezone.utc).date().isoformat()
   # Refresh on startup and then once per UTC day; persist every learning state.
   if last_day!=day:
    save_learning_snapshot();last_day=day
  except Exception as e:
   with LOCK:S["last_error"]="adaptive: "+str(e)[:160]
  SHUTDOWN.wait(900)

def research_page_monitor(source,url):
 delay=60
 while not SHUTDOWN.is_set():
  try:
   raw,transport=_fetch_news_xml(url,timeout=8)
   text=raw.decode("utf-8","replace")
   # Direct publisher page health. Trading content from these firms is also
   # covered by their X accounts; this avoids turning stale research archives
   # into fresh trade signals on restart.
   links=re.findall(r'<a[^>]+href=["\\\']([^"\\\']+)["\\\'][^>]*>(.*?)</a>',text,re.I|re.S)
   titles=[]
   for href,label in links:
    clean=htmlmod.unescape(re.sub(r"<[^>]+>"," ",label))
    clean=re.sub(r"\\s+"," ",clean).strip()
    if len(clean)>=24 and len(clean)<=220:titles.append(clean)
   with LOCK:S["sources"][source]={"ok":True,"last_check":now(),"mode":"direct_research_page","transport":transport,
      "items_detected":len(set(titles)),"realtime_verified":False,"error":None}
   delay=120
  except Exception as exc:
   err=str(exc)[:220]
   with LOCK:S["sources"][source]={"ok":False,"last_check":now(),"mode":"direct_research_page","error":err}
   try:journal("source_error",None,{"source":source,"kind":"research_page","error":err})
   except Exception:pass
   delay=min(600,max(120,delay*1.7))
  SHUTDOWN.wait(delay)

def _news_candidates(url):
 parsed=urllib.parse.urlsplit(url)
 if parsed.hostname=="news.google.com":
  query=urllib.parse.parse_qs(parsed.query)
  q=(query.get("q") or [""])[0].strip()
  if "when:" not in q:q=(q+" when:1h").strip()
  g=urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode({"q":q,"hl":"en-US","gl":"US","ceid":"US:en"})))
  # Independent search-RSS fallback so Google outages/rate limits do not blind PANDORA.
  clean_q=q.replace(" when:1h","")
  b="https://www.bing.com/news/search?"+urllib.parse.urlencode({"q":clean_q,"format":"rss","setlang":"en-us"})
  y="https://news.search.yahoo.com/rss?"+urllib.parse.urlencode({"p":clean_q})
  return [("google_news",g),("bing_news",b),("yahoo_news",y)]
 return [("direct_rss",url)]

def _fetch_news_xml(url,timeout=7):
 errors=[]
 try:
  req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; PANDORA/1.0)","Accept":"application/rss+xml,application/xml,text/xml,*/*","Cache-Control":"no-cache"})
  with urllib.request.urlopen(req,timeout=timeout) as r:return r.read(2_500_000),"urllib"
 except Exception as exc:errors.append("urllib:"+str(exc)[:100])
 try:
  r=curl_requests.get(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/rss+xml,application/xml,text/xml,*/*","Cache-Control":"no-cache"},impersonate="chrome",timeout=timeout)
  if int(r.status_code)!=200:raise RuntimeError("http_"+str(r.status_code))
  body=bytes(r.content)
  if not body:raise RuntimeError("empty")
  return body,"browser_tls"
 except Exception as exc:errors.append("browser:"+str(exc)[:100])
 raise RuntimeError(" | ".join(errors))

def whitehouse_official_realtime():
 urls=[
  "https://www.whitehouse.gov/news/",
  "https://www.whitehouse.gov/releases/",
  "https://www.whitehouse.gov/briefings-statements/",
 ]
 seen=set();primed=False
 link_re=re.compile(r'<a[^>]+href=["\\\']([^"\\\']+)["\\\'][^>]*>(.*?)</a>',re.I|re.S)
 article_path=re.compile(r"/(?:releases|briefings-statements|fact-sheets|presidential-actions|remarks)/20\\d{2}/\\d{2}/[^/?#]+/?$",re.I)
 def fetch_page(url):
  req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; PANDORA/1.0)","Cache-Control":"no-cache"})
  with urllib.request.urlopen(req,timeout=6) as r:return r.read(2_500_000).decode("utf-8","replace")
 def parse_listing(raw,base):
  out=[]
  for href,label in link_re.findall(raw):
   full=urllib.parse.urljoin(base,htmlmod.unescape(href))
   if not article_path.search(urllib.parse.urlsplit(full).path):continue
   title=htmlmod.unescape(re.sub(r"<[^>]+>"," ",label))
   title=re.sub(r"\\s+"," ",title).strip()
   if 12<=len(title)<=280:out.append((full,title))
  dedup={}
  for u,t in out:dedup[u]=t
  return list(dedup.items())[:80]
 def article_meta(url,fallback_title):
  try:
   raw=fetch_page(url)
   title=fallback_title
   m=re.search(r'<meta[^>]+property=["\\\']og:title["\\\'][^>]+content=["\\\']([^"\\\']+)',raw,re.I)
   if m:title=htmlmod.unescape(m.group(1)).strip()
   patterns=[
    r'<meta[^>]+property=["\\\']article:published_time["\\\'][^>]+content=["\\\']([^"\\\']+)',
    r'<meta[^>]+name=["\\\']date["\\\'][^>]+content=["\\\']([^"\\\']+)',
    r'<time[^>]+datetime=["\\\']([^"\\\']+)'
   ]
   pub=None
   for p in patterns:
    q=re.search(p,raw,re.I)
    if q:pub=htmlmod.unescape(q.group(1)).strip();break
   return title,pub
  except Exception:return fallback_title,None
 pool=concurrent.futures.ThreadPoolExecutor(max_workers=3,thread_name_prefix="whitehouse-official")
 while not SHUTDOWN.is_set():
  if not S["engine_active"]:
   SHUTDOWN.wait(0.5);continue
  started=time.monotonic()
  try:
   futures={pool.submit(fetch_page,u):u for u in urls};items=[];errors=[]
   for fut,u in futures.items():
    try:items.extend(parse_listing(fut.result(),u))
    except Exception as exc:errors.append(type(exc).__name__+":"+str(exc)[:80])
   current={u for u,_ in items}
   if not primed:
    seen=set(current);fresh=[];primed=True
   else:
    fresh=[(u,t) for u,t in items if u not in seen];seen.update(current)
    if len(seen)>1000:seen=set(list(seen)[-700:])
   ingested=0
   for u,t in fresh[:20]:
    title,pub=article_meta(u,t)
    # Do not invent a publication timestamp: missing metadata means the item is
    # journalled by source health only and cannot become a trade.
    if not pub:
     journal("whitehouse_item_missing_timestamp",None,{"url":u,"title":title})
     continue
    ident=hashlib.sha256(("WhiteHouseOfficial:"+u).encode()).hexdigest()
    ingested+=bool(ingest_event(ident,"WhiteHouseOfficial",title,pub,u))
   with LOCK:S["sources"]["WhiteHouseOfficial"]={"ok":bool(items),"last_check":now(),
    "mode":"official_whitehouse_pages","poll_seconds":WHITEHOUSE_POLL_SECONDS,
    "pages":len(urls),"items":len(items),"new":ingested,"request_seconds":round(time.monotonic()-started,2),
    "realtime_verified":False,"error":" | ".join(errors)[:180] if errors and not items else None}
  except Exception as exc:
   with LOCK:S["sources"]["WhiteHouseOfficial"]={"ok":False,"last_check":now(),"mode":"official_whitehouse_pages",
    "poll_seconds":WHITEHOUSE_POLL_SECONDS,"error":str(exc)[:180]}
  SHUTDOWN.wait(max(0.1,WHITEHOUSE_POLL_SECONDS-(time.monotonic()-started)))

def news_feed(source,url):
 # Every news source is isolated. Search feeds have an independent Bing RSS
 # fallback; direct publishers have browser-TLS fallback when urllib is blocked.
 candidates=_news_candidates(url)
 base_poll=max(15,NEWS_POLL_SECONDS) if candidates[0][0]=="direct_rss" else max(20,NEWS_POLL_SECONDS)
 delay=base_poll;error_log_at=0
 while not SHUTDOWN.is_set():
  errors=[];success=None
  for backend,candidate_url in candidates:
   try:
    raw,transport=_fetch_news_xml(candidate_url)
    root=ET.fromstring(raw);items=root.findall(".//item")[:40]
    if not items:
     # Atom fallback for publishers using <entry>.
     items=root.findall(".//{*}entry")[:40]
    if not items:raise RuntimeError("feed_empty")
    success=(backend,transport,items);break
   except Exception as exc:errors.append(backend+":"+str(exc)[:130])
  if success:
   backend,transport,items=success;count=0
   try:
    for item in reversed(items):
     if SHUTDOWN.is_set():break
     title=(item.findtext("title") or item.findtext("{*}title") or "").strip()
     if not title:continue
     pub=item.findtext("pubDate") or item.findtext("{*}published") or item.findtext("{*}updated")
     link=item.findtext("link")
     if not link:
      node=item.find("{*}link")
      if node is not None:link=node.get("href")
     ident=hashlib.sha256((source+title).encode()).hexdigest()
     count+=bool(ingest_event(ident,source,title,pub,link))
    with LOCK:S["sources"][source]={"ok":True,"last_check":now(),"new":count,"feed_items":len(items),
      "poll_seconds":base_poll,"mode":backend,"transport":transport,"fallback_used":backend!=candidates[0][0],
      "realtime_verified":False,"error":None}
    delay=base_poll
   except Exception as exc:
    errors.append("parse:"+str(exc)[:130]);success=None
  if not success:
   err=" | ".join(errors)[:350] or "feed_unavailable"
   with LOCK:
    S["errors"]+=1;S["last_error"]=source+": "+err[:180]
    S["sources"][source]={"ok":False,"last_check":now(),"error":err,"mode":"rss_with_fallbacks"}
   if time.time()-error_log_at>=120:
    error_log_at=time.time()
    try:journal("source_error",None,{"source":source,"kind":"news_feed","error":err})
    except Exception:pass
   delay=min(300,max(base_poll,delay*1.7))
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
  positions.append({"strategy":"NEWS","symbol":sym,"side":"LONG" if p["side"]>0 else "SHORT","entry":p["entry"],"mark":px,"notional_usd":round(p["notional"],2),"margin_usd":round(margin,2),"leverage":lev,"roe_pct":round(roi,3),"unrealized_pnl":round(pnl,4),"opened":p["opened"],"headline":p["headline"],"protection_stop":p.get("stop"),"trailing_stop":p.get("trail_stop"),"peak":p.get("peak"),"trailing_armed":p.get("trail_armed",False),"last_evaluated_at":p.get("last_evaluated_at")})
 pump_positions=[];pump_unreal=0.0
 whale_positions=[];whale_unreal=0.0
 for sym,p in state.get("whale_positions",{}).items():
  px=prices.get(sym,p["entry"]);move=(px/p["entry"]-1)*p["side"];gross=p["notional"]*move;fees=p["notional"]*FEE*2;pnl=gross-fees;whale_unreal+=pnl
  whale_positions.append({"strategy":"WHALE_LIQ","symbol":sym,"side":"LONG" if p["side"]>0 else "SHORT","entry":p["entry"],"mark":px,"notional_usd":round(p["notional"],2),"margin_usd":round(p["margin"],2),"leverage":p["leverage"],"roe_pct":round(pnl/p["margin"]*100,3) if p["margin"] else 0,"unrealized_pnl":round(pnl,4),"opened":p["opened"],"score":round(float(p.get("score",0)),2),"features":p.get("features",{})})
 for sym,p in state.get("pump_positions",{}).items():
  px=prices.get(sym,p["entry"]);move=(px/p["entry"]-1)*p["side"];gross=p["notional"]*move;fees=p["notional"]*FEE*2;pnl=gross-fees;pump_unreal+=pnl
  pump_positions.append({"strategy":"PUMP_DUMP","symbol":sym,"side":"LONG" if p["side"]>0 else "SHORT","entry":p["entry"],"mark":px,"notional_usd":round(p["notional"],2),"margin_usd":round(p["margin"],2),"leverage":p["leverage"],"roe_pct":round(pnl/p["margin"]*100,3) if p["margin"] else 0,"unrealized_pnl":round(pnl,4),"opened":p["opened"],"score":round(float(p.get("score",0)),2)})
 starts=[x.get("opened") for x in trades if x.get("opened")]+[x.get("opened") for x in positions if x.get("opened")]
 account_started=min(starts) if starts else now()
 try: account_age_seconds=max(0,int((datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(account_started.replace("Z","+00:00"))).total_seconds()))
 except Exception: account_age_seconds=0
 contributed=max(PAPER_RESET,float(state.get("contributed_capital",PAPER_RESET)));total=state["equity"]+unreal+pump_unreal+whale_unreal;account_roi=(total/contributed-1)*100
 used_margin=sum(float(p.get("margin",float(p.get("notional",0))/max(1.0,float(p.get("leverage",TRADE_LEVERAGE))))) for book in (state.get("positions",{}),state.get("pump_positions",{}),state.get("whale_positions",{})) for p in book.values())
 free_margin=max(0.0,float(state["equity"])-used_margin);margin_utilization=(used_margin/float(state["equity"])*100.0) if float(state["equity"])>0 else 0.0
 visible_sources={k:v for k,v in state["sources"].items() if not k.startswith("XIndex:") and k!="XIndexMonitor" and not k.startswith("XFree:") and k not in SEARCH_INDEX_FEEDS and not v.get("disabled") and not (k.startswith("TruthDirect:") and k!="TruthDirect:realDonaldTrump")}
 return {"mode":state["mode"],"balance":round(state["equity"],4),"capital_contributed":round(float(state.get("contributed_capital",PAPER_RESET)),4),"unrealized_pnl":round(unreal+pump_unreal+whale_unreal,4),"total_equity":round(total,4),"realized_pnl":round(state["realized_pnl"],4),"account_started":account_started,"account_age_seconds":account_age_seconds,"account_roi_pct":round(account_roi,3),"used_margin":round(used_margin,4),"free_margin":round(free_margin,4),"margin_utilization_pct":round(margin_utilization,3),"trade_margin_fraction_pct":round(TRADE_MARGIN_FRACTION*100,3),"trade_leverage":TRADE_LEVERAGE,"positions":positions+pump_positions+whale_positions,"pump_positions":pump_positions,"pump_unrealized_pnl":round(pump_unreal,4),"pump_trades":state.get("pump_trades",0),"whale_liq_positions":whale_positions,"whale_liq_unrealized_pnl":round(whale_unreal,4),"whale_liq_trades":state.get("whale_trades",0),"whale_liq_engine":copy.deepcopy(state.get("sources",{}).get("WhaleLiquidationScanner",{})),"account_model":"UNIFIED_PAPER_ACCOUNT","trades":trades,"news":newsrows,"features":feats,"sources":visible_sources,"errors":state["errors"],"last_error":state["last_error"],"news_seen":state["news_seen"],"market_count":state["market_count"],"last_poll":state["last_poll"],"uptime_seconds":int(time.time()-START),"engine_active":state["engine_active"],"engine_error":state["engine_error"],"last_checkpoint":state["last_checkpoint"],"last_market_error":state["last_market_error"],"news_max_age_seconds":NEWS_MAX_AGE_SECONDS,"market_structure_filter_active":False,"entry_rejections":dict(S.get("_entry_rejections",{})),"decision_counts":dict(S.get("_decision_counts",{})),"learning":copy.deepcopy(S.get("adaptive",{})),"version":os.getenv("RENDER_GIT_COMMIT","risk-state-v2")}

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
  "positions":positions,"pump_positions":[],"pump_balance":round(state.get("pump_equity",100.0),4),"pump_unrealized_pnl":0.0,"pump_total_equity":round(state.get("pump_equity",100.0),4),"pump_realized_pnl":round(state.get("pump_realized_pnl",0.0),4),"pump_trades":state.get("pump_trades",0),"trades":[],"news":[],"features":[],"sources":{k:v for k,v in state["sources"].items() if not k.startswith("XIndex:") and k!="XIndexMonitor" and not k.startswith("XFree:") and k not in SEARCH_INDEX_FEEDS and not v.get("disabled") and not (k.startswith("TruthDirect:") and k!="TruthDirect:realDonaldTrump")},
  "errors":state["errors"],"last_error":state["last_error"],"news_seen":state["news_seen"],
  "market_count":state["market_count"],"last_poll":state["last_poll"],
  "uptime_seconds":int(time.time()-START),"engine_active":state["engine_active"],
  "engine_error":state["engine_error"],"last_checkpoint":state["last_checkpoint"],
  "last_market_error":state["last_market_error"],"news_max_age_seconds":NEWS_MAX_AGE_SECONDS,
  "market_structure_filter_active":False,"version":os.getenv("RENDER_GIT_COMMIT","risk-state-v2")}

def daily_audit_stats():
 try:
  with pg() as c:
   trades_closed=c.execute("select count(*) as n from trade_history where closed::timestamptz >= date_trunc('day', now())").fetchone()["n"]
   trades_opened=c.execute("select count(*) as n from trade_history where opened::timestamptz >= date_trunc('day', now())").fetchone()["n"]
   news=c.execute("select count(*) as n from news_events where ts::timestamptz >= date_trunc('day', now())").fetchone()["n"]
   decisions=c.execute("select coalesce(payload->>'reason','unknown') as reason,count(*) as n from audit_journal where recorded_at::timestamptz >= date_trunc('day', now()) and kind='decision' group by 1 order by n desc limit 20").fetchall()
   skipped=c.execute("select coalesce(payload->>'reason','unknown') as reason,count(*) as n from audit_journal where recorded_at::timestamptz >= date_trunc('day', now()) and kind='entry_skipped' group by 1 order by n desc limit 20").fetchall()
   ignored=c.execute("select count(*) as n from audit_journal where recorded_at::timestamptz >= date_trunc('day', now()) and kind='ignored_non_market_news'").fetchone()["n"]
   bad=c.execute("select count(*) as n from bad_signal_feedback where recorded_at::timestamptz >= date_trunc('day', now())").fetchone()["n"]
   reversals=c.execute("select count(*) as n from audit_journal where recorded_at::timestamptz >= date_trunc('day', now()) and kind='news_reversal'").fetchone()["n"]
  return {"trades_closed_today_utc":int(trades_closed),"trades_opened_today_utc":int(trades_opened),"news_today_utc":int(news),"ignored_non_market_today_utc":int(ignored),"bad_signal_feedback_today_utc":int(bad),"news_reversals_today_utc":int(reversals),"decision_reasons_today_utc":{str(x["reason"]):int(x["n"]) for x in decisions},"entry_skips_today_utc":{str(x["reason"]):int(x["n"]) for x in skipped}}
 except Exception as exc:
  return {"error":str(exc)[:180]}

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
     "sources_failed":[k for k,v in S["sources"].items() if not v.get("ok") and not v.get("disabled") and not k.startswith("XFree:") and not k.startswith("XIndex:") and k!="XIndexMonitor" and k not in SEARCH_INDEX_FEEDS and not (k.startswith("TruthDirect:") and k!="TruthDirect:realDonaldTrump")],
     "sources_degraded_noncritical":[k for k,v in S["sources"].items() if not v.get("ok") and (k.startswith("XIndex:") or k=="XIndexMonitor")],
     "news_failures":{k:str(v.get("error") or "")[:160] for k,v in S["sources"].items() if not v.get("ok") and ((k in FEEDS and k not in SEARCH_INDEX_FEEDS and not k.startswith("XIndex:")) or k in RESEARCH_PAGES)},
     "social_channels":{k:{"ok":v.get("ok"),"degraded":v.get("degraded"),"mode":v.get("mode"),"posts":v.get("posts"),"last_check":v.get("last_check"),"error":v.get("error"),"realtime_verified":v.get("realtime_verified"),"latest_post_age_seconds":v.get("latest_post_age_seconds"),"delivery_latency_seconds":v.get("delivery_latency_seconds"),"accounts_ok":v.get("accounts_ok"),"accounts_initialized":v.get("accounts_initialized"),"accounts_total":v.get("accounts_total"),"active_accounts":v.get("active_accounts"),"scan_label":v.get("scan_label"),"key_accounts":v.get("key_accounts"),"disabled_retry_accounts":v.get("disabled_retry_accounts"),"recently_polled_accounts":v.get("recently_polled_accounts"),"target_poll_seconds":v.get("target_poll_seconds"),"backend_accounts":v.get("backend_accounts"),"rate_limited_accounts":v.get("rate_limited_accounts"),"backoff_accounts":v.get("backoff_accounts"),"scan_workers":v.get("scan_workers")} for k,v in S["sources"].items() if k in ("XMonitor","XCriticalMonitor","XFilteredStream","XListMonitor","TruthMonitor","TruthStream","TruthDirect:realDonaldTrump","TruthSocialPublic")},
     "pump_engine":copy.deepcopy(S["sources"].get("PumpDumpScanner",{})),
     "pump_positions":len(S.get("pump_positions",{})),"pump_trades":S.get("pump_trades"),"shared_account_equity":S.get("equity"),
     "whale_liq_engine":copy.deepcopy(S["sources"].get("WhaleLiquidationScanner",{})),
     "whale_liq_positions":len(S.get("whale_positions",{})),"whale_liq_trades":S.get("whale_trades"),"account_model":"UNIFIED_PAPER_ACCOUNT",
     "sizing_policy":{"margin_fraction":TRADE_MARGIN_FRACTION,"leverage":TRADE_LEVERAGE,"auto_topup_step":PAPER_TOPUP_STEP,"contributed_capital":S.get("contributed_capital",PAPER_RESET),"micro_analysis_threads":MICRO_ANALYSIS_THREADS},
     "entry_rejections":dict(S.get("_entry_rejections",{})),
     "daily_audit":daily_audit_stats(),
     "learning":{"samples":S.get("adaptive",{}).get("samples",0),"generated_at":S.get("adaptive",{}).get("generated_at"),"policy":S.get("adaptive",{}).get("policy")},
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
 cards='<div class="grid"><b>MODE<br>%s</b><b>ACCOUNT BALANCE<br>$ %s</b><b>CONTRIBUTED<br>$ %s</b><b>UNREALIZED P&L<br>$ %s</b><b>TOTAL EQUITY<br>$ %s</b><b>ACCOUNT ROI<br>%s%%</b><b>USED MARGIN<br>$ %s</b><b>FREE MARGIN<br>$ %s</b><b>MARGIN LOAD<br>%s%%</b><b>SIZE / LEV<br>%s%% / %sx</b><b>ACCOUNT AGE<br>%s</b><b>OPEN POSITIONS<br>%s</b><b>PUMP POSITIONS<br>%s</b><b>WHALE POSITIONS<br>%s</b></div>'%(esc(data["mode"]),data["balance"],data.get("capital_contributed",100),data["unrealized_pnl"],data["total_equity"],data["account_roi_pct"],data.get("used_margin",0),data.get("free_margin",0),data.get("margin_utilization_pct",0),data.get("trade_margin_fraction_pct",0),data.get("trade_leverage",TRADE_LEVERAGE),age_txt,len(data["positions"]),len(data.get("pump_positions",[])),len(data.get("whale_liq_positions",[])))
 pos="".join('<tr><td>%s</td><td>%s</td><td>$%s</td><td>$%s</td><td>%sx</td><td>%s</td><td>%s</td><td class="%s">%s%%</td><td class="%s">$%s</td><td>%s</td><td><button onclick="closePos(this.dataset.sym)" data-sym="%s">Close</button></td></tr>'%(esc(x["symbol"]),x["side"],x.get("margin_usd",0),x.get("notional_usd",0),x.get("leverage",LEV),x["entry"],x["mark"],"posv" if x.get("roe_pct",0)>=0 else "negv",x.get("roe_pct",0),"posv" if x["unrealized_pnl"]>=0 else "negv",x["unrealized_pnl"],esc(x["headline"]),esc(x["symbol"])) for x in data["positions"]) or '<tr><td colspan=11>No open positions</td></tr>'
 trs="".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(esc(x["closed"]),esc(x["symbol"]),"LONG" if x["side"]>0 else "SHORT",round(x["pnl"],4),esc(x["reason"])) for x in data["trades"]) or '<tr><td colspan=5>No closed trades</td></tr>'
 whale_engine=data.get("whale_liq_engine",{}) or {}
 whale_positions=data.get("whale_liq_positions",[]) or []
 whale_candidates=whale_engine.get("top_candidates",[]) or []
 whale_cards='<div class="grid"><b>WHALE SCANNER<br>%s</b><b>DANGER ZONE<br>%s</b><b>ELIGIBLE<br>%s</b><b>QUALIFIED<br>%s</b><b>OPEN WHALE POS<br>%s</b><b>SCAN<br>%ss</b></div>'%("OK" if whale_engine.get("ok") else "ERROR",whale_engine.get("danger_positions",0),whale_engine.get("eligible_candidates",0),whale_engine.get("qualified_candidates",0),len(whale_positions),whale_engine.get("scan_seconds","-"))
 whale_pos_html="".join('<tr><td>%s</td><td>%s</td><td>$%s</td><td>$%s</td><td>%sx</td><td>%s</td><td>%s</td><td class="%s">%s%%</td><td class="%s">$%s</td><td>%s</td></tr>'%(esc(x["symbol"]),x["side"],x["margin_usd"],x["notional_usd"],x["leverage"],x["entry"],x["mark"],"posv" if x["roe_pct"]>=0 else "negv",x["roe_pct"],"posv" if x["unrealized_pnl"]>=0 else "negv",x["unrealized_pnl"],x.get("score",0)) for x in whale_positions) or '<tr><td colspan=10>No whale liquidation positions</td></tr>'
 whale_candidates_html="".join('<tr><td>%s</td><td>%s</td><td>$%s</td><td>%s%%</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(esc(x.get("symbol","")),("LONG" if int(x.get("side",0))>0 else "SHORT"),round(float(x.get("whale_size_usd",0) or 0),2),round(float(x.get("distance_pct",0) or 0),4),round(float(x.get("score",0) or 0),2),esc(x.get("victim_side","")),esc(x.get("liquidation_price",""))) for x in whale_candidates) or '<tr><td colspan=7>No qualified whale candidates now</td></tr>'
 pump_pos="".join('<tr><td>%s</td><td>%s</td><td>$%s</td><td>$%s</td><td>%sx</td><td>%s</td><td>%s</td><td class="%s">%s%%</td><td class="%s">$%s</td><td>%s</td></tr>'%(esc(x["symbol"]),x["side"],x["margin_usd"],x["notional_usd"],x["leverage"],x["entry"],x["mark"],"posv" if x["roe_pct"]>=0 else "negv",x["roe_pct"],"posv" if x["unrealized_pnl"]>=0 else "negv",x["unrealized_pnl"],x.get("score",0)) for x in data.get("pump_positions",[])) or '<tr><td colspan=10>No pump/dump positions</td></tr>'
 src="".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(esc(k),(esc(v.get("scan_label")) if k=="XMonitor" and v.get("scan_label") else ("OK" if v.get("ok") else "ERROR")),esc(v.get("last_check","")),esc(v.get("error",""))) for k,v in data["sources"].items())
 news="".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(esc(x["ts"]),esc(x["source"]),esc(x["symbol"]),esc(x["signal"]),esc(x["title"])) for x in data["news"][:12])
 return '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>PANDORA LIVE</title><style>body{font-family:system-ui;background:#080b10;color:#e8edf5;margin:24px}h1{margin:0}.muted{color:#8b98aa}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:18px 0}.grid b{background:#111722;padding:16px;border-radius:12px}table{width:100%%;border-collapse:collapse;background:#0e141e;margin-bottom:22px}td,th{padding:9px;border-bottom:1px solid #202938;text-align:left;font-size:13px}th{color:#91a2b8}.posv{color:#49d17d;font-weight:700}.negv{color:#ff6262;font-weight:700}a{color:#8bc4ff}</style></head><body><h1>PANDORA LIVE</h1><div class="muted">Paper engine · dashboard refresh 5s · last market poll %s</div>%s<h2>Open positions</h2><button onclick="closePos(null)">Close Everything</button><button onclick="location.reload()">Refresh</button><p id="actionResult"></p><table><tr><th>Token</th><th>Side</th><th>Margin</th><th>Position</th><th>Lev</th><th>Entry</th><th>Mark</th><th>ROI%%</th><th>P&L</th><th>Trigger</th><th>Action</th></tr>%s</table><h2>Pump/Dump PAPER positions</h2><table><tr><th>Token</th><th>Side</th><th>Margin</th><th>Position</th><th>Lev</th><th>Entry</th><th>Mark</th><th>ROI%%</th><th>P&L</th><th>Score</th></tr>%s</table><h2>Whale Liquidation</h2>%s<table><tr><th>Token</th><th>Side</th><th>Margin</th><th>Position</th><th>Lev</th><th>Entry</th><th>Mark</th><th>ROI%%</th><th>P&L</th><th>Score</th></tr>%s</table><h3>Whale liquidation candidates</h3><table><tr><th>Token</th><th>Trade side</th><th>Whale size</th><th>Distance</th><th>Score</th><th>Victim</th><th>Liq price</th></tr>%s</table><h2>Closed trades</h2><table><tr><th>Closed</th><th>Token</th><th>Side</th><th>PnL</th><th>Reason</th></tr>%s</table><h2>Sources</h2><table><tr><th>Source</th><th>Status</th><th>Checked</th><th>Error</th></tr>%s</table><h2>Latest news</h2><table><tr><th>Time</th><th>Source</th><th>Token</th><th>Raw signal</th><th>Headline</th></tr>%s</table><p>Errors: %s · Last error: %s</p><p><a href="/api/dashboard">JSON dashboard</a> · <a href="/features">Features</a> · <a href="/trades">Trades</a> · <a href="/news">News</a></p><script>let closing=false;setInterval(()=>{if(!closing&&document.visibilityState==="visible")location.reload()},5000);async function closePos(sym){if(closing||!confirm(sym?"Close "+sym+"?":"Close ALL positions?"))return;closing=true;const status=document.getElementById("actionResult");status.textContent="Processing close request...";try{const r=await fetch("/api/positions/close",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify(sym?{symbol:sym}:{all:true})});const result=await r.json();status.textContent=r.ok?"Close confirmed: "+JSON.stringify(result):(r.status===401?"Controls locked: open the control-access link once, then retry.":"Close failed ("+r.status+"): "+JSON.stringify(result));if(r.ok){location.reload();return}}catch(e){status.textContent="Close request failed: "+String(e)}finally{closing=false}}</script></body></html>'''%(esc(data["last_poll"]),cards,pos,pump_pos,whale_cards,whale_pos_html,whale_candidates_html,trs,src,news,data["errors"],esc(data["last_error"]))


def manual_close(symbol=None,reason_override=None):
 with LOCK:
  all_symbols=set(S.get("positions",{}))|set(S.get("pump_positions",{}))|set(S.get("whale_positions",{}))
  targets=sorted(all_symbols) if symbol is None else [symbol]
 results=[]
 for sym in targets:
  with LOCK:
   news_pos=copy.deepcopy(S.get("positions",{}).get(sym))
   pump_pos=copy.deepcopy(S.get("pump_positions",{}).get(sym))
   whale_pos=copy.deepcopy(S.get("whale_positions",{}).get(sym))
   price=S.get("_prices",{}).get(sym)
  if not any((news_pos,pump_pos,whale_pos)):
   results.append({"symbol":sym,"ok":False,"error":"position_not_found"});continue
  if not price:
   pos=news_pos or pump_pos or whale_pos;price=pos.get("last_price") or pos.get("entry")
  reason=reason_override or ("manual_close_all" if symbol is None else "manual_close")
  if pump_pos:
   result=pump_close(sym,price,reason)
  elif whale_pos:
   result=whale_liq_close(sym,price,reason)
  else:
   result=STORE.close(sym,news_pos,price,reason)
   if result:
    with LOCK:
     S["equity"]=float(result["equity"]);S["realized_pnl"]=float(result["realized_pnl"]);S["trades"]+=1
     S["positions"].pop(sym,None)
  if result is None:
   results.append({"symbol":sym,"ok":False,"error":"close_not_committed"});continue
  results.append({"symbol":sym,"ok":True,"price":price,"pnl":result.get("pnl")})
 return {"ok":all(x["ok"] for x in results) if results else True,"results":results}


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
   body=b'{"ok":false,"error":"control_session_required","hint":"open monitor once with ?access=YOUR_CONTROL_TOKEN"}'
   self.send_response(401);self.send_header("Content-Type","application/json");self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body);return
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
 social={k:v for k,v in sources.items() if k in ("XMonitor","XCriticalMonitor","XFilteredStream","XListMonitor","TruthMonitor","TruthStream","TruthDirect:realDonaldTrump","TruthSocialPublic")}
 unavailable=[k for k,v in social.items() if not v.get("ok") and k not in ("XFilteredStream","XListMonitor","TruthStream","TruthSocialPublic")]
 return {"healthy":healthy,"risk_ready":ready,"news_sources_total":len(sources),"news_sources_failed":sum((not v.get("ok",False)) and not k.startswith(("XFree:","XIndex:")) and k!="XIndexMonitor" and k not in SEARCH_INDEX_FEEDS for k,v in sources.items()),"social_sources_failed":unavailable,"guest_x_realtime_verified":False,"news_24h_guaranteed":False,"engine_active":S["engine_active"],
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
 def supervised_worker(label,fn):
  while not SHUTDOWN.is_set():
   try:
    fn()
    if SHUTDOWN.is_set():return
    with LOCK:S["sources"]["Worker:"+label]={"ok":False,"degraded":True,"last_check":now(),"error":"worker_returned_restart"}
   except Exception as exc:
    with LOCK:S["sources"]["Worker:"+label]={"ok":False,"degraded":True,"last_check":now(),"error":type(exc).__name__+":"+str(exc)[:140]}
    try:journal("worker_restart",None,{"worker":label,"error":type(exc).__name__+":"+str(exc)[:180]})
    except Exception:pass
   SHUTDOWN.wait(2)

 worker_specs=[
  ("engine_coordinator",engine_coordinator),("market",market),("market_metadata",market_metadata),
  ("telemetry",telemetry),("pump_dump",impulse_scan),("whale_liquidations",whale_liquidation_scan),
  ("adapt",adapt),("x_critical_4s",x_critical_realtime),("truth_public",free_truth_realtime),("whitehouse_official",whitehouse_official_realtime),
  ("dashboard_cache",dashboard_cache_loop),("diagnostics",operations_diagnostics)
 ]
 if os.getenv("X_AUTH_TOKEN","").strip() and os.getenv("X_CT0","").strip() and os.getenv("X_LIST_ID","").strip():worker_specs.append(("x_list_official",x_list_realtime))
 if os.getenv("TRUTH_STREAM_TOKEN","").strip() or os.getenv("TRUTHSOCIAL_TOKEN","").strip() or (os.getenv("TRUTHSOCIAL_USERNAME","").strip() and os.getenv("TRUTHSOCIAL_PASSWORD","")):worker_specs.append(("truth_stream",truth_stream_realtime))
 if os.getenv("X_STREAM_BEARER_TOKEN","").strip():worker_specs.append(("x_filtered_stream",x_filtered_stream))
 if os.getenv("X_BEARER_TOKEN","").strip():worker_specs.append(("x_recent_search",xnews))
 if os.getenv("X_SESSION_COOKIES","").strip():worker_specs.append(("x_session_scraper",lambda:social_reader("x")))
 if os.getenv("TRUTHSOCIAL_TOKEN","").strip():worker_specs.append(("truth_auth_reader",lambda:social_reader("truth")))
 for name,url in FEEDS.items():
  if not name.startswith("XIndex:") and name not in SEARCH_INDEX_FEEDS:
   worker_specs.append(("feed:"+name,lambda n=name,u=url:news_feed(n,u)))
 for name,url in RESEARCH_PAGES.items():worker_specs.append(("research:"+name,lambda n=name,u=url:research_page_monitor(n,u)))
 if os.getenv("ENABLE_PUBLIC_X_HTML","0")=="1":
  for handle in WATCH:worker_specs.append(("public-x:"+handle,lambda h=handle:public_social_reader("x",h)))
 workers=[threading.Thread(target=supervised_worker,args=(label,fn),daemon=True,name=label) for label,fn in worker_specs]
 # Operator action is intentionally one-shot; normal completion is not a health failure.
 workers.append(threading.Thread(target=operator_one_shot_actions,daemon=True,name="operator_actions"))
 for worker in workers:worker.start()
 try:server.serve_forever()
 finally:
  SHUTDOWN.set();server.server_close()
  for worker in workers:worker.join(timeout=0.5)
  try:STORE.release()
  except Exception:pass