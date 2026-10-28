import html
import os,json,time,threading,urllib.request,urllib.parse,urllib.error,sqlite3,datetime,xml.etree.ElementTree as ET,re,hashlib,subprocess,html as htmlmod
import sqlite3,math,email.utils,secrets,signal,copy,concurrent.futures,functools
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
from momentum_scanner import (candidates as momentum_candidates, breadth_regime,
                              continuation_candidates, direction_guard, regime_candidate_guard)
from piq_direct import discover as piq_discover, fetch_story as piq_fetch_story, high_signal as piq_high_signal
from source_health import LatencyMetrics, aggregate_delivery
from market_data import RollingMarketData
from market_stream import run_trade_stream
from hyperliquid_transport import RestBudget, RestDeferred
from whale_signals import (MIN_NOTIONAL_USD, cluster_positions, summarize_book, significance, update_streaks,
                           PriceToValueTracker, price_to_value_entry, PRICE_TO_VALUE_POLICY)
from news_logic import analyze_headline, is_non_market_news as semantic_non_market
from accounting import paper_pnl
from strategy_stats import performance as strategy_performance, cards_html as strategy_cards_html, with_capital_basis as strategy_capital_basis
from strategy1_week_backtest import start as start_s1_week_backtest, status as s1_week_backtest_status
from local_caterpillar import (POLICY as CATERPILLAR_POLICY,pressure_exit as caterpillar_pressure_exit,
 update_watch as caterpillar_update_watch,reentry_ready as caterpillar_reentry_ready,
 protective_breakeven as caterpillar_breakeven, entry_candidate as local_entry_candidate,
 rank_candidates as rank_local_candidates, SELECTION_POLICY as LOCAL_SELECTION_POLICY)
from local_order_flow import m15_direction as local4_m15_direction
from local_order_flow import (POLICY as LOCAL4_FLOW_POLICY, entry_candidate as local4_entry_candidate,
 pressure_exit as local4_pressure_exit, update_watch as local4_update_watch, reentry_ready as local4_reentry_ready)
from learning_audit import (ensure_schema as ensure_learning_schema,
                            record_decision as record_learning_decision,
                            update_labels as update_learning_labels,
                            summary as learning_audit_summary)
from emergency_guard import reversal as emergency_reversal, profit_targets, COOLDOWN_SECONDS
from liquidation_stream import LiquidationTape, run as run_liquidation_stream, cascade_candidates
from hype_h1_swing import (POLICY as HYPE_SWING_POLICY, SYMBOL as HYPE_SWING_SYMBOL,
                           SYMBOLS as LOCAL_SWING_SYMBOLS, INTERVAL as HYPE_SWING_INTERVAL,
                           M15_INTERVAL as LOCAL_SWING_M15_INTERVAL, H1_CONTEXT_INTERVAL as LOCAL_SWING_H1_CONTEXT_INTERVAL,
                           STARTING_EQUITY as HYPE_SWING_STARTING_EQUITY,
                           MARGIN_FRACTION as HYPE_SWING_MARGIN_FRACTION, LEVERAGE as HYPE_SWING_LEVERAGE,
                           PROFIT_LOCK_ARM_MOVE as HYPE_PROFIT_LOCK_ARM_MOVE,
                           PROFIT_LOCK_BUFFER_MOVE as HYPE_PROFIT_LOCK_BUFFER_MOVE,
                           REENTRY_WATCH_SECONDS as LOCAL_REENTRY_WATCH_SECONDS,
                           REENTRY_MAX_PER_SWING as LOCAL_REENTRY_MAX_PER_SWING,
                           analyze as analyze_hype_h1, pending_extreme as local_pending_extreme, analyze_h1_context as analyze_local_h1_context,
                           analyze_m15 as analyze_local_m15,
                           m15_profit_protection as local_m15_profit_protection,
                           m15_reentry_ready as local_m15_reentry_ready,
                           m15_reentry_after_exit as local_m15_reentry_after_exit,
                           position_exit as hype_position_exit, update_path as hype_update_path,
                           profit_lock_exit as hype_profit_lock_exit, shadow_triggers as hype_shadow_triggers)

# Separate 24h Local paper experiment. Leverage follows Hyperliquid's live
# per-market maxLeverage metadata; validated fallbacks are only for metadata outages.
LOCAL_EXPERIMENT_SYMBOLS=("INIT","NEAR","GRASS","HYPE","BTC","ETH","SOL")
LOCAL_S3_SYMBOLS=("HYPE","NEAR","INIT","USELESS","GRASS","APT","TAO","CHIP","BABY","SPX","LIT","CASHCAT")
LOCAL_EXPERIMENT_STARTING_EQUITY=500.0
S1_ONLY_MODE=True
NEWS_NEW_ENTRIES_ENABLED=False
WHALE_NEW_ENTRIES_ENABLED=False
LOCAL_EXPERIMENT_MARGIN_FRACTION=0.20
LOCAL_EXPERIMENT_MAX_POSITIONS=7
# Legacy HYPE/NEAR book remains exit-only until its existing paper positions close.
VALIDATED_MAX_LEVERAGE={"BTC":50.0,"ETH":50.0,"SOL":20.0,"HYPE":10.0,"NEAR":10.0,"APT":10.0,"TAO":5.0,"SPX":5.0,"LIT":5.0,
 "INIT":3.0,"USELESS":3.0,"GRASS":3.0,"CHIP":3.0,"BABY":3.0,"CASHCAT":3.0}
ALL_LOCAL_CANDLE_SYMBOLS=tuple(dict.fromkeys(tuple(LOCAL_SWING_SYMBOLS)+LOCAL_EXPERIMENT_SYMBOLS+LOCAL_S3_SYMBOLS))

def market_max_leverage(symbol):
 with LOCK:
  raw=(S.get("_max_leverage") or {}).get(symbol)
 try:
  lev=float(raw)
  if math.isfinite(lev) and lev>=1:return lev
 except (TypeError,ValueError,OverflowError):pass
 return float(VALIDATED_MAX_LEVERAGE.get(symbol,1.0))

LATENCIES=LatencyMetrics()
MARKET_OBS=RollingMarketData(max_symbols=512)
LIQUIDATION_TAPE=LiquidationTape()
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
 # Live news path is intentionally minimal: FirstSquawk on X + PiQ Direct.
 # Other accounts are not required for health and cannot turn the scanner red.
 "critical":["FirstSquawk"]
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
 # No delayed Google/X index fallback in the trading path: stale indexed posts can create false entries.
 return []

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
S={"adaptive":{"samples":0,"changed":False},"mode":"PAPER_ONLY","orders_enabled":False,"last_poll":None,"market_count":0,"news_seen":0,"trades":0,"errors":0,"last_error":None,"sources":{},"positions":{},"equity":100.0,"realized_pnl":0.0,"pump_positions":{},"pump_equity":100.0,"pump_realized_pnl":0.0,"pump_trades":0,"pump_history_baseline":{},"whale_positions":{},"whale_equity":100.0,"whale_realized_pnl":0.0,"whale_trades":0,"local_swing_positions":{},"local_swing_watch":{},"hype_swing_position":None,"hype_swing_equity":100.0,"hype_swing_realized_pnl":0.0,"hype_swing_trades":0,"hype_swing_started_at":None,
"local_v12_positions":{},"local_experiment_watch":{},"local_experiment_equity":LOCAL_EXPERIMENT_STARTING_EQUITY,
"local_experiment_realized_pnl":0.0,"local_experiment_trades":0,"local_experiment_started_at":None,
"local_experiment_stats":{},
"local_s1_positions":{},"local_s1_watch":{},"local_s1_equity":500.0,"local_s1_realized_pnl":0.0,"local_s1_trades":0,
"local_s2_positions":{},"local_s2_equity":500.0,"local_s2_realized_pnl":0.0,"local_s2_trades":0,
"local_s3_positions":{},"local_s3_watch":{},"local_s3_equity":500.0,"local_s3_realized_pnl":0.0,"local_s3_trades":0,
"news_health":{}}
LOCK=threading.RLock()
ACCOUNT_LOCK=threading.RLock()
MARKET_REFRESH_LOCK=threading.Lock()
SHUTDOWN=threading.Event()
def account_mutation(fn):
 @functools.wraps(fn)
 def run(*args,**kwargs):
  # Serialize account writes without blocking price/health/source snapshots.
  with ACCOUNT_LOCK:return fn(*args,**kwargs)
 return run
TRADE_LEVERAGE=25.0
TRADE_MARGIN_FRACTION=0.10
POSITION_MARGIN_MAX=0.10
TARGET_OPEN_POSITIONS=max(1,min(20,int(os.getenv("TARGET_OPEN_POSITIONS","10"))))
MAX_OPEN_POSITIONS=max(TARGET_OPEN_POSITIONS,min(30,int(os.getenv("MAX_OPEN_POSITIONS","30"))))
PUMP_MAX_POSITIONS=max(TARGET_OPEN_POSITIONS,min(MAX_OPEN_POSITIONS,int(os.getenv("PUMP_MAX_POSITIONS","20"))))
PUMP_PRIMARY_SCORE=max(70.0,min(100.0,float(os.getenv("PUMP_PRIMARY_SCORE","84"))))
PUMP_SECONDARY_SCORE=max(60.0,min(PUMP_PRIMARY_SCORE,float(os.getenv("PUMP_SECONDARY_SCORE","76"))))
PUMP_SECONDARY_MARGIN_FRACTION=TRADE_MARGIN_FRACTION
PUMP_QUEUE_TTL_SECONDS=max(15.0,min(180.0,float(os.getenv("PUMP_QUEUE_TTL_SECONDS","60"))))
PUMP_SECONDARY_SAME_SIDE_CAP=max(1,min(TARGET_OPEN_POSITIONS,int(os.getenv("PUMP_SECONDARY_SAME_SIDE_CAP","4"))))
WHALE_MAX_ACTIVE_POSITIONS=max(1,min(5,int(os.getenv("WHALE_MAX_ACTIVE_POSITIONS","5"))))
WHALE_MARGIN_FRACTION=TRADE_MARGIN_FRACTION
WHALE_LEVERAGE=25.0
PROFIT_PROTECT_ARM_MOVE=max(0.002,float(os.getenv("PROFIT_PROTECT_ARM_MOVE","0.004")))
PROFIT_PROTECT_LOCK_MOVE=max(0.0010,min(PROFIT_PROTECT_ARM_MOVE,float(os.getenv("PROFIT_PROTECT_LOCK_MOVE","0.0012"))))
PROFIT_PROTECT_REVERSAL_MIN_MOVE=max(PROFIT_PROTECT_LOCK_MOVE,float(os.getenv("PROFIT_PROTECT_REVERSAL_MIN_MOVE","0.0012")))
PROFIT_PROTECT_R15=max(0.0005,float(os.getenv("PROFIT_PROTECT_R15","0.0012")))
PROFIT_PROTECT_R60=max(PROFIT_PROTECT_R15,float(os.getenv("PROFIT_PROTECT_R60","0.0022")))
PROFIT_PROTECT_FLOW=max(0.05,float(os.getenv("PROFIT_PROTECT_FLOW","0.12")))
NEWS_MAX_AGE_SECONDS=float(os.getenv("NEWS_MAX_AGE_SECONDS","120"))
NEWS_POLL_SECONDS=float(os.getenv("NEWS_POLL_SECONDS","15"))
WHITEHOUSE_POLL_SECONDS=max(10.0,float(os.getenv("WHITEHOUSE_POLL_SECONDS","15")))
PUMP_SCAN_SECONDS=max(1.0,float(os.getenv("PUMP_SCAN_SECONDS","2")))
MARKET_METADATA_SECONDS=max(180.0,float(os.getenv("MARKET_METADATA_SECONDS","180")))
MICRO_ANALYSIS_THREADS=max(1,min(10,int(os.getenv("MICRO_ANALYSIS_THREADS","10"))))
LIQ_WHALE_SCAN_SECONDS=max(3.0,float(os.getenv("LIQ_WHALE_SCAN_SECONDS","3")))
LIQ_WHALE_MAX_DISTANCE_PCT=max(0.5,float(os.getenv("LIQ_WHALE_MAX_DISTANCE_PCT","1.5")))
LIQ_WHALE_MIN_USD=max(100000.0,float(os.getenv("LIQ_WHALE_MIN_USD","2000000")))
LIQ_WHALE_SCORE_MIN=max(50.0,float(os.getenv("LIQ_WHALE_SCORE_MIN","76")))
LIQ_WHALE_MAX_POSITION_AGE_SECONDS=max(30.0,float(os.getenv("LIQ_WHALE_MAX_POSITION_AGE_SECONDS","180")))
LIQ_WHALE_MIN_BY_SYMBOL=dict(MIN_NOTIONAL_USD)
LIQ_WHALE_DEFAULT_MIN_USD=max(25_000.0,float(os.getenv("LIQ_WHALE_DEFAULT_MIN_USD","25000")))
LIQ_WHALE_MIN_BY_SYMBOL["__DEFAULT__"]=LIQ_WHALE_DEFAULT_MIN_USD
LIQ_WHALE_BASE_ENTRY_DISTANCE={"BTC":0.45,"ETH":0.60,"SOL":0.75}
LIQ_WHALE_DEFAULT_ENTRY_DISTANCE=max(0.35,min(LIQ_WHALE_MAX_DISTANCE_PCT,float(os.getenv("LIQ_WHALE_DEFAULT_ENTRY_DISTANCE","0.90"))))
LIQ_WHALE_LEV=TRADE_LEVERAGE
LIQ_WHALE_MARGIN_FRACTION=TRADE_MARGIN_FRACTION
LIQ_WHALE_SYMBOLS=set()
if not math.isfinite(NEWS_MAX_AGE_SECONDS) or NEWS_MAX_AGE_SECONDS<=0:raise ValueError("invalid news freshness window")
if not math.isfinite(NEWS_POLL_SECONDS) or NEWS_POLL_SECONDS<1:raise ValueError("invalid news poll interval")
S.update({"engine_active":False,"engine_error":None,"last_checkpoint":None,"last_market_error":None})
FEEDS={
 # Trading news ingestion is restricted to FirstSquawk + PiQ Direct.
 # Optional RSS feeds are disabled so stale/blocked feeds cannot degrade live health.
}
SEARCH_INDEX_FEEDS=set()
RESEARCH_PAGES={}

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
 "FedMonetary":1.00,"ECBOfficial":0.95,"WhiteHouseOfficial":1.00,
 "TruthSocialPublic":0.98,"XOfficial":0.92,"PiQDirect":0.96,
 "CoinDesk":0.90,"Cointelegraph":0.85
}
NON_MARKET_PATTERNS=(
 r"\\b(?:giveaway|sweepstakes|contest|competition)\\b",
 r"\\b(?:winner|winners|won|prize|award|awards)\\b",
 r"\\b(?:congratulations|congrats)\\b",
 r"\\b(?:tickets?|merch|merchandise)\\b",
 r"\\b(?:podcast|webinar|meetup)\\b",
)
def is_non_market_news(title):
 return semantic_non_market(title)

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
 elif source=="XOfficial:FirstSquawk":base=0.99
 elif source=="XOfficial:realDonaldTrump":base=1.00
 elif source in ("XOfficial:federalreserve","XOfficial:SECGov"):base=1.00
 elif source=="PiQDirect":base=0.96
 elif source.startswith("XOfficial:"):base=0.92
 elif source.startswith("TruthSocialPublic"):base=1.00
 else:base=float(SOURCE_WEIGHTS.get(source,0.50))
 learned=S.get("adaptive",{}).get("source_multipliers",{}) if S.get("mode")=="PAPER_ONLY" else {}
 return max(0.20,min(1.00,base*float(learned.get(source,1.0))))
def source_freshness_window(source):
 # Use the advertised publication-age limit consistently. Hidden 35s/60s
 # overrides discarded otherwise eligible posts received via public mirrors.
 return NEWS_MAX_AGE_SECONDS

STOP_ROE=-999.0;TAKE_ROE=0.20;LEV=25.0;MARGIN_FRACTION=0.10;FEE=0.00045;LOCK_TRIGGER_ROE=0.10;LOCK_ROE=0.075;PAPER_RESET=100.0;MIN_EXIT_ROE=0.075;TRAIL_ARM_ROE=0.12
PUMP_LEV=TRADE_LEVERAGE;PUMP_MARGIN_FRACTION=TRADE_MARGIN_FRACTION;PUMP_STOP_ROE=-0.06;PUMP_TAKE_ROE=0.14;PUMP_TRAIL_ARM_ROE=0.09;PUMP_TRAIL_GAP_ROE=0.035;PUMP_MAX_HOLD_SECONDS=900
PUMP_RESTORED_HISTORY_TRADES=26
PUMP_RESTORED_HISTORY_PNL=38.77481472248827
PUMP_RESTORED_HISTORY_ACTION="restore-pump-history-baseline-v1"
PUMP_RESTORED_HISTORY_TIMESTAMP="2026-10-26T08:18:24.779166+00:00"
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def pg():
 # Neon transaction pooling rejects statement_timeout in startup options.
 return psycopg.connect(os.environ["DATABASE_URL"],autocommit=True,row_factory=dict_row,connect_timeout=5)
STORE=EngineStore(pg,FEE,PAPER_RESET)
def pinit():
 with pg() as c:
  c.execute("create table if not exists local_candle_checkpoints (symbol text not null, interval text not null, candles jsonb not null, saved_at timestamptz not null default clock_timestamp(), primary key(symbol,interval))")
  c.execute("""create table if not exists local_s1_research_runs (
    run_id text primary key, created_at timestamptz not null default clock_timestamp(),
    start_date text not null, end_exclusive text not null, starting_equity double precision not null,
    final_equity double precision not null, realized_pnl double precision not null, open_pnl double precision not null,
    return_pct double precision not null, max_drawdown_pct double precision, closed_trades integer not null,
    wins integer not null, win_rate double precision, profit_factor double precision, policy text,
    research_only boolean not null default true, result jsonb not null default '{}'::jsonb)""")
  c.execute("""create table if not exists local_s1_research_trades (
    run_id text not null references local_s1_research_runs(run_id) on delete cascade, seq integer not null,
    opened timestamptz, closed timestamptz, symbol text not null, side integer not null,
    entry double precision not null, exit double precision not null, margin double precision not null,
    notional double precision not null, leverage double precision not null, pnl double precision not null,
    reason text, mfe_price_move double precision, mae_price_move double precision, equity_after double precision,
    research_only boolean not null default true, primary key(run_id,seq))""")
  for seed in c.execute("select symbol,interval,candles from local_candle_checkpoints").fetchall():
   accept_local_candles(seed["candles"],history=True)
  c.execute("create table if not exists account_state (id integer primary key, equity double precision not null, realized_pnl double precision not null, updated_at text not null)")
  c.execute("alter table account_state add column if not exists contributed_capital double precision not null default 100")
  c.execute("create table if not exists open_positions (symbol text primary key, side integer not null, entry double precision not null, notional double precision not null, opened text not null, opened_epoch double precision not null, headline text, locked boolean not null default false, stop double precision)")
  c.execute("alter table open_positions add column if not exists leverage double precision")
  c.execute("alter table open_positions add column if not exists margin double precision")
  c.execute("create table if not exists trade_history (id bigserial primary key, opened text, closed text, symbol text, side integer, entry double precision, exit double precision, pnl double precision, reason text, headline text)")
  c.execute("create table if not exists news_events (id text primary key, ts text, source text, title text, symbol text, signal integer)")
  c.execute("create table if not exists news_processing (event_id text primary key, state text not null default 'pending', processed_at text)")
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
  restored=c.execute("select payload from operator_actions where action_id=%s",(PUMP_RESTORED_HISTORY_ACTION,)).fetchone()
  if not restored:
   acct0=c.execute("select id from account_state where id=1").fetchone()
   if acct0:
    c.execute("update account_state set equity=equity+%s,realized_pnl=realized_pnl+%s,updated_at=%s where id=1",
      (PUMP_RESTORED_HISTORY_PNL,PUMP_RESTORED_HISTORY_PNL,now()))
    payload={"action":"restore_pump_history_baseline","strategy":"pump_dump",
      "restored_closed_trades":PUMP_RESTORED_HISTORY_TRADES,"restored_realized_pnl":PUMP_RESTORED_HISTORY_PNL,
      "source":"render_cleanup_log_2026-10-26T08:18:24.779166Z",
      "note":"Individual deleted trade rows unavailable; exact count and aggregate realized PnL restored."}
    c.execute("insert into operator_actions(action_id,completed_at,payload) values(%s,%s,%s::jsonb)",
      (PUMP_RESTORED_HISTORY_ACTION,now(),json.dumps(payload,default=str)))
  c.execute("create table if not exists pump_positions (symbol text primary key, side integer not null, entry double precision not null, notional double precision not null, margin double precision not null, leverage double precision not null, opened text not null, opened_epoch double precision not null, peak_roe double precision not null default 0, score double precision not null default 0, features jsonb not null default '{}'::jsonb)")
  c.execute("create table if not exists pump_trade_history (id bigserial primary key, opened text, closed text, symbol text, side integer, entry double precision, exit double precision, pnl double precision, reason text, score double precision, features jsonb)")
  c.execute("create table if not exists learning_snapshots (id bigserial primary key, recorded_at text not null, samples integer not null, payload jsonb not null)")
  c.execute("create table if not exists whale_liq_positions (symbol text primary key, side integer not null, entry double precision not null, notional double precision not null, margin double precision not null, leverage double precision not null, opened text not null, opened_epoch double precision not null, peak_roe double precision not null default 0, score double precision not null default 0, features jsonb not null default '{}'::jsonb)")
  c.execute("create table if not exists whale_liq_trade_history (id bigserial primary key, opened text, closed text, symbol text, side integer, entry double precision, exit double precision, pnl double precision, reason text, score double precision, features jsonb)")
  c.execute("create table if not exists whale_liq_signal_journal (id text primary key, ts text not null, symbol text, side integer, score double precision, action text, features jsonb)")
  c.execute("create table if not exists hype_swing_account_state (id integer primary key, equity double precision not null, realized_pnl double precision not null, started_at text not null, updated_at text not null)")
  c.execute("create table if not exists hype_swing_positions (symbol text primary key, side integer not null, entry double precision not null, notional double precision not null, margin double precision not null, leverage double precision not null, opened text not null, opened_epoch double precision not null, signal_candle_time bigint, features jsonb not null default '{}'::jsonb)")
  c.execute("create table if not exists hype_swing_trade_history (id bigserial primary key, opened text, closed text, symbol text, side integer, entry double precision, exit double precision, pnl double precision, reason text, margin double precision, notional double precision, leverage double precision, features jsonb)")
  c.execute("create table if not exists local_h1_direction (symbol text primary key, analysis jsonb not null)")
  S["local_h1_direction"]={r["symbol"]:r["analysis"] for r in c.execute("select symbol,analysis from local_h1_direction").fetchall()}
  c.execute("create table if not exists hype_swing_signal_journal (id text primary key, ts text not null, candle_time bigint, action text not null, side integer, price double precision, features jsonb not null default '{}'::jsonb)")
  c.execute("create table if not exists hype_swing_shadow_exits (id bigserial primary key, opened text not null, entry_candle_time bigint, side integer not null, entry double precision not null, extreme_exit_at text, extreme_exit_price double precision, weakening_exit_at text, weakening_exit_price double precision, actual_exit_at text, actual_exit_price double precision, actual_exit_reason text, status text not null default 'OPEN', context jsonb not null default '{}'::jsonb)")
  c.execute("alter table hype_swing_shadow_exits add column if not exists symbol text")
  c.execute("update hype_swing_shadow_exits set symbol='HYPE' where symbol is null")
  c.execute("""create table if not exists local_swing_watchlist (
    symbol text primary key, side integer not null, origin_signal_candle bigint, exit_price double precision,
    exit_at text not null, expires_epoch double precision not null, reentries integer not null default 0,
    context jsonb not null default '{}'::jsonb)""")
  c.execute("""create table if not exists local_v12_account_state (
    id integer primary key, equity double precision not null, realized_pnl double precision not null,
    started_at text not null, updated_at text not null)""")
  c.execute("""create table if not exists local_v12_positions (
    symbol text primary key, side integer not null, entry double precision not null, notional double precision not null,
    margin double precision not null, leverage double precision not null, opened text not null, opened_epoch double precision not null,
    signal_candle_time bigint, features jsonb not null default '{}'::jsonb)""")
  c.execute("""create table if not exists local_v12_trade_history (
    id bigserial primary key, opened text, closed text, symbol text, side integer, entry double precision, exit double precision,
    pnl double precision, reason text, margin double precision, notional double precision, leverage double precision,
    features jsonb not null default '{}'::jsonb)""")
  c.execute("""create table if not exists local_v12_watchlist (
    symbol text primary key, side integer not null, origin_signal_candle bigint, exit_price double precision,
    exit_at text not null, expires_epoch double precision not null default 0, reentries integer not null default 0,
    context jsonb not null default '{}'::jsonb)""")
  c.execute("""create table if not exists local_v12_signal_journal (
    id text primary key, ts text not null, candle_time bigint, action text not null, side integer, price double precision,
    features jsonb not null default '{}'::jsonb)""")
  # Two independent $500 paper comparison accounts.
  # Strategy 1 restores the profitable H1->M15 Caterpillar rules; Strategy 2 is pure H1 pivot-to-pivot.
  for prefix in ("local_s1","local_s2","local_s3"):
   c.execute(f"""create table if not exists {prefix}_account_state (
     id integer primary key, equity double precision not null, realized_pnl double precision not null,
     started_at text not null, updated_at text not null)""")
   c.execute(f"""create table if not exists {prefix}_positions (
     symbol text primary key, side integer not null, entry double precision not null, notional double precision not null,
     margin double precision not null, leverage double precision not null, opened text not null, opened_epoch double precision not null,
     signal_candle_time bigint, features jsonb not null default '{{}}'::jsonb)""")
   c.execute(f"""create table if not exists {prefix}_trade_history (
     id bigserial primary key, opened text, closed text, symbol text, side integer, entry double precision, exit double precision,
     pnl double precision, reason text, margin double precision, notional double precision, leverage double precision,
     features jsonb not null default '{{}}'::jsonb)""")
  c.execute("""create table if not exists local_s1_watchlist (
    symbol text primary key, side integer not null, origin_signal_candle bigint, exit_price double precision,
    exit_at text not null, reentries integer not null default 0, context jsonb not null default '{}'::jsonb)""")
  c.execute("""create table if not exists local_s3_watchlist (
    symbol text primary key, side integer not null, origin_signal_candle bigint, exit_price double precision,
    exit_at text not null, reentries integer not null default 0, context jsonb not null default '{}'::jsonb)""")
  c.execute("create index if not exists local_s1_trade_closed_idx on local_s1_trade_history(closed desc)")
  c.execute("create index if not exists local_s2_trade_closed_idx on local_s2_trade_history(closed desc)")
  c.execute("create index if not exists local_s3_trade_closed_idx on local_s3_trade_history(closed desc)")
  c.execute("create index if not exists local_experiment_trade_closed_idx on local_v12_trade_history(closed desc)")
  c.execute("create index if not exists local_experiment_signal_time_idx on local_v12_signal_journal(ts desc)")
  c.execute("create index if not exists hype_swing_trade_closed_idx on hype_swing_trade_history(closed desc)")
  c.execute("create index if not exists hype_swing_signal_time_idx on hype_swing_signal_journal(ts desc)")
  c.execute("create index if not exists hype_swing_shadow_open_idx on hype_swing_shadow_exits(status,opened)")
  c.execute("create table if not exists account_capacity_snapshots (id bigserial primary key, ts text not null, equity double precision not null, contributed_capital double precision not null, used_margin double precision not null, free_margin double precision not null, margin_utilization_pct double precision not null, news_positions integer not null, pump_positions integer not null, whale_positions integer not null, total_positions integer not null, entry_margin_fraction double precision not null)")
  c.execute("create table if not exists module_snapshots (id bigserial primary key, ts text not null, module text not null, ok boolean, state jsonb not null)")
  c.execute("create table if not exists position_snapshots (id bigserial primary key, ts text not null, strategy text not null, symbol text not null, opened text, side integer, entry double precision, mark double precision, margin double precision, notional double precision, leverage double precision, unrealized_pnl double precision, roe_pct double precision, peak double precision, exit_reason text, exit_check jsonb not null default '{}'::jsonb, features jsonb not null default '{}'::jsonb)")
  c.execute("create table if not exists scanner_observations (id bigserial primary key, ts text not null, module text not null, payload jsonb not null)")
  ensure_learning_schema(c)

  c.execute("create index if not exists audit_journal_event_idx on audit_journal(event_id,id)")
  c.execute("create index if not exists audit_journal_kind_time_idx on audit_journal(kind,recorded_at)")
  c.execute("create index if not exists news_events_time_idx on news_events(ts desc)")
  c.execute("create index if not exists market_context_symbol_time_idx on market_context_snapshots(symbol,ts desc)")
  c.execute("create index if not exists module_snapshots_module_time_idx on module_snapshots(module,ts desc)")
  c.execute("create index if not exists position_snapshots_symbol_time_idx on position_snapshots(symbol,ts desc)")
  c.execute("create index if not exists position_snapshots_strategy_time_idx on position_snapshots(strategy,ts desc)")
  c.execute("create index if not exists scanner_observations_module_time_idx on scanner_observations(module,ts desc)")
  row=c.execute("select equity,realized_pnl,contributed_capital from account_state where id=1").fetchone()
  if row:
   S["equity"]=float(row["equity"]);S["realized_pnl"]=float(row["realized_pnl"]);S["contributed_capital"]=float(row["contributed_capital"] or PAPER_RESET)
  else:
   c.execute("insert into account_state(id,equity,realized_pnl,updated_at,contributed_capital) values(1,%s,%s,%s,%s)",(S["equity"],S["realized_pnl"],now(),PAPER_RESET))
   S["contributed_capital"]=PAPER_RESET
  S["news_seen"]=c.execute("select count(*) as n from news_events").fetchone()["n"]
  baseline_row=c.execute("select payload from operator_actions where action_id=%s",(PUMP_RESTORED_HISTORY_ACTION,)).fetchone()
  baseline=(baseline_row["payload"] if baseline_row else {}) or {}
  baseline_trades=int(baseline.get("restored_closed_trades",0) or 0)
  baseline_pnl=float(baseline.get("restored_realized_pnl",0) or 0)
  pump_live=c.execute("select count(*) as n,coalesce(sum(pnl),0) as pnl from trade_history where strategy='pump_dump'").fetchone()
  S["trades"]=int(c.execute("select count(*) as n from trade_history").fetchone()["n"])+baseline_trades
  S["pump_equity"]=S["equity"]
  S["pump_realized_pnl"]=baseline_pnl+float(pump_live["pnl"] or 0)
  S["pump_trades"]=baseline_trades+int(pump_live["n"] or 0)
  S["pump_history_baseline"]={"restored_closed_trades":baseline_trades,"restored_realized_pnl":baseline_pnl,
    "source":baseline.get("source"),"exact_rows_available":False}
  ppositions={}
  for r in c.execute("select * from pump_positions").fetchall():
   ppositions[r["symbol"]]={"side":int(r["side"]),"entry":float(r["entry"]),"notional":float(r["notional"]),"margin":float(r["margin"]),"leverage":float(r["leverage"]),"opened":r["opened"],"t":float(r["opened_epoch"]),"peak_roe":float(r["peak_roe"] or 0),"score":float(r["score"] or 0),"features":r["features"] or {},**risk_state(r.get("risk_state") or {})}
  S["pump_positions"]=ppositions
  S["whale_equity"]=S["equity"];S["whale_realized_pnl"]=S["realized_pnl"]
  S["whale_trades"]=c.execute("select count(*) as n from trade_history where strategy='whale_liquidation'").fetchone()["n"]
  wpositions={}
  for r in c.execute("select * from whale_liq_positions").fetchall():
   wpositions[r["symbol"]]={"side":int(r["side"]),"entry":float(r["entry"]),"notional":float(r["notional"]),"margin":float(r["margin"]),"leverage":float(r["leverage"]),"opened":r["opened"],"t":float(r["opened_epoch"]),"peak_roe":float(r["peak_roe"] or 0),"score":float(r["score"] or 0),"features":r["features"] or {},**risk_state(r.get("risk_state") or {})}
  S["whale_positions"]=wpositions
  c.execute("insert into hype_swing_account_state(id,equity,realized_pnl,started_at,updated_at) values(1,%s,0,%s,%s) on conflict(id) do nothing",(HYPE_SWING_STARTING_EQUITY,now(),now()))
  hsacct=c.execute("select equity,realized_pnl,started_at from hype_swing_account_state where id=1").fetchone()
  S["hype_swing_equity"]=float(hsacct["equity"]);S["hype_swing_realized_pnl"]=float(hsacct["realized_pnl"]);S["hype_swing_started_at"]=hsacct["started_at"]
  hspositions={}
  for hsrow in c.execute("select * from hype_swing_positions").fetchall():
   hspositions[hsrow["symbol"]]={"side":int(hsrow["side"]),"entry":float(hsrow["entry"]),"notional":float(hsrow["notional"]),
    "margin":float(hsrow["margin"]),"leverage":float(hsrow["leverage"]),"opened":hsrow["opened"],"t":float(hsrow["opened_epoch"]),
    "signal_candle_time":int(hsrow["signal_candle_time"] or 0),"features":hsrow["features"] or {}}
  S["local_swing_positions"]=hspositions
  S["hype_swing_position"]=hspositions.get(HYPE_SWING_SYMBOL)
  watches={}
  for wr in c.execute("select * from local_swing_watchlist").fetchall():
   if True:  # H1 opposite pivot, rather than a timer, invalidates the watch
    watches[wr["symbol"]]={"symbol":wr["symbol"],"side":int(wr["side"]),"origin_signal_candle":int(wr["origin_signal_candle"] or 0),
      "exit_price":float(wr["exit_price"] or 0),"exit_at":wr["exit_at"],"expires_epoch":float(wr["expires_epoch"]),
      "reentries":int(wr["reentries"] or 0),"context":wr["context"] or {}}
   else:c.execute("delete from local_swing_watchlist where symbol=%s",(wr["symbol"],))
  S["local_swing_watch"]=watches
  S["hype_swing_trades"]=c.execute("select count(*) as n from hype_swing_trade_history").fetchone()["n"]

  c.execute("""insert into local_v12_account_state(id,equity,realized_pnl,started_at,updated_at)
    values(1,%s,0,%s,%s) on conflict(id) do nothing""",(LOCAL_EXPERIMENT_STARTING_EQUITY,now(),now()))
  exacct=c.execute("select equity,realized_pnl,started_at from local_v12_account_state where id=1").fetchone()
  S["local_experiment_equity"]=float(exacct["equity"]);S["local_experiment_realized_pnl"]=float(exacct["realized_pnl"])
  S["local_experiment_started_at"]=exacct["started_at"]
  expos={}
  for r in c.execute("select * from local_v12_positions").fetchall():
   expos[r["symbol"]]={"symbol":r["symbol"],"side":int(r["side"]),"entry":float(r["entry"]),"notional":float(r["notional"]),
    "margin":float(r["margin"]),"leverage":float(r["leverage"]),"opened":r["opened"],"t":float(r["opened_epoch"]),
    "signal_candle_time":int(r["signal_candle_time"] or 0),"features":r["features"] or {}}
  S["local_v12_positions"]=expos
  exwatches={}
  for r in c.execute("select * from local_v12_watchlist").fetchall():
   exwatches[r["symbol"]]={"symbol":r["symbol"],"side":int(r["side"]),"origin_signal_candle":int(r["origin_signal_candle"] or 0),
    "exit_price":float(r["exit_price"] or 0),"exit_at":r["exit_at"],"expires_epoch":float(r["expires_epoch"] or 0),
    "reentries":int(r["reentries"] or 0),"context":r["context"] or {}}
  S["local_experiment_watch"]=exwatches
  S["local_experiment_trades"]=int(c.execute("select count(*) as n from local_v12_trade_history").fetchone()["n"])
  for prefix,state_name in (("local_s1","local_s1"),("local_s2","local_s2"),("local_s3","local_s3")):
   c.execute(f"""insert into {prefix}_account_state(id,equity,realized_pnl,started_at,updated_at)
     values(1,500,0,%s,%s) on conflict(id) do nothing""",(now(),now()))
   acct=c.execute(f"select equity,realized_pnl from {prefix}_account_state where id=1").fetchone()
   S[state_name+"_equity"]=float(acct["equity"]);S[state_name+"_realized_pnl"]=float(acct["realized_pnl"])
   book={}
   for rr in c.execute(f"select * from {prefix}_positions").fetchall():
    book[rr["symbol"]]={"symbol":rr["symbol"],"side":int(rr["side"]),"entry":float(rr["entry"]),"notional":float(rr["notional"]),
      "margin":float(rr["margin"]),"leverage":float(rr["leverage"]),"opened":rr["opened"],"t":float(rr["opened_epoch"]),
      "signal_candle_time":int(rr["signal_candle_time"] or 0),"features":rr["features"] or {}}
   S[state_name+"_positions"]=book
   S[state_name+"_trades"]=int(c.execute(f"select count(*) as n from {prefix}_trade_history").fetchone()["n"])
  s1w={}
  for rr in c.execute("select * from local_s1_watchlist").fetchall():
   s1w[rr["symbol"]]={"symbol":rr["symbol"],"side":int(rr["side"]),"origin_signal_candle":int(rr["origin_signal_candle"] or 0),
     "exit_price":float(rr["exit_price"] or 0),"exit_at":rr["exit_at"],"reentries":int(rr["reentries"] or 0),"context":rr["context"] or {}}
  S["local_s1_watch"]=s1w
  s3w={}
  for rr in c.execute("select * from local_s3_watchlist").fetchall():
   s3w[rr["symbol"]]={"symbol":rr["symbol"],"side":int(rr["side"]),"origin_signal_candle":int(rr["origin_signal_candle"] or 0),
     "exit_price":float(rr["exit_price"] or 0),"exit_at":rr["exit_at"],"reentries":int(rr["reentries"] or 0),"context":rr["context"] or {}}
  S["local_s3_watch"]=s3w
 STORE.migrate()
 _,positions=STORE.load(recover_legacy=False)
 S["positions"]=positions
def journal(kind,event_id,payload):
 with pg() as c:c.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,%s,%s,%s::jsonb)",(now(),event_id,kind,json.dumps(payload,default=str)))
 # NEWS decisions and later entry vetoes share the durable event id, so the
 # learning row keeps the final reason while the raw audit journal remains lossless.
 if isinstance(payload,dict) and event_id and kind in ("decision","entry_skipped"):
  strategy=str(payload.get("strategy") or "news")
  if strategy=="news":
   side=payload.get("side")
   if side not in (-1,1):
    side=payload.get("effective_side") or payload.get("event_side") or payload.get("raw_side") or 0
   symbol=payload.get("symbol")
   with LOCK:live_price=S.get("_prices",{}).get(symbol) if symbol else None
   log_learning_decision("NEWS:"+str(event_id),"news",symbol,side,
    "SKIPPED" if kind=="entry_skipped" or payload.get("side") not in (-1,1) else "ELIGIBLE",
    payload.get("reason") or kind,payload.get("price") or live_price,payload.get("confidence"),
    TRADE_LEVERAGE,payload.get("features") or payload)
def log_learning_decision(decision_id,strategy,symbol,side,action,reason,entry_price=None,score=None,leverage=1.0,features=None,ts=None):
 try:
  return record_learning_decision(pg,decision_id,strategy,symbol,side,action,reason,entry_price,score,leverage,features,ts)
 except Exception as exc:
  with LOCK:S["last_error"]="decision_learning_write: "+type(exc).__name__+":"+str(exc)[:140]
  return False
def learning_shadow_loop():
 while not SHUTDOWN.is_set():
  try:
   with LOCK:
    active=bool(S.get("engine_active"));prices=dict(S.get("_prices",{}))
   if active and prices:
    labels=update_learning_labels(pg,prices,time.time(),1000)
    summary=learning_audit_summary(pg)
    state={**summary,**labels,"horizons":["5m","15m","1h","4h"],"counterfactual":True,
           "captures":["entered","skipped","rejected","mfe","mae","forward_roe"]}
    with LOCK:
     S["learning_audit"]=state
     S["sources"]["DecisionLearning"]={"ok":True,"last_check":now(),"mode":"durable_counterfactual_labels",
      "total":state.get("total",0),"complete":state.get("complete",0),"pending":state.get("pending",0),
      "horizons":state["horizons"],"error":None}
  except Exception as exc:
   with LOCK:S["sources"]["DecisionLearning"]={"ok":False,"last_check":now(),"mode":"durable_counterfactual_labels","error":type(exc).__name__+":"+str(exc)[:160]}
  SHUTDOWN.wait(30)
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
   row=c.execute("insert into news_events(id,ts,source,title,symbol,signal,published_at,source_url) values(%s,%s,%s,%s,%s,%s,%s,%s) on conflict(id) do nothing returning id",(ident,ts,source,title,symbol,signal,published_at,source_url)).fetchone()
   if row is None:return False
   c.execute("insert into news_processing(event_id,state) values(%s,'pending')",(ident,))
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

def save_module_snapshots():
 # Low-frequency durable state for week-long post-test reconstruction.
 # Event journals remain lossless for actual decisions/trades; this captures
 # scanner health, thresholds, candidate counts and source latency over time.
 tracked=("HypeH1LocalSwing","ConfirmedLiquidationStream","MarketBreadthHistory","CoinDesk","Cointelegraph","PumpDumpScanner","WhaleLiquidationScanner","DecisionLearning","XCriticalMonitor","XMonitor",
          "PiQDirect","MarketTradeStream","MarketMetadata","PersistentPostgres")
 with LOCK:
  rows=[(now(),name,bool(S.get("sources",{}).get(name,{}).get("ok")),
         copy.deepcopy(S.get("sources",{}).get(name,{})))
        for name in tracked if name in S.get("sources",{})]
 if not rows:return 0
 with pg() as c:
  for ts,name,ok,state in rows:
   c.execute("insert into module_snapshots(ts,module,ok,state) values(%s,%s,%s,%s::jsonb)",
             (ts,name,ok,json.dumps(state,default=str)))
 return len(rows)

def save_scanner_observation(module,payload):
 with pg() as c:c.execute("insert into scanner_observations(ts,module,payload) values(%s,%s,%s::jsonb)",(now(),module,json.dumps(payload,default=str)))

def save_position_snapshots(prices):
 # Snapshot every open PAPER position so a later audit can reconstruct the
 # full path to the local-extreme exit instead of seeing only entry/exit PnL.
 with LOCK:
  books=(("news",copy.deepcopy(S.get("positions",{}))),
         ("pump_dump",copy.deepcopy(S.get("pump_positions",{}))),
         ("whale_liquidation",copy.deepcopy(S.get("whale_positions",{}))),)
 rows=[]
 sampled_at=now()
 for strategy,book in books:
  for symbol,pos in book.items():
   try:
    entry=float(pos["entry"]);side=int(pos["side"]);lev=max(1.0,float(pos.get("leverage",TRADE_LEVERAGE)))
    margin=float(pos.get("margin",float(pos.get("notional",0))/lev))
    notional=float(pos.get("notional",margin*lev))
    mark=float(prices.get(symbol,pos.get("last_price",entry)))
    if not (math.isfinite(mark) and mark>0):continue
    pnl=paper_pnl(notional,entry,mark,side,FEE)
    roe=(pnl/margin*100.0) if margin>0 else 0.0
    exit_check=copy.deepcopy(pos.get("last_exit_check") or {})
    features=copy.deepcopy(pos.get("features") or {})
    if strategy=="news":
     features={**features,"event_id":pos.get("event_id"),"headline":pos.get("headline")}
    rows.append((sampled_at,strategy,symbol,pos.get("opened"),side,entry,mark,margin,notional,lev,pnl,roe,
                 pos.get("peak"),exit_check.get("reason"),exit_check,features))
   except (TypeError,ValueError,KeyError,OverflowError):
    continue
 if not rows:return 0
 with pg() as c:
  for row in rows:
   c.execute("""insert into position_snapshots
    (ts,strategy,symbol,opened,side,entry,mark,margin,notional,leverage,unrealized_pnl,roe_pct,peak,exit_reason,exit_check,features)
    values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
    (*row[:-2],json.dumps(row[-2],default=str),json.dumps(row[-1],default=str)))
 return len(rows)

def export_rows(kind,after,limit):
 columns={"journal":("audit_journal","id"),"news":("news_events","id"),
          "features":("event_features","id"),"trades":("trade_history","id"),
          "positions":("open_positions","symbol"),"pump_signals":("pump_signal_journal","id"),
          "pump_trades":("pump_trade_history","id"),"learning":("learning_snapshots","id"),
          "whale_signals":("whale_liq_signal_journal","id"),"whale_trades":("whale_liq_trade_history","id"),
          "capacity":("account_capacity_snapshots","id"),"modules":("module_snapshots","id"),
          "position_history":("position_snapshots","id"),"scanner_observations":("scanner_observations","id"),"decisions":("decision_learning_log","seq"),"operators":("operator_actions","action_id"),"hype_signals":("hype_swing_signal_journal","id"),"hype_trades":("hype_swing_trade_history","id")}
 if kind not in columns:raise ValueError("Unsupported export kind")
 table,key=columns[kind]
 cursor=int(after) if kind in ("journal","trades","pump_trades","learning","whale_trades","capacity","modules","position_history","decisions","hype_trades") else after
 with pg() as c:
  rows=c.execute(f"select * from {table} where {key}>%s order by {key} limit %s",(cursor,limit+1)).fetchall()
 return {"kind":kind,"rows":rows[:limit],"next_after":str(rows[limit-1][key]) if len(rows)>limit else None,"has_more":len(rows)>limit}
def persistent_news(limit=50):
 with pg() as c:return c.execute("select ts,source,title,symbol,signal,published_at,source_url from news_events order by ts desc limit %s",(limit,)).fetchall()
def persistent_features(limit=100):
 with pg() as c:return c.execute("select ts,source,title,symbol,decision,confidence,features from event_features order by ts desc limit %s",(limit,)).fetchall()
HL_REST_BUDGET=RestBudget(limit=250)

def get(url,body=None):
 data=None if body is None else json.dumps(body).encode()
 req=urllib.request.Request(url,data=data,headers={"User-Agent":"Mozilla/5.0 PANDORA-research/1.0","Content-Type":"application/json"})
 if url==API:HL_REST_BUDGET.acquire(body or {})
 try:
  with urllib.request.urlopen(req,timeout=4 if url==API else 8) as r:result=r.read()
 except urllib.error.HTTPError as exc:
  if url==API and exc.code==429:HL_REST_BUDGET.limited(exc.headers.get("Retry-After") if exc.headers else None)
  raise
 if url==API:HL_REST_BUDGET.success()
 return result
def init():
 with sqlite3.connect(DB) as c:
  c.execute("create table if not exists news (id text primary key,ts text,source text,title text,symbol text,signal integer)")
  c.execute("create table if not exists trades (id integer primary key autoincrement,opened text,closed text,symbol text,side integer,entry real,exit real,pnl real,reason text,headline text)")
  c.execute("create table if not exists snapshots (ts text,markets integer,equity real,positions integer)")
  c.execute("create table if not exists event_features (id text primary key,ts text,source text,title text,symbol text,decision integer,confidence real,features text)")
def apply_local4_user_reset():
 # Explicit user-authorized reset, fenced after takeover, exactly once.
 action="user-caterpillar-1-0-reset-20261027"
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   if db.execute("select 1 from operator_actions where action_id=%s",(action,)).fetchone():return False
   cleared={}
   for table in ["hype_swing_positions","hype_swing_shadow_exits","hype_swing_signal_journal","hype_swing_trade_history","local_swing_watchlist","local_experiment_positions","local_experiment_signal_journal","local_experiment_trade_history","local_experiment_watchlist","local_v12_positions","local_v12_signal_journal","local_v12_trade_history","local_v12_watchlist","local_h1_direction","local_v12_learning_pre_v10_20261027","local_v12_positions_pre_v10_20261027","local_v12_signal_journal_pre_v10_20261027","local_v12_trade_history_pre_v10_20261027","local_v12_watchlist_pre_v10_20261027"]:
    if not db.execute("select to_regclass(%s) as name",(table,)).fetchone()["name"]:continue
    result=db.execute("delete from "+table)
    cleared[table]=result.rowcount
   db.execute("delete from trade_history where strategy like 'local%%' or strategy like 'hype%%'")
   db.execute("delete from decision_learning_log where strategy like 'local%%' or strategy like 'hype%%'")
   db.execute("delete from position_snapshots where strategy like 'local%%' or strategy like 'hype%%'")
   db.execute("delete from scanner_observations where module like 'local%%' or module like 'hype%%'")
   db.execute("""delete from audit_journal where kind like 'local%%' or kind like 'hype%%'
     or payload->>'strategy' like 'local%%' or payload->>'strategy' like 'hype%%'""")
   stamp=now()
   for table in ("local_v12_account_state","local_experiment_account_state"):
    db.execute("update "+table+" set equity=500,realized_pnl=0,started_at=%s,updated_at=%s where id=1",(stamp,stamp))
   db.execute("update hype_swing_account_state set equity=100,realized_pnl=0,started_at=%s,updated_at=%s where id=1",(stamp,stamp))
   db.execute("delete from local_candle_checkpoints where symbol not in ('INIT','NEAR','GRASS','HYPE','BTC','ETH','SOL')")
   payload={"symbols":list(LOCAL_EXPERIMENT_SYMBOLS),"starting_equity":500,"margin_fraction":.20,
            "leverage":25,"policy":LOCAL4_FLOW_POLICY,"cleared":cleared}
   db.execute("insert into operator_actions(action_id,completed_at,payload) values(%s,%s,%s::jsonb)",(action,stamp,json.dumps(payload)))
 with LOCK:
  S["local_experiment_stats"]={};S["_dashboard_history"]={}
  S["_local4_analysis"]={};S["_local_experiment_path_persist_epoch"]={}
  S["local_swing_positions"]={};S["local_swing_watch"]={}
 return True

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
     with ACCOUNT_LOCK:
      if apply_local4_user_reset():pinit()
      account,positions=STORE.load()
      # Render keeps the previous instance alive briefly during a deploy. A
      # pre-start restoration can therefore be overwritten by the draining
      # instance. Re-arm the restored BTC short only after this instance owns
      # the fenced paper-engine lease, then persist the fresh local-search state.
      btc_rearm_payload=None
      btc=positions.get("BTC")
      if btc and int(btc.get("side",0))==-1 and abs(float(btc.get("entry",0))-80524.5)<0.01:
       with pg() as repair_db:
        repair_action="btc-post-lease-rearm-v1"
        done=repair_db.execute("select 1 from operator_actions where action_id=%s",(repair_action,)).fetchone()
       if not done:
        with LOCK:mark=float(S.get("_prices",{}).get("BTC") or btc.get("last_price") or btc["entry"])
        btc["peak"]=mark;btc["history"]=[mark];btc["last_price"]=mark
        btc["local_search_min_samples"]=30
        btc.pop("last_exit_check",None);btc.pop("last_evaluated_at",None)
        btc_rearm_payload={"symbol":"BTC","entry":btc["entry"],"mark":mark,
                           "local_search_min_samples":30,"reason":"post_lease_restore_rearm"}
      for sym,pos in positions.items():STORE.save(sym,pos)
      if btc_rearm_payload:
       with pg() as repair_db:
        with repair_db.transaction():
         STORE.fence(repair_db)
         repair_db.execute("""insert into operator_actions(action_id,completed_at,payload)
           values('btc-post-lease-rearm-v1',%s,%s::jsonb)
           on conflict(action_id) do nothing""",(now(),json.dumps(btc_rearm_payload,default=str)))
         repair_db.execute("""insert into audit_journal(recorded_at,event_id,kind,payload)
           values(%s,%s,'btc_post_lease_rearmed',%s::jsonb)""",
           (now(),btc.get("event_id"),json.dumps(btc_rearm_payload,default=str)))
      with pg() as db:
       capital=db.execute("select contributed_capital from account_state where id=1").fetchone()
       restored={}
       for key,table in (("pump_positions","pump_positions"),("whale_positions","whale_liq_positions")):
        restored[key]={r["symbol"]:{"side":int(r["side"]),"entry":float(r["entry"]),"notional":float(r["notional"]),"margin":float(r["margin"]),"leverage":float(r["leverage"]),"opened":r["opened"],"t":float(r["opened_epoch"]),"peak_roe":float(r["peak_roe"] or 0),"score":float(r["score"] or 0),"features":r["features"] or {},**risk_state(r.get("risk_state") or {})} for r in db.execute("select * from "+table).fetchall()}
      with LOCK:
       S.update(restored);S["positions"]=positions;S["equity"]=float(account["equity"]);S["realized_pnl"]=float(account["realized_pnl"])
       S["contributed_capital"]=float(capital["contributed_capital"]);S["last_checkpoint"]=now()
     journal("engine_restored",None,{"positions":list(positions),"risk_checkpoints":True})
    if not S.get("engine_active"):S["_engine_activated_epoch"]=time.time()
    S["engine_active"]=True;S["engine_error"]=None
   else:
    S["engine_active"]=False;S["engine_error"]="standby: another engine owns the lease"
  except Exception as e:
   S["engine_active"]=False;S["engine_error"]=str(e)[:180]
  SHUTDOWN.wait(5)
 S["engine_active"]=False
 try:STORE.release()
 except Exception:pass

def post_lease_historical_restore():
 # Routine deployments must preserve existing trading history and balances.
 # Historical repairs are a separate, explicitly enabled operator operation.
 if os.getenv("PANDORA_RUN_HISTORICAL_REPAIR","0")!="1":
  with LOCK:S["sources"]["HistoricalRestore"]={"ok":True,"disabled":True,"mode":"explicit_operator_repair_only","last_check":now()}
  return
 # A rolling Render deploy starts before the old instance has released the
 # single-writer lease. Historical repair must therefore run only *after* this
 # instance owns the lease; otherwise the draining instance can overwrite the
 # restored risk checkpoint with stale in-memory state.
 while not SHUTDOWN.is_set():
  with LOCK:active=bool(S.get("engine_active"))
  if not active:
   SHUTDOWN.wait(.5);continue
  try:
   with ACCOUNT_LOCK:
    with LOCK:
     if not S.get("engine_active"):continue
    import restore_positions
    restore_positions.main()
    # The repair mutates durable PAPER state directly. Reload every persistent
    # book before normal workers are allowed to mutate the account again.
    pinit()
    with LOCK:
     S["last_checkpoint"]=now()
     summary={"news_positions":len(S.get("positions",{})),
              "pump_positions":len(S.get("pump_positions",{})),
              "whale_positions":len(S.get("whale_positions",{})),
              "equity":S.get("equity")}
   journal("post_lease_historical_restore",None,summary)
   with LOCK:S["sources"]["HistoricalRestore"]={"ok":True,"last_check":now(),"mode":"post_lease_one_shot",**summary}
   return
  except Exception as exc:
   with LOCK:S["sources"]["HistoricalRestore"]={"ok":False,"last_check":now(),"mode":"post_lease_one_shot","error":type(exc).__name__+":"+str(exc)[:160]}
   SHUTDOWN.wait(2)

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
   result=manual_close(symbol,close_reason)
   if not result.get("ok"):
    SHUTDOWN.wait(2);continue
   with pg() as c:
    with c.transaction():
     completed=c.execute("insert into operator_actions(action_id,completed_at,payload) values(%s,%s,%s::jsonb) on conflict(action_id) do nothing returning action_id",
       (action_id,now(),json.dumps({"feedback":feedback,"close_result":result}))).fetchone()
     if completed and feedback_reason:c.execute("insert into bad_signal_feedback(recorded_at,event_id,symbol,headline,reason,payload) values(%s,%s,%s,%s,%s,%s::jsonb)",
       (now(),pos.get("event_id"),symbol,pos.get("headline"),feedback_reason,json.dumps(feedback)))
   journal("operator_position_closed",pos.get("event_id"),{"feedback":feedback,"close_result":result})
   return
  except Exception as exc:
   S["last_error"]="operator_action: "+str(exc)[:160]
   SHUTDOWN.wait(2)


@account_mutation
def exclude_authorized_pump_position(request):
 symbol=str(request["symbol"]);opened=str(request["opened"]);action_id=str(request["id"])
 with pg() as db:
  if db.execute("select 1 from operator_actions where action_id=%s",(action_id,)).fetchone():return True
 with LOCK:
  if not S.get("engine_active") or S.get("mode")!="PAPER_ONLY" or S.get("orders_enabled"):return False
  position=copy.deepcopy(S.get("pump_positions",{}).get(symbol));price=S.get("_prices",{}).get(symbol)
  if not price or time.time()-S.get("_last_poll_epoch",0)>10:return False
 if position and position.get("opened")==opened:
  if not pump_close(symbol,price,"operator_exclude_pump_test"):return False
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   if db.execute("select 1 from operator_actions where action_id=%s",(action_id,)).fetchone():return True
   rows=db.execute("delete from trade_history where strategy='pump_dump' and symbol=%s and opened=%s returning pnl,closed",(symbol,opened)).fetchall()
   reversed_pnl=sum(float(r["pnl"] or 0) for r in rows)
   db.execute("delete from pump_trade_history where symbol=%s and opened=%s",(symbol,opened))
   db.execute("delete from position_snapshots where strategy='pump_dump' and symbol=%s and opened=%s",(symbol,opened))
   db.execute("delete from pump_signal_journal where symbol=%s and ts::timestamptz between %s::timestamptz-interval '10 seconds' and %s::timestamptz+interval '10 seconds'",(symbol,opened,opened))
   db.execute("""delete from audit_journal where payload->>'symbol'=%s
     and kind in ('pump_trade_opened','pump_trade_closed')
     and (payload->>'opened'=%s or (not(payload ? 'opened') and kind='pump_trade_opened'
       and recorded_at::timestamptz between %s::timestamptz and %s::timestamptz+interval '10 seconds'))""",(symbol,opened,opened,opened))
   account=db.execute("update account_state set equity=equity-%s,realized_pnl=realized_pnl-%s,updated_at=%s where id=1 returning equity,realized_pnl",(reversed_pnl,reversed_pnl,now())).fetchone()
   counts=db.execute("select count(*) as total,count(*) filter(where strategy='pump_dump') as pump from trade_history").fetchone()
   payload={"action":"excluded_user_selected_pump_test","symbol":symbol,"excluded_trades":len(rows),
            "statistics_basis":"operator_filtered","requested_at":"2026-10-26"}
   db.execute("insert into operator_actions(action_id,completed_at,payload) values(%s,%s,%s::jsonb)",(action_id,now(),json.dumps(payload)))
 with LOCK:
  S["equity"]=float(account["equity"]);S["realized_pnl"]=float(account["realized_pnl"])
  S["trades"]=int(counts["total"]);S["pump_trades"]=int(counts["pump"])
  S["statistics_basis"]="operator_filtered_REZ_test_excluded"
  S["operator_cleanup"]={"ok":True,"action_id":action_id,"symbol":symbol,"excluded_trades":len(rows)}
 return True

def authorized_cleanup_worker():
 path=os.path.join(os.path.dirname(__file__),"operator_requests.json")
 if not os.path.exists(path):return
 try:
  with open(path) as source:
   payload=json.load(source)
  requests=payload.get("actions",[]) if isinstance(payload,dict) else []
 except Exception as exc:
  with LOCK:S["operator_cleanup"]={"ok":False,"ignored_invalid_operator_requests":True,"error":type(exc).__name__+":"+str(exc)[:120]}
  return
 while requests and not SHUTDOWN.is_set():
  for request in list(requests):
   try:
    kind=request.get("type")
    if kind=="EXCLUDE_OPEN_PUMP_LONGS":
     completed=exclude_authorized_pump_longs(request)
    elif kind=="EXCLUDE_PUMP_POSITION":
     completed=exclude_authorized_pump_position(request)
    else:continue
    if completed:
     with LOCK:
      S["statistics_basis"]="operator_filtered_pump_test_exclusions"
      if kind=="EXCLUDE_PUMP_POSITION":S["operator_cleanup"]={"ok":True,"action_id":request["id"],"symbol":request["symbol"]}
     requests.remove(request)
   except Exception as exc:
    with LOCK:S["operator_cleanup"]={"ok":False,"error":str(exc)[:160]}
  if requests:SHUTDOWN.wait(2)

@account_mutation
def exclude_authorized_pump_longs(request):
 action_id=str(request["id"])
 with LOCK:
  if not S.get("engine_active") or S.get("mode")!="PAPER_ONLY" or S.get("orders_enabled"):return False
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   prior=db.execute("select payload from operator_actions where action_id=%s for update",(action_id,)).fetchone()
   if prior:
    payload=prior["payload"]
   else:
    # Freeze the exact identities once. A crash/restart must not expand this
    # request to positions opened later under the repaired strategy.
    rows=db.execute("select symbol,opened from pump_positions where side=1 order by symbol").fetchall()
    payload={"stage":"pending","selected":[{"symbol":r["symbol"],"opened":r["opened"],
      "id":action_id+":"+hashlib.sha256((r["symbol"]+r["opened"]).encode()).hexdigest()[:16]} for r in rows],
      "statistics_basis":"operator_filtered"}
    db.execute("insert into operator_actions(action_id,completed_at,payload) values(%s,%s,%s::jsonb)",(action_id,now(),json.dumps(payload)))
 if payload.get("stage")!="done":
  for selected in payload["selected"]:
   if not exclude_authorized_pump_position(selected):return False
  payload["stage"]="done"
  with pg() as db:
   with db.transaction():
    STORE.fence(db)
    db.execute("update operator_actions set completed_at=%s,payload=%s::jsonb where action_id=%s",(now(),json.dumps(payload),action_id))
 with LOCK:
  S["statistics_basis"]="operator_filtered_pump_test_exclusions"
  S["operator_cleanup"]={"ok":True,"action_id":action_id,"selected":[{"symbol":r["symbol"],"opened":r["opened"]} for r in payload["selected"]]}
 return True

def _shared_used_margin():
 total=0.0
 local_book=S.get("local_swing_positions",{})
 if not local_book and S.get("hype_swing_position"):local_book={HYPE_SWING_SYMBOL:S["hype_swing_position"]}
 for book in (S.get("positions",{}),S.get("pump_positions",{}),S.get("whale_positions",{}),local_book):
  for p in book.values():
   lev=max(1.0,float(p.get("leverage",TRADE_LEVERAGE)))
   total+=float(p.get("margin",float(p.get("notional",0))/lev))
 total+=sum(float(x or 0) for x in S.get("_entry_reservations",{}).values())
 return total

def _symbol_open_anywhere(symbol):
 return (symbol in S.get("positions",{}) or symbol in S.get("pump_positions",{}) or symbol in S.get("whale_positions",{}) or symbol in S.get("local_swing_positions",{}))

@account_mutation
def _reserve_shared_entry(symbol,margin_fraction=None,strategy="shared"):
 with LOCK:
  reservations=S.setdefault("_entry_reservations",{})
  total_open=sum(len(S.get(k,{})) for k in ("positions","pump_positions","whale_positions","local_swing_positions"))
  reservation_key=symbol if strategy=="shared" else strategy+":"+symbol
  equity=float(S.get("equity",0) or 0)
  used=_shared_used_margin()
  free=max(0.0,equity-used)
  if total_open>=MAX_OPEN_POSITIONS:
   return False,0.0,"portfolio_position_cap",free
  if (strategy=="shared" and _symbol_open_anywhere(symbol)) or reservation_key in reservations:
   return False,0.0,"symbol_already_open_shared_account",free
  try:
   requested_fraction=float(margin_fraction) if margin_fraction is not None else TRADE_MARGIN_FRACTION
  except Exception:
   requested_fraction=TRADE_MARGIN_FRACTION
  fraction=max(0.01,min(1.0,requested_fraction))
  margin=max(0.01,max(0.0,equity)*fraction)
  if equity<=0:
   return False,0.0,"nonpositive_equity",free
  if used>equity+1e-9:
   return False,0.0,"portfolio_margin_over_cap",free
  if free+1e-9<margin:
   if strategy=="local_swing" and free>=0.01:
    margin=free
   else:
    return False,0.0,"insufficient_free_margin",free
  reservations[reservation_key]=margin
  return True,margin,None,free

def _release_shared_entry(symbol,strategy="shared"):
 key=symbol if strategy=="shared" else strategy+":"+symbol
 with LOCK:S.setdefault("_entry_reservations",{}).pop(key,None)

def liquidity_margin_fraction(symbol,features,base=None,regime=None):
 features["allocation_margin_fraction"]=TRADE_MARGIN_FRACTION
 features["allocation_policy"]="fixed_10pct_compound_shared_all_strategies_v5"
 if regime:
  features["market_regime"]=regime.get("mode")
  features["market_regime_side"]=regime.get("side",0)
 return TRADE_MARGIN_FRACTION

def current_entry_price(symbol):
 with LOCK:
  if not S["engine_active"] or S.get("mode")!="PAPER_ONLY" or S.get("orders_enabled") or SHUTDOWN.is_set():return None
  if time.time()-S.get("_last_poll_epoch",0)>10:return None
  checkpoint=publication_epoch(S.get("last_checkpoint"))
  if checkpoint is None or time.time()-checkpoint>15:return None
  price=S.get("_prices",{}).get(symbol)
  return float(price) if price is not None and math.isfinite(float(price)) and float(price)>0 else None

@account_mutation
def pump_open(symbol,side,price,score,features,margin_fraction=None):
 if side not in (-1,1) or not price:return False
 if features.get("observed_at_epoch") and not 0<=time.time()-features["observed_at_epoch"]<=10:return False
 price=current_entry_price(symbol)
 if price is None:return False
 if features.get("observed_at_epoch"):
  with LOCK:
   latest_prices=dict(S.get("_prices",{}));history={k:list(v) for k,v in S.get("_timeline",{}).items()}
   volumes=dict(S.get("_day_volumes",{}))
  regime=market_regime(latest_prices,history,volumes,time.time())
  rejection=regime_candidate_guard(features,regime) or direction_guard(symbol,side,latest_prices,history,time.time(),regime)
  if rejection:
   journal("entry_skipped",None,{"strategy":"pump_dump","symbol":symbol,"reason":rejection,"market_regime":regime.get("mode")})
   return False
  features=dict(features,entry_market_regime=regime.get("mode"),entry_market_regime_side=regime.get("side"),entry_direction_revalidated_at=now())
 with LOCK:
  if not S["engine_active"] or len(S["pump_positions"])>=PUMP_MAX_POSITIONS:return False
 reserved,margin,reason,free=_reserve_shared_entry(symbol,margin_fraction)
 if not reserved:
  journal("entry_skipped",None,{"strategy":"pump_dump","symbol":symbol,"reason":reason,"free_margin":free})
  return False
 try:
  price=current_entry_price(symbol)
  if price is None:return False
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
     (now(),json.dumps({"strategy":"pump_dump","symbol":symbol,"opened":opened,"side":side,"entry":price,"score":score,"margin":margin,"notional":notional,"leverage":TRADE_LEVERAGE},default=str)))
  with LOCK:S["pump_positions"][symbol]=pos
  return True
 finally:_release_shared_entry(symbol)

@account_mutation
def pump_close(symbol,price,reason):
 with LOCK:pos=copy.deepcopy(S["pump_positions"].get(symbol))
 if not pos or not price:return None
 pnl=paper_pnl(pos["notional"],pos["entry"],float(price),pos["side"],FEE)
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
    (now(),json.dumps({"strategy":"pump_dump","symbol":symbol,"opened":pos["opened"],"side":pos["side"],"entry":pos["entry"],"exit":price,"pnl":pnl,"reason":reason},default=str)))
 with LOCK:
  S["pump_positions"].pop(symbol,None);S["equity"]=float(account["equity"]);S["realized_pnl"]=float(account["realized_pnl"])
  S["pump_equity"]=S["equity"];S["pump_realized_pnl"]=float(S.get("pump_realized_pnl",0) or 0)+float(pnl);S["pump_trades"]+=1;S["trades"]+=1
 return {"pnl":pnl,"equity":float(account["equity"])}

@account_mutation
def pump_mark_positions(prices):
 # Local-extreme exit plus the global earned-profit protection overlay.
 with LOCK:
  positions=copy.deepcopy(S["pump_positions"])
  timelines={k:list(v) for k,v in S.get("_timeline",{}).items()}
 stamp=time.time()
 for sym,pos in positions.items():
  px=prices.get(sym)
  if not px:continue
  entry=float(pos["entry"]);side=int(pos["side"]);lev=float(pos["leverage"])
  # An earned-profit lock does not protect a position that never went positive.
  # Limit adverse mark moves and exit stale losing momentum positions in PAPER mode.
  adverse_move=(float(px)/entry-1.0)*side
  age_seconds=max(0.0,stamp-float(pos.get("t") or pos.get("opened_epoch") or stamp))
  hard_loss_price_pct=max(0.003,min(0.02,float(os.getenv("PUMP_HARD_LOSS_PRICE_PCT","0.008"))))
  stale_exit_seconds=max(900.0,float(os.getenv("PUMP_STALE_LOSS_SECONDS","3600")))
  stale_loss_price_pct=max(0.0005,float(os.getenv("PUMP_STALE_LOSS_PRICE_PCT","0.0015")))
  if adverse_move<=-hard_loss_price_pct:
   pump_close(sym,float(px),"pump_hard_adverse_move");continue
  if age_seconds>=stale_exit_seconds and adverse_move<=-stale_loss_price_pct:
   pump_close(sym,float(px),"pump_stale_losing_thesis");continue
  protected,protect_reason,protect_fill,protect_state=_profit_protection_eval(pos,sym,float(px),stamp,timelines.get(sym,[]))
  _profit_protection_arm_journal("pump_dump",sym,bool(pos.get("profit_lock_armed")),protected)
  if protect_reason:
   with LOCK:
    live=S["pump_positions"].get(sym)
    if live and live.get("opened")==pos.get("opened"):S["pump_positions"][sym]=protected
   pump_close(sym,protect_fill,protect_reason);continue
  prior_peak_roe=float(protected.get("peak_roe",0) or 0)
  peak_price=entry*(1+(prior_peak_roe/lev)*side)
  probe=copy.deepcopy(protected);probe["peak"]=peak_price
  evaluated,reason=evaluate_exit(probe,float(px),now())
  peak_price=float(evaluated.get("peak",entry));peak=(peak_price/entry-1)*side*lev
  with LOCK:
   if sym in S["pump_positions"]:
    S["pump_positions"][sym].update(risk_state(evaluated))
    S["pump_positions"][sym]["features"]=copy.deepcopy(evaluated.get("features",{}))
    S["pump_positions"][sym]["last_price"]=float(px);S["pump_positions"][sym]["peak_roe"]=peak
  if reason:
   pump_close(sym,px,"local_extreme_weakening");continue
  with pg() as db:
   with db.transaction():
    STORE.fence(db);db.execute("update pump_positions set peak_roe=%s,risk_state=%s::jsonb,features=%s::jsonb where symbol=%s and opened=%s",(peak,json.dumps(risk_state(evaluated)),json.dumps(evaluated.get("features",{}),default=str),sym,pos["opened"]))

@account_mutation
def whale_liq_open(symbol,side,price,score,features,margin_fraction=None):
 if not WHALE_NEW_ENTRIES_ENABLED:return False
 if S.get("mode")!="PAPER_ONLY" or S.get("orders_enabled") or side not in (-1,1) or not price:return False
 if features.get("observed_at_epoch") and not 0<=time.time()-features["observed_at_epoch"]<=10:return False
 price=current_entry_price(symbol)
 if price is None:return False
 with LOCK:
  if not S["engine_active"]:return False
  if len(S.get("whale_positions",{}))>=WHALE_MAX_ACTIVE_POSITIONS:return False
 # PriceToValueLiquidation sizes from total PAPER equity; the shared
 # reservation layer still enforces total used margin <= 100% equity.
 margin_fraction=WHALE_MARGIN_FRACTION
 features=copy.deepcopy(features)
 features["engine"]="price_to_value_liquidation"
 features["policy"]=PRICE_TO_VALUE_POLICY
 features["ptv_entry_distance_pct"]=float(features.get("distance_pct",0) or 0)
 features["ptv_distance_history_after_entry"]=[float(features.get("distance_pct",0) or 0)]
 features["ptv_widen_streak"]=0
 features["ptv_thesis_break_streak"]=0
 features["ptv_mfe_price_move"]=0.0
 features["ptv_mae_price_move"]=0.0
 features["allocation_margin_fraction"]=WHALE_MARGIN_FRACTION
 features["allocation_policy"]="price_to_value_liquidation_equity_fraction_v1"
 reserved,margin,reason,free=_reserve_shared_entry(symbol,margin_fraction)
 if not reserved:
  journal("entry_skipped",None,{"strategy":"whale_liquidation","symbol":symbol,"reason":reason,"free_margin":free})
  return False
 try:
  price=current_entry_price(symbol)
  if price is None:return False
  notional=margin*WHALE_LEVERAGE;opened=now();epoch=time.time()
  pos={"side":side,"entry":float(price),"notional":notional,"margin":margin,"leverage":WHALE_LEVERAGE,"opened":opened,"t":epoch,"peak_roe":0.0,"score":float(score),"features":features}
  with pg() as db:
   with db.transaction():
    STORE.fence(db)
    row=db.execute("""insert into whale_liq_positions(symbol,side,entry,notional,margin,leverage,opened,opened_epoch,peak_roe,score,features)
     values(%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s::jsonb) on conflict(symbol) do nothing returning symbol""",
     (symbol,side,price,notional,margin,WHALE_LEVERAGE,opened,epoch,float(score),json.dumps(features,default=str))).fetchone()
    if not row:return False
    db.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'whale_liq_trade_opened',%s::jsonb)",
     (now(),json.dumps({"strategy":"whale_liquidation","symbol":symbol,"side":side,"entry":price,"score":score,"margin":margin,"notional":notional,"leverage":WHALE_LEVERAGE,"features":features},default=str)))
  with LOCK:S["whale_positions"][symbol]=pos
  return True
 finally:_release_shared_entry(symbol)

@account_mutation
def whale_liq_close(symbol,price,reason):
 with LOCK:pos=copy.deepcopy(S["whale_positions"].get(symbol))
 if not pos or not price:return None
 pnl=paper_pnl(pos["notional"],pos["entry"],float(price),pos["side"],FEE)
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
    (pos["opened"],now(),symbol,pos["side"],pos["entry"],price,pnl,reason,"PRICE_TO_VALUE_LIQUIDATION",pos.get("score",0),features))
   c.execute("""insert into whale_liq_trade_history(opened,closed,symbol,side,entry,exit,pnl,reason,score,features)
    values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
    (pos["opened"],now(),symbol,pos["side"],pos["entry"],price,pnl,reason,pos.get("score",0),features))
   c.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'whale_liq_trade_closed',%s::jsonb)",
    (now(),json.dumps({"strategy":"whale_liquidation","symbol":symbol,"side":pos["side"],"entry":pos["entry"],"exit":price,"pnl":pnl,"reason":reason},default=str)))
 with LOCK:
  S["whale_positions"].pop(symbol,None);S["equity"]=float(account["equity"]);S["realized_pnl"]=float(account["realized_pnl"])
  S["whale_equity"]=S["equity"];S["whale_realized_pnl"]=S["realized_pnl"];S["whale_trades"]+=1;S["trades"]+=1
 return {"pnl":pnl,"equity":float(account["equity"])}

@account_mutation
def whale_liq_mark_positions(prices):
 with LOCK:
  positions=copy.deepcopy(S["whale_positions"])
  timelines={k:list(v) for k,v in S.get("_timeline",{}).items()}
  contexts=copy.deepcopy(S.get("_pump_ctx",{}))
 stamp=time.time();updates=[]
 for sym,pos in positions.items():
  px=prices.get(sym)
  if not px:continue
  entry=float(pos["entry"]);side=int(pos["side"]);lev=float(pos["leverage"])
  ctx=contexts.get(sym,{})
  mark=float(ctx.get("mark_price",0) or 0) or float(px)
  features=copy.deepcopy(pos.get("features",{}))
  liq=float(features.get("liquidation_price",0) or 0)
  victim=str(features.get("victim_side","")).lower()
  price_move=side*(mark/entry-1.0)
  features["ptv_mfe_price_move"]=max(float(features.get("ptv_mfe_price_move",0) or 0),price_move)
  features["ptv_mae_price_move"]=min(float(features.get("ptv_mae_price_move",0) or 0),price_move)

  # Touching the target must not disable risk if the liquidation fails to cascade.
  if price_move<=-0.008:
   with LOCK:
    live=S["whale_positions"].get(sym)
    if live and live.get("opened")==pos.get("opened"):live["features"]=features
   whale_liq_close(sym,float(px),"ptv_hard_adverse_move");continue

  reached=bool(liq>0 and ((victim=="long" and mark<=liq) or (victim=="short" and mark>=liq)))
  if reached and not features.get("liquidation_level_reached_at"):
   features["liquidation_level_reached_at"]=now()
   features["liquidation_level_reached_mark"]=mark
   features["pre_liquidation_hold_active"]=False
   features["post_liq_search_started_at"]=now()
   journal("whale_liq_level_reached",None,{"symbol":sym,"victim_side":victim,
    "liquidation_price":liq,"mark_price":mark,"entry":entry,"policy":PRICE_TO_VALUE_POLICY})
  if features.get("liquidation_level_reached_at") and liq>0:
   post_bps=max(0.0,side*(mark/liq-1.0)*10000.0)
   if post_bps>float(features.get("post_liq_max_favorable_bps",0) or 0):
    features["post_liq_max_favorable_bps"]=round(post_bps,2)

  pos["features"]=features
  protected,protect_reason,protect_fill,protect_state=_profit_protection_eval(pos,sym,float(px),stamp,timelines.get(sym,[]))
  _profit_protection_arm_journal("whale_liquidation",sym,bool(pos.get("profit_lock_armed")),protected)
  if protect_reason:
   with LOCK:
    live=S["whale_positions"].get(sym)
    if live and live.get("opened")==pos.get("opened"):S["whale_positions"][sym]=protected
   whale_liq_close(sym,protect_fill,protect_reason)
   continue
  pos=protected;features=copy.deepcopy(pos.get("features",{}))

  pre_liq=not features.get("liquidation_level_reached_at") and liq>0 and victim in ("long","short")
  if pre_liq:
   remaining=((mark/liq)-1.0)*100.0 if victim=="long" else ((liq/mark)-1.0)*100.0
   remaining=max(0.0,remaining)
   hist=[float(v) for v in features.get("ptv_distance_history_after_entry",[]) if v is not None][-11:]
   hist.append(remaining);features["ptv_distance_history_after_entry"]=hist[-12:]
   widening=len(hist)>=2 and hist[-1]>hist[-2]+0.015
   features["ptv_widen_streak"]=int(features.get("ptv_widen_streak",0) or 0)+1 if widening else 0
   flow=float(MARKET_OBS.context(sym,stamp).get("flow_imbalance") or 0)
   r15=_timeline_return(timelines.get(sym,[]),stamp,15,mark)
   r60=_timeline_return(timelines.get(sym,[]),stamp,60,mark)
   trend_against=(r15 is not None and r60 is not None and side*r15<=-0.00030 and side*r60<=-0.00060)
   flow_against=side*flow<=-0.08
   thesis_break=trend_against and (flow_against or int(features.get("ptv_widen_streak",0) or 0)>=2)
   features["ptv_thesis_break_streak"]=int(features.get("ptv_thesis_break_streak",0) or 0)+1 if thesis_break else 0
   features["ptv_remaining_to_liquidation_pct"]=remaining
   features["ptv_flow_against"]=bool(flow_against)
   features["ptv_trend_against"]=bool(trend_against)

   entry_dist=max(0.05,float(features.get("ptv_entry_distance_pct",remaining) or remaining))
   distance_invalid=(remaining>min(1.25,entry_dist+0.25))
   # Absolute thesis boundary cannot be disabled by flat ticks or sparse history.
   if price_move<=-0.008:distance_invalid=True
   thesis_invalid=int(features.get("ptv_thesis_break_streak",0) or 0)>=2
   peak_move=float(features.get("ptv_mfe_price_move",0) or 0)
   if peak_move>=0.0025:features["ptv_profit_lock_armed"]=True
   profit_lock=bool(features.get("ptv_profit_lock_armed")) and price_move<=max(0.0012,peak_move*0.50) and peak_move>=0.0025
   profit_weakening=price_move>=0.0012 and trend_against and flow_against

   pos["features"]=features
   if profit_lock:
    with LOCK:
     live=S["whale_positions"].get(sym)
     if live and live.get("opened")==pos.get("opened"):live["features"]=features
    whale_liq_close(sym,float(px),"ptv_profit_lock");continue
   if profit_weakening:
    with LOCK:
     live=S["whale_positions"].get(sym)
     if live and live.get("opened")==pos.get("opened"):live["features"]=features
    whale_liq_close(sym,float(px),"ptv_profit_weakening");continue
   if distance_invalid or thesis_invalid:
    with LOCK:
     live=S["whale_positions"].get(sym)
     if live and live.get("opened")==pos.get("opened"):live["features"]=features
    whale_liq_close(sym,float(px),"ptv_distance_invalidation" if distance_invalid else "ptv_thesis_break");continue

  roe=(float(px)/entry-1)*side*lev
  peak=max(float(pos.get("peak_roe",0) or 0),roe)
  peak_price=float(pos.get("peak",entry*(1+(peak/lev)*side)))
  probe=copy.deepcopy(pos);probe["peak"]=peak_price;probe["features"]=features
  evaluated,reason=evaluate_exit(probe,float(px),now())
  new_peak=float(evaluated.get("peak",entry));peak=(new_peak/entry-1)*side*lev
  state=risk_state(evaluated)
  with LOCK:
   live=S["whale_positions"].get(sym)
   if live and live.get("opened")==pos.get("opened"):
    live["features"]=copy.deepcopy(evaluated.get("features",features))
    live["peak_roe"]=peak
    live.update(state)
    live["last_price"]=float(px)
  if reason:
   whale_liq_close(sym,float(px),"ptv_post_liq_weakening")
   continue
  updates.append((peak,json.dumps(state,default=str),json.dumps(evaluated.get("features",features),default=str),sym,pos["opened"]))
 if updates:
  with pg() as db:
   with db.transaction():
    STORE.fence(db)
    with db.cursor() as cur:
     cur.executemany("""update whale_liq_positions
       set peak_roe=%s,risk_state=%s::jsonb,features=%s::jsonb
       where symbol=%s and opened=%s""",updates)

def _whale_liq_book(symbol):
 stamp=time.time()
 with LOCK:cached=copy.deepcopy(S.setdefault("_l2_book_cache",{}).get(symbol))
 if cached and stamp-float(cached.get("_cached_epoch",0) or 0)<=2.0:
  cached.pop("_cached_epoch",None);return cached
 try:
  book=json.loads(get(API,{"type":"l2Book","coin":symbol,"nSigFigs":4}))
  summary=summarize_book(book,depth_bps=10)
  if summary:
   stored=copy.deepcopy(summary);stored["_cached_epoch"]=stamp
   with LOCK:S.setdefault("_l2_book_cache",{})[symbol]=stored
  return summary
 except Exception:
  if cached and stamp-float(cached.get("_cached_epoch",0) or 0)<=5.0:
   cached.pop("_cached_epoch",None);return cached
  return None

def _whale_liq_cvd(symbol):
 observed=MARKET_OBS.context(symbol,time.time())
 return observed.get("cvd_1m") or 0.0,observed.get("flow_imbalance") or 0.0,observed.get("trade_coverage_seconds")

def whale_liquidation_scan():
 last_signal={};scan_id=0;ptv_tracker=PriceToValueTracker();rejection_totals={}
 pool=concurrent.futures.ThreadPoolExecutor(max_workers=10,thread_name_prefix="whale-book")
 try:
  while not SHUTDOWN.is_set():
   started=time.monotonic()
   try:
    with LOCK:
     active=bool(S.get("engine_active"))
     metadata_ready=bool(S.get("_day_volumes")) and bool(S.get("_max_leverage"))
    if not active:
     SHUTDOWN.wait(0.5);continue
    if not metadata_ready:
     with LOCK:S["sources"]["PumpDumpScanner"]={"ok":True,"ready":False,"warmup":True,"last_check":now(),
       "mode":"waiting_for_market_metadata","error":None}
     SHUTDOWN.wait(0.5);continue
    prices=refresh_market_prices(max_age=8.0)
    with LOCK:
     history={k:list(v) for k,v in S.get("_timeline",{}).items()}
     contexts=copy.deepcopy(S.get("_pump_ctx",{}))
    danger_error=None
    try:
     data=hyperdata("/v1/positions/danger-zone?threshold="+urllib.parse.quote(str(LIQ_WHALE_MAX_DISTANCE_PCT)))
     if not isinstance(data,dict) or not isinstance(data.get("positions"),list):
      raise RuntimeError("danger_zone_unavailable_or_invalid")
     rows=data["positions"]
    except Exception as exc:
     rows=[];danger_error=str(exc)[:180]

    stamp=time.time();scan_id+=1
    for sym in contexts:contexts[sym].update(MARKET_OBS.context(sym,stamp))
    clusters=cluster_positions(rows,prices,contexts,stamp,LIQ_WHALE_MAX_POSITION_AGE_SECONDS,LIQ_WHALE_MAX_DISTANCE_PCT)
    rejections={};eligible=[]
    def reject(reason):rejections[reason]=rejections.get(reason,0)+1

    for cluster in clusters:
     probe=significance(cluster,None,contexts.get(cluster["symbol"],{}),floors=LIQ_WHALE_MIN_BY_SYMBOL)
     if probe["reason"]=="missing_orderbook":eligible.append(cluster)
     else:reject(probe["reason"])

    jobs={sym:pool.submit(_whale_liq_book,sym) for sym in {p["symbol"] for p in eligible}}
    books={sym:None for sym in jobs}
    # One global deadline for the whole order-book phase. Sequential per-job
    # timeouts could stretch a nominal 3s scan into 8-15s when several venues lag.
    if jobs:
     done,pending=concurrent.futures.wait(set(jobs.values()),timeout=2.20)
     reverse={job:sym for sym,job in jobs.items()}
     for job in done:
      sym=reverse[job]
      try:books[sym]=job.result()
      except Exception:books[sym]=None
     for job in pending:
      job.cancel()

    raw_candidates=[]
    for p in eligible:
     sym=p["symbol"];side=p["trade_side"];ctx=contexts.get(sym,{});book=books.get(sym)
     p=dict(p,evaluated_at=time.time())
     material=significance(p,book,ctx,floors=LIQ_WHALE_MIN_BY_SYMBOL)
     if not material["allowed"]:
      reject(material["reason"]);continue

     r15=_timeline_return(history.get(sym,[]),stamp,15,prices[sym])
     r60=_timeline_return(history.get(sym,[]),stamp,60,prices[sym])
     r300=_timeline_return(history.get(sym,[]),stamp,300,prices[sym])
     r900=_timeline_return(history.get(sym,[]),stamp,900,prices[sym])
     if r15 is None or r60 is None:
      reject("insufficient_price_history");continue

     dist=p["distance_pct"];impact=float(material.get("liquidation_flow_to_depth",0) or 0)
     base_distance=LIQ_WHALE_BASE_ENTRY_DISTANCE.get(sym,LIQ_WHALE_DEFAULT_ENTRY_DISTANCE)
     dynamic=min(LIQ_WHALE_MAX_DISTANCE_PCT,base_distance+(0.10 if impact>=.5 else 0)+(0.15 if impact>=1 else 0)+(0.15 if impact>=2 else 0))
     flow=float(ctx.get("flow_imbalance") or 0)
     imb=float((book or {}).get("imbalance") or 0)
     spread=float((book or {}).get("spread_bps",9999) or 9999)
     vol_z=ctx.get("volume_rate_z")
     burst=float(ctx.get("volume_burst_ratio") or 0)
     oi=float(ctx.get("oi_delta_60s") or 0)
     book_ok=side*imb>=.03 and spread<=15
     flow_ok=side*flow>=.04
     participation_ok=burst>=1.15 or (vol_z is not None and float(vol_z)>=1.3)
     oi_ok=abs(oi)>=.0015
     confirmations=sum((book_ok,flow_ok,participation_ok,oi_ok,impact>=.25))

     score=25+max(0,25*(1-dist/max(dynamic,.01)))+min(18,impact*9)
     score+=10*bool(side*r15>=.00015)+12*bool(side*r60>=.00035)+6*book_ok+6*flow_ok+4*participation_ok+4*oi_ok
     raw_candidates.append({**material,"engine":"price_to_value_liquidation","policy":PRICE_TO_VALUE_POLICY,
      "observed_at_epoch":stamp,"symbol":sym,"side":side,"victim_side":p["side"],
      "cluster_id":p["cluster_id"],"wallet_count":p["wallet_count"],"whale_size_usd":p["size_usd"],
      "liquidation_price":p["liq_price"],"mark_price":p["mark_price"],"distance_pct":dist,
      "dynamic_entry_distance_pct":dynamic,"position_age_seconds":p["position_age_seconds"],
      "r15":r15,"r60":r60,"r300":r300,"r900":r900,"orderbook_imbalance":imb,
      "spread_bps":spread,"flow_imbalance":flow,"cvd_1m":ctx.get("cvd_1m"),
      "volume_rate_z":vol_z,"volume_burst_ratio":burst,"oi_delta_60s":oi,
      "micro_confirmations":confirmations,"score":round(min(100,score),2)})

    tracked=ptv_tracker.observe(raw_candidates,scan_id,stamp)
    regime=market_regime(prices,history,S.get("_day_volumes",{}),stamp)
    regime_side=int(regime.get("side") or 0)
    evaluated=[price_to_value_entry(x,regime_side) for x in tracked]
    qualified=[x for x in evaluated if x.get("ptv_qualified")]

    best_by_symbol={}
    for x in sorted(qualified,key=lambda z:(float(z.get("distance_pct",99)),
                                             -float(z.get("ptv_quality_score",0)),
                                             -float(z.get("whale_size_usd",0)))):
     best_by_symbol.setdefault(x["symbol"],x)
    qualified=list(best_by_symbol.values())
    qualified.sort(key=lambda x:(-float(x.get("ptv_quality_score",0)),float(x.get("distance_pct",99))))

    for x in evaluated:
     if x.get("ptv_qualified"):continue
     for reason in x.get("ptv_reject_reasons") or ["ptv_rejected"]:reject(reason)
    for reason,count in rejections.items():rejection_totals[reason]=rejection_totals.get(reason,0)+count

    opened_now=[]
    for x in qualified:
     sym=x["symbol"];side=int(x["side"])
     learn_id=hashlib.sha256(("PTV_ENTRY:"+str(x.get("cluster_id"))+":"+str(int(stamp//15))).encode()).hexdigest()
     x["learning_decision_id"]=learn_id
     with LOCK:capacity=len(S.get("whale_positions",{}))<WHALE_MAX_ACTIVE_POSITIONS
     opened=capacity and whale_liq_open(sym,side,prices.get(sym),x.get("ptv_quality_score",x["score"]),x,WHALE_MARGIN_FRACTION)
     action="OPENED" if opened else ("SKIPPED" if not capacity else "QUALIFIED")
     reason="entry_opened" if opened else ("whale_position_cap" if not capacity else "qualified_but_entry_vetoed_or_symbol_busy")
     log_learning_decision(learn_id,"whale_liquidation",sym,side,action,reason,prices.get(sym),
       x.get("ptv_quality_score",x.get("score")),WHALE_LEVERAGE,x)
     if opened:opened_now.append(sym)

     key=(x["cluster_id"],action)
     if stamp-last_signal.get(key,0)>=15:
      last_signal[key]=stamp
      ident=hashlib.sha256(("PTV:"+x["cluster_id"]+":"+str(int(stamp//15))+":"+action).encode()).hexdigest()
      with pg() as db:db.execute(
       "insert into whale_liq_signal_journal(id,ts,symbol,side,score,action,features) values(%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict(id) do nothing",
       (ident,now(),sym,side,x.get("ptv_quality_score",x["score"]),action,json.dumps(x,default=str)))

    bucket=int(stamp//60)
    for x in evaluated:
     if x.get("ptv_qualified"):continue
     sym=x.get("symbol");side=int(x.get("side") or 0)
     if not sym or side not in (-1,1):continue
     reason=",".join(str(r) for r in (x.get("ptv_reject_reasons") or ["ptv_rejected"]))
     did=hashlib.sha256(("PTV_OBS:"+str(x.get("cluster_id"))+":"+str(bucket)).encode()).hexdigest()
     log_learning_decision(did,"whale_liquidation",sym,side,"REJECTED",reason,prices.get(sym),
       x.get("ptv_quality_score",x.get("score")),WHALE_LEVERAGE,x)

    if clusters or evaluated or qualified:
     try:save_scanner_observation("whale_liquidation",{"policy":PRICE_TO_VALUE_POLICY,
      "danger_positions":len(rows),"clusters":clusters[:25],"candidates":evaluated[:25],
      "qualified":qualified[:15],"opened":opened_now,"market_regime":regime,
      "rejections":rejections,"scan_epoch":stamp})
     except Exception as obs_exc:
      with LOCK:S["last_error"]="whale_observation: "+str(obs_exc)[:160]

    elapsed=time.monotonic()-started
    with LOCK:S["sources"]["WhaleLiquidationScanner"]={"ok":danger_error is None,"last_check":now(),
     "mode":"price_to_value_liquidation","policy":PRICE_TO_VALUE_POLICY,
     "symbols":"ALL_HYPERLIQUID_LISTED","scan_seconds":LIQ_WHALE_SCAN_SECONDS,
     "actual_scan_seconds":round(elapsed,3),"danger_positions":len(rows),"clusters":len(clusters),
     "eligible_candidates":len(evaluated),"qualified_candidates":len(qualified),
     "opened_this_scan":opened_now,"rejections":rejections,
     "rejections_since_start":dict(rejection_totals),
     "top_candidates":qualified[:5] if qualified else sorted(evaluated,key=lambda x:float(x.get("distance_pct",99)))[:5],
     "paper_positions":len(S["whale_positions"]),"paper_trades":S["whale_trades"],
     "market_regime":regime,
     "entry_logic":"trend->nearest_material_liquidation->approach->micro_confirmation",
     "exit_logic":"profit_protection->distance/thesis_invalidation->post_liquidation_weakening",
     "coverage":"observed_hyperliquid_wallets_only_not_global_heatmap",
     "shared_account_equity":round(S["equity"],4),"error":danger_error}
   except Exception as exc:
    with LOCK:S["sources"]["WhaleLiquidationScanner"]={"ok":False,"last_check":now(),
     "mode":"price_to_value_liquidation","policy":PRICE_TO_VALUE_POLICY,"error":str(exc)[:180]}
   SHUTDOWN.wait(max(.05,LIQ_WHALE_SCAN_SECONDS-(time.monotonic()-started)))
 finally:
  pool.shutdown(wait=False,cancel_futures=True)

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
 # A 15s move must never use a just-arrived observation as its anchor.
 tolerance=min(5.0,age*0.20)
 candidates=[r for r in rows if len(r)>=2 and age-tolerance<=stamp-float(r[0])<=age+tolerance]
 if not candidates:return None
 t,p=min(candidates,key=lambda r:abs((stamp-float(r[0]))-age))
 try:return float(current)/float(p)-1
 except Exception:return None

def _profit_protection_eval(position,symbol,mark,stamp,timeline):
 """Strategy-agnostic PAPER profit protection.

 It has two layers:
 1) after +0.40% favorable movement, protect half the peak (floor +0.12%);
 2) while still profitable, close early on a confirmed fast reversal using
    15s/60s price pressure, executed trade-flow and giveback from MFE.
 """
 pos=copy.deepcopy(position or {})
 try:
  entry=float(pos["entry"]);side=int(pos["side"]);mark=float(mark)
 except Exception:return pos,None,None,{"ready":False}
 if entry<=0 or mark<=0 or side not in (-1,1):return pos,None,None,{"ready":False}
 features=copy.deepcopy(pos.get("features") or {})
 prior=features.get("profit_protection") or {}
 peak=max(float(pos.get("profit_peak_move",prior.get("peak_move",0)) or 0),side*(mark/entry-1.0))
 favorable=side*(mark/entry-1.0)
 was_armed=bool(pos.get("profit_lock_armed",prior.get("armed",False)))
 armed=was_armed or peak>=PROFIT_PROTECT_ARM_MOVE
 lock_move=max(PROFIT_PROTECT_LOCK_MOVE, peak*0.50)
 stop=entry*(1.0+side*lock_move) if armed else None
 r15=_timeline_return(timeline or [],stamp,15,mark)
 r60=_timeline_return(timeline or [],stamp,60,mark)
 observed=MARKET_OBS.context(symbol,stamp)
 flow=observed.get("flow_imbalance")
 flow_fresh=bool(observed.get("trade_data_fresh"))
 adverse15=r15 is not None and side*float(r15)<=-PROFIT_PROTECT_R15
 adverse60=r60 is not None and side*float(r60)<=-PROFIT_PROTECT_R60
 adverse_flow=flow_fresh and flow is not None and side*float(flow)<=-PROFIT_PROTECT_FLOW
 giveback=max(0.0,peak-favorable)
 giveback_trigger=max(0.0006,min(0.0020,max(peak,0.0)*0.20))
 adverse_giveback=giveback>=giveback_trigger
 score=sum((adverse15,adverse60,adverse_flow,adverse_giveback))
 hard_stop=bool(armed and stop is not None and ((side>0 and mark<=stop) or (side<0 and mark>=stop)))
 reversal=bool(favorable>=PROFIT_PROTECT_REVERSAL_MIN_MOVE and score>=3 and (adverse15 or adverse60))
 state={"enabled":True,"armed":armed,"arm_move_pct":PROFIT_PROTECT_ARM_MOVE*100.0,
  "lock_move_pct":PROFIT_PROTECT_LOCK_MOVE*100.0,"peak_move":peak,"current_move":favorable,
  "stop":stop,"return_15s":r15,"return_60s":r60,"flow_imbalance":flow if flow_fresh else None,
  "flow_fresh":flow_fresh,"giveback":giveback,"giveback_trigger":giveback_trigger,
  "adverse_score":score,"adverse_15s":adverse15,"adverse_60s":adverse60,
  "adverse_flow":adverse_flow,"adverse_giveback":adverse_giveback,"checked_at":now()}
 pos["profit_peak_move"]=peak;pos["profit_lock_armed"]=armed;pos["profit_lock_stop"]=stop
 if armed and not was_armed:pos["profit_protect_armed_at"]=now()
 pos["profit_protect_last"]=state
 features["profit_protection"]=state;pos["features"]=features
 if hard_stop:return pos,"profit_lock_stop",mark,state
 if reversal:return pos,"profit_protect_fast_reversal",mark,state
 return pos,None,None,state

def _profit_protection_arm_journal(strategy,symbol,before,after):
 if not before and bool(after.get("profit_lock_armed")):
  state=after.get("profit_protect_last") or {}
  journal("profit_protection_armed",None,{"strategy":strategy,"symbol":symbol,
   "entry":after.get("entry"),"side":after.get("side"),"stop":state.get("stop"),
   "arm_move_pct":PROFIT_PROTECT_ARM_MOVE*100.0,"lock_move_pct":PROFIT_PROTECT_LOCK_MOVE*100.0,
   "peak_move_pct":float(state.get("peak_move",0) or 0)*100.0})

def market_regime(prices,history,volumes,stamp):
 with LOCK:candles=copy.deepcopy(S.get("_regime_candles",{}))
 return breadth_regime(prices,history,volumes,stamp,candles,require_trend_context=True)

# A fixed liquid seed set makes H1/H4 context independent of REST fan-out.
# Five markets remain mandatory; missing history must not become a flat regime.
REGIME_SEED_SYMBOLS=("BTC","ETH","SOL","HYPE","NEAR","DOGE")

def accept_regime_candles(rows):
 if isinstance(rows,dict):rows=[rows]
 if not isinstance(rows,list):return 0
 stamp=time.time();accepted=0
 with LOCK:
  for row in rows:
   if not isinstance(row,dict) or row.get("s") not in REGIME_SEED_SYMBOLS or row.get("i")!="1m":continue
   try:
    t,T,close=float(row["t"]),float(row["T"]),float(row["c"])
    if not all(math.isfinite(v) for v in (t,T,close)) or close<=0 or not 59000<=T-t<=60000 or t/1000>stamp+1:continue
   except (ValueError,TypeError,KeyError,OverflowError):continue
   symbol=row["s"];prior=S.setdefault("_regime_candles",{}).get(symbol,[])
   merged=dict(prior);pending=S.setdefault("_regime_pending_candles",{}).get(symbol)
   if pending and pending[0]<stamp:
    merged[pending[0]]=pending[1];S["_regime_pending_candles"].pop(symbol,None);accepted+=1
   if T/1000<stamp:merged[T/1000]=close;accepted+=1
   else:
    pending=S["_regime_pending_candles"].get(symbol)
    if not pending or T/1000>=pending[0]:S["_regime_pending_candles"][symbol]=(T/1000,close)
   S["_regime_candles"][symbol]=sorted(merged.items())[-361:]
  if accepted:S["_regime_ws_last_update"]=stamp
 return accepted

@account_mutation
def close_news_position(sym,pos,price,reason):
 result=STORE.close(sym,pos,price,reason)
 if result:
  with LOCK:
   S["equity"]=float(result["equity"]);S["realized_pnl"]=float(result["realized_pnl"]);S["trades"]+=1
   if S["positions"].get(sym,{}).get("opened")==pos["opened"]:S["positions"].pop(sym,None)
 return result

def reconcile_open_paper_sizing(prices):
 # Sizing is fixed at each actual entry. Do not resize old trades at their
 # historical entry price or reconstruct their performance after the fact.
 return 0

def accept_market_prices(mids):
 valid={}
 for k,v in (mids or {}).items():
  try:
   px=float(v)
   if re.match(r"^[A-Z0-9]{2,15}$",k) and math.isfinite(px) and px>0:valid[k]=px
  except (ValueError,TypeError):continue
 if not valid:raise ValueError("empty market response")
 stamp=time.time()
 with LOCK:
  S["last_poll"]=now();S["_last_poll_epoch"]=stamp;S["market_count"]=len(valid);S["_prices"]=valid;S["last_market_error"]=None
  for sym,px in valid.items():
   track=S.setdefault("_timeline",{}).setdefault(sym,[])
   if not track or stamp-float(track[-1][0])>=0.5:
    track.append((stamp,px))
    if len(track)>1800:del track[:-1800]
   hist=S.setdefault("_hist",{}).setdefault(sym,[])
   if not hist or float(hist[-1])!=px:
    hist.append(px)
    if len(hist)>120:del hist[:-120]
 return valid

def refresh_market_prices(force=False,max_age=8.0):
 # Emergency refresh keeps scanners live even when the position-checkpoint part
 # of the market worker is busy writing many PAPER positions to PostgreSQL.
 # Network I/O is serialized but never holds the global state lock.
 with LOCK:
  cached=dict(S.get("_prices",{}));last=float(S.get("_last_poll_epoch",0) or 0)
  active=bool(S.get("engine_active"))
  metadata_ready=bool(S.get("_day_volumes")) and bool(S.get("_max_leverage"))
 # Hard startup barrier: no caller is allowed to spend REST budget on allMids
 # before the one metadata bootstrap request succeeds.
 if active and not metadata_ready:
  if cached and time.time()-last<=max_age:return cached
  raise RestDeferred("metadata_bootstrap_required_before_allMids")
 if not force and cached and time.time()-last<=max_age:return cached
 with MARKET_REFRESH_LOCK:
  with LOCK:
   cached=dict(S.get("_prices",{}));last=float(S.get("_last_poll_epoch",0) or 0)
  if not force and cached and time.time()-last<=max_age:return cached
  if not force and not cached:
   deadline=time.monotonic()+2.5
   while time.monotonic()<deadline and not SHUTDOWN.is_set():
    SHUTDOWN.wait(.1)
    with LOCK:
     cached=dict(S.get("_prices",{}));last=float(S.get("_last_poll_epoch",0) or 0)
    if cached and time.time()-last<=max_age:return cached
  try:
   mids=json.loads(get(API,{"type":"allMids"}))
  except urllib.error.HTTPError as exc:
   # Hyperliquid can transiently rate-limit duplicate allMids requests. If the
   # market worker already has a very recent snapshot, keep the risk/exit loop
   # alive from that snapshot instead of turning a harmless 429 into an engine error.
   if exc.code==429 and cached and time.time()-last<=12.0:
    with LOCK:S["last_market_error"]=None
    return cached
   raise
  return accept_market_prices(mids)



# Avoid repeated identical Hyperliquid candle requests across local scanner cycles.
# M15 remains reasonably fresh; H1 context cannot change on every 10s loop.
_LOCAL_CANDLE_CACHE={}
_LOCAL_CANDLE_CACHE_LOCK=threading.RLock()
_LOCAL_CANDLE_REFRESH_LOCK=threading.Lock()
_LOCAL_CANDLE_BACKOFF={}
_LOCAL_CANDLE_STREAM={}
def accept_local_candles(data,history=False):
 rows=data if isinstance(data,list) else [data]
 stamp=time.monotonic();wall_ms=int(time.time()*1000)
 with _LOCAL_CANDLE_CACHE_LOCK:
  for row in rows:
   if not isinstance(row,dict):continue
   symbol,interval=row.get("s"),row.get("i")
   if symbol not in ALL_LOCAL_CANDLE_SYMBOLS or interval not in ("1h","15m"):continue
   try:
    t,T=int(row["t"]),int(row["T"])
    values=[float(row[k]) for k in ("o","h","l","c","v")]
    o,h,l,c,v=values;step=3600000 if interval=="1h" else 900000
    if not all(math.isfinite(z) for z in values) or min(o,h,l,c)<=0 or v<0:continue
    if not (step-1000<=T-t<=step and l<=min(o,c)<=max(o,c)<=h and t<=wall_ms+1000 and T>=wall_ms-((120 if interval=="1h" else 12)*3600000 if history else 2*step)):continue
   except (KeyError,TypeError,ValueError,OverflowError):continue
   key=(symbol,interval,120 if interval=="1h" else 12)
   cached=_LOCAL_CANDLE_CACHE.get(key)
   old=cached[1] if cached else []
   merged={int(r["t"]):r for r in old}
   if not (history and cached and any(int(r["t"])==t for r in cached[1])):merged[t]=dict(row)
   # A delayed WS update cannot replace a newer version of the same candle.
   previous=_LOCAL_CANDLE_STREAM.get((symbol,interval))
   if not history and previous and t<previous[1]:continue
   _LOCAL_CANDLE_CACHE[key]=(stamp,[merged[k] for k in sorted(merged)][-125:],wall_ms)
   if not history:_LOCAL_CANDLE_STREAM[(symbol,interval)]=(stamp,t)

def accept_local_history(rows):
 # Local bootstrap arrives as one compact 3m snapshot per market. Aggregate
 # only complete 3m buckets into the exact H1/M15 OHLCV shapes consumed by
 # the existing strategy; live H1/M15 subscriptions overwrite current candles.
 if not isinstance(rows,list):return 0
 direct=[r for r in rows if isinstance(r,dict) and r.get("i") in ("1h","15m")]
 if direct:return accept_local_candles(direct,history=True) or len(direct)
 by_symbol={}
 for row in rows:
  if not isinstance(row,dict) or row.get("i")!="3m" or row.get("s") not in ALL_LOCAL_CANDLE_SYMBOLS:continue
  try:
   t,T=int(row["t"]),int(row["T"])
   vals=[float(row[k]) for k in ("o","h","l","c","v")]
   if not all(math.isfinite(x) for x in vals) or min(vals[:4])<=0 or vals[4]<0:continue
   if not 179000<=T-t<=180000:continue
  except (KeyError,TypeError,ValueError,OverflowError):continue
  by_symbol.setdefault(row["s"],[]).append(dict(row))
 aggregated=[]
 for symbol,source in by_symbol.items():
  indexed={int(r["t"]):r for r in source}
  for interval,step,parts in (("15m",900000,5),("1h",3600000,20)):
   starts=sorted({(t//step)*step for t in indexed})
   for start in starts:
    required=[start+i*180000 for i in range(parts)]
    if not all(t in indexed for t in required):continue
    group=[indexed[t] for t in required]
    try:
     o=float(group[0]["o"]);c=float(group[-1]["c"])
     h=max(float(r["h"]) for r in group);l=min(float(r["l"]) for r in group)
     v=sum(float(r.get("v",0) or 0) for r in group)
     n=sum(int(r.get("n",0) or 0) for r in group)
    except (TypeError,ValueError,OverflowError):continue
    aggregated.append({"s":symbol,"i":interval,"t":start,"T":start+step-1,
      "o":str(o),"h":str(h),"l":str(l),"c":str(c),"v":str(v),"n":n})
 accept_local_candles(aggregated,history=True)
 return len(aggregated)

_LOCAL_CANDLE_CHECKPOINTED={}
def checkpoint_local_candles():
 # Persist once per newly closed interval, rather than every live candle tick.
 wall_ms=int(time.time()*1000);pending=[]
 with _LOCAL_CANDLE_CACHE_LOCK:
  for key,value in _LOCAL_CANDLE_CACHE.items():
   symbol,interval,_hours=key
   if len(value[1])<_local_min_history_rows(interval):continue
   closed=[int(r["t"]) for r in value[1] if int(r["T"])<=wall_ms-1000]
   token=max(closed) if closed else None
   if token is None or _LOCAL_CANDLE_CHECKPOINTED.get(key)==token:continue
   pending.append((key,token,copy.deepcopy(value[1])))
 if not pending:return
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   for key,token,rows in pending:
    db.execute("insert into local_candle_checkpoints(symbol,interval,candles,saved_at) values(%s,%s,%s::jsonb,clock_timestamp()) on conflict(symbol,interval) do update set candles=excluded.candles,saved_at=excluded.saved_at",
     (key[0],key[1],json.dumps(rows)))
 for key,token,_rows in pending:_LOCAL_CANDLE_CHECKPOINTED[key]=token

def _local_min_history_rows(interval):
 return 6 if interval=="1h" else 9

def _local_cached_interval_fresh(cached,interval):
 if not cached or len(cached[1])<_local_min_history_rows(interval):return False
 try:
  step=3600000 if interval=="1h" else 900000
  # Both structural H1 and execution M15 require a contiguous run of CLOSED
  # candles. A recent last candle must never hide multi-hour holes in M15.
  wall_ms=int(time.time()*1000)
  closed=sorted({int(r["t"]) for r in cached[1] if int(r.get("T",int(r["t"])+step-1))<=wall_ms-1000})
  need=6 if interval=="1h" else 12
  if len(closed)<need or any(b-a!=step for a,b in zip(closed[-need:],closed[-need+1:])):
   return False
  row=cached[1][-1]
  close_ms=int(row.get("T",int(row["t"])+step-1))
  # Illiquid markets may legitimately produce no new candle websocket message
  # for several minutes. The candle is still valid while its exchange interval
  # is current/recent, so do not turn quiet trading into a REST refresh storm.
  return close_ms>=int(time.time()*1000)-2*step
 except (KeyError,TypeError,ValueError,OverflowError):
  return False

def _local_candles(symbol,interval,hours):
 key=(symbol,interval,hours)
 ttl=45.0 if interval==LOCAL_SWING_M15_INTERVAL else 120.0
 max_stale=75.0 if interval==LOCAL_SWING_M15_INTERVAL else 180.0
 stamp=time.monotonic()
 with _LOCAL_CANDLE_CACHE_LOCK:
  cached=_LOCAL_CANDLE_CACHE.get(key)
  stream=_LOCAL_CANDLE_STREAM.get((symbol,interval))
  if cached and stream and stamp-stream[0]<45 and _local_cached_interval_fresh(cached,interval):
   return cached[1],int(time.time()*1000)
  if _local_cached_interval_fresh(cached,interval):
   return cached[1],int(time.time()*1000)
  if cached and _local_cached_interval_fresh(cached,interval) and stamp-cached[0]<ttl:return cached[1],int(time.time()*1000)
  with LOCK:
   stream_state=copy.deepcopy(S.get("sources",{}).get("MarketTradeStream",{}))
   active_engine=bool(S.get("engine_active"))
   history_bootstrap=copy.deepcopy(S.get("sources",{}).get("MarketHistoryBootstrap",{}))
  if active_engine:
   raise RuntimeError("local_swing_history_bootstrap_pending:"+symbol+":"+interval)
  if stamp<_LOCAL_CANDLE_BACKOFF.get(key,0):
   if cached and stamp-cached[0]<max_stale:return cached[1],cached[2]
   raise RuntimeError("local_swing_candle_rate_limit_backoff:"+symbol+":"+interval)
 # Serialize refreshes to avoid concurrent API bursts across LOCAL symbols.
 with _LOCAL_CANDLE_REFRESH_LOCK:
  stamp=time.monotonic()
  with _LOCAL_CANDLE_CACHE_LOCK:
   cached=_LOCAL_CANDLE_CACHE.get(key)
   if _local_cached_interval_fresh(cached,interval):
    return cached[1],int(time.time()*1000)
   if cached and _local_cached_interval_fresh(cached,interval) and stamp-cached[0]<ttl:return cached[1],int(time.time()*1000)
   with LOCK:
    stream_state=copy.deepcopy(S.get("sources",{}).get("MarketTradeStream",{}))
    active_engine=bool(S.get("engine_active"))
    history_bootstrap=copy.deepcopy(S.get("sources",{}).get("MarketHistoryBootstrap",{}))
   # Historical REST recovery has exactly one owner: MarketHistoryBootstrap.
   # Local workers only consume the cache while the engine is active.
   if active_engine:
    raise RuntimeError("local_swing_history_bootstrap_pending:"+symbol+":"+interval)
   if stamp<_LOCAL_CANDLE_BACKOFF.get(key,0):
    if cached and stamp-cached[0]<max_stale:return cached[1],cached[2]
    raise RuntimeError("local_swing_candle_rate_limit_backoff:"+symbol+":"+interval)
  end_ms=int(time.time()*1000);start_ms=end_ms-int(max(12,hours)*3600*1000)
  if cached and len(cached[1])>=_local_min_history_rows(interval):
   step=3600000 if interval=="1h" else 900000
   start_ms=max(start_ms,int(cached[1][-1]["t"])-step)
  try:
   rows=json.loads(get(API,{"type":"candleSnapshot","req":{"coin":symbol,"interval":interval,"startTime":start_ms,"endTime":end_ms}}))
   if not isinstance(rows,list):raise RuntimeError("local_swing_candle_snapshot_invalid:"+symbol+":"+interval)
  except urllib.error.HTTPError as exc:
   if exc.code!=429:raise
   with _LOCAL_CANDLE_CACHE_LOCK:
    _LOCAL_CANDLE_BACKOFF[key]=time.monotonic()+30.0
    cached=_LOCAL_CANDLE_CACHE.get(key)
    if cached and time.monotonic()-cached[0]<max_stale:return cached[1],cached[2]
   raise
  with _LOCAL_CANDLE_CACHE_LOCK:
   # Merge REST with WS updates received while this HTTP request was running.
   current=_LOCAL_CANDLE_CACHE.get(key)
   merged={int(r["t"]):r for r in (cached[1] if cached else [])}
   merged.update({int(r["t"]):r for r in rows})
   if current and current[0]>stamp:merged.update({int(r["t"]):r for r in current[1]})
   rows=[merged[k] for k in sorted(merged)][-125:]
   _LOCAL_CANDLE_CACHE[key]=(time.monotonic(),rows,end_ms)
   _LOCAL_CANDLE_BACKOFF.pop(key,None)
  return rows,end_ms

def _local_h1_candles(symbol,hours=120):
 return _local_candles(symbol,LOCAL_SWING_H1_CONTEXT_INTERVAL,hours)

def _local_m15_candles(symbol,hours=12):
 return _local_candles(symbol,LOCAL_SWING_M15_INTERVAL,hours)

def _hype_h1_candles(hours=120):
 return _local_h1_candles(HYPE_SWING_SYMBOL,hours)

def _local_claim(symbol,action,side,analysis,price=None):
 candle=int(analysis.get("signal_candle_time") or 0)
 ident="LOCAL_H1:%s:%s:%s:%s"%(symbol,action,candle,int(side or 0))
 payload={**analysis,"symbol":symbol,"action":action,"side":int(side or 0),"policy":HYPE_SWING_POLICY}
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   row=db.execute("""insert into hype_swing_signal_journal(id,ts,candle_time,action,side,price,features)
     values(%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict(id) do nothing returning id""",
     (ident,now(),candle,action,int(side or 0),price,json.dumps(payload,default=str))).fetchone()
   if row and action=="OBSERVE":
    db.execute("insert into scanner_observations(ts,module,payload) values(%s,%s,%s::jsonb)",
      (now(),"local_h1_m15_swing_v5",json.dumps(payload,default=str)))
 if row:
  log_learning_decision("LOCAL_H1:"+symbol+":"+str(candle)+":"+str(int(side or 0)),"local_h1_m15_swing_v5",
   symbol,int(side or 0),action,"confirmed_h1_pivot",price,None,HYPE_SWING_LEVERAGE,payload)
 return bool(row)

def _hype_claim(action,side,analysis,price=None):
 return _local_claim(HYPE_SWING_SYMBOL,action,side,analysis,price)

def _local_watch_clear(symbol,reason):
 with LOCK:watch=copy.deepcopy(S.get("local_swing_watch",{}).get(symbol))
 if not watch:return False
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   db.execute("delete from local_swing_watchlist where symbol=%s",(symbol,))
   db.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'local_swing_watch_cleared',%s::jsonb)",
    (now(),json.dumps({"symbol":symbol,"reason":reason,"watch":watch},default=str)))
 with LOCK:S.setdefault("local_swing_watch",{}).pop(symbol,None)
 return True

@account_mutation
def _local_watch_observe(symbol,watch,mark,m15,flow,stamp):
 updated=caterpillar_update_watch(watch,mark,m15,flow,stamp)
 before=(watch or {}).get("context") or {};context=updated.get("context") or {}
 with LOCK:last=float(S.setdefault("_local_watch_persist_epoch",{}).get(symbol,0) or 0)
 changed=before.get("phase")!=context.get("phase")
 if changed or stamp-last>=30:
  with pg() as db:
   with db.transaction():
    STORE.fence(db)
    db.execute("update local_swing_watchlist set context=%s::jsonb where symbol=%s and exit_at=%s",
     (json.dumps(context,default=str),symbol,watch.get("exit_at")))
    if changed:
     db.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'local_caterpillar_phase',%s::jsonb)",
      (now(),json.dumps({"symbol":symbol,"side":watch.get("side"),"phase":context.get("phase"),"context":context},default=str)))
  with LOCK:S["_local_watch_persist_epoch"][symbol]=stamp
 with LOCK:
  live=S.get("local_swing_watch",{}).get(symbol)
  if live and live.get("exit_at")==watch.get("exit_at"):S["local_swing_watch"][symbol]=copy.deepcopy(updated)
 return updated

@account_mutation
def local_swing_open(symbol,side,analysis,entry_kind="M15",m15=None,watch=None):
 if symbol in LOCAL_EXPERIMENT_SYMBOLS:return False  # legacy HYPE/NEAR book is exit-only
 if symbol not in LOCAL_SWING_SYMBOLS:return False
 if S.get("mode")!="PAPER_ONLY" or S.get("orders_enabled") or int(side) not in (-1,1):return False
 if not analysis.get("ready"):return False
 if not analysis.get("h1_direction_anchor") or int(analysis.get("entry_side") or 0)!=int(side):return False
 if analysis.get("entry_blocked"):return False
 if entry_kind=="M15" and int(analysis.get("entry_side") or 0)!=int(side):return False
 if entry_kind=="REENTRY":
  if not watch or int(watch.get("side") or 0)!=int(side):return False
  if LOCAL_REENTRY_MAX_PER_SWING>0 and int(watch.get("reentries") or 0)>=LOCAL_REENTRY_MAX_PER_SWING:return False
  if int(analysis.get("entry_side") or 0)==-int(side):return False
 price=current_entry_price(symbol)
 if price is None:return False
 leverage=market_max_leverage(symbol)
 with LOCK:
  if not S.get("engine_active") or symbol in S.get("local_swing_positions",{}) or _symbol_open_anywhere(symbol):return False
  equity=float(S.get("equity",0) or 0)
 if equity<=0:return False
 # Preserve the old Local gross-exposure target (25% margin at 25x) while
 # respecting the exchange's real max leverage. Lower leverage therefore uses
 # more margin; if the shared account lacks it, the fill is capped to free margin.
 target_notional=equity*HYPE_SWING_MARGIN_FRACTION*HYPE_SWING_LEVERAGE
 desired_margin=target_notional/max(leverage,1.0)
 desired_fraction=desired_margin/equity
 reserved,margin,reason,free=_reserve_shared_entry(symbol,desired_fraction,strategy="local_swing")
 if not reserved:
  journal("entry_skipped",None,{"strategy":"local_h1_m15_swing_v5","symbol":symbol,"reason":reason,"free_margin":free,"entry_kind":entry_kind})
  log_learning_decision("LOCAL_SKIP:"+symbol+":"+str(int(time.time()//15))+":"+str(int(side)),
   "local_h1_m15_swing_v5",symbol,int(side),"SKIPPED",reason,price,None,leverage,{**analysis,"entry_kind":entry_kind})
  return False
 try:
  price=float(price);notional=margin*leverage
  exposure_fill_ratio=(notional/target_notional) if target_notional>0 else 0.0
  opened=now();epoch=time.time()
  reentries=(int(watch.get("reentries") or 0)+1) if entry_kind=="REENTRY" and watch else 0
  origin_signal=int(analysis.get("signal_candle_time") or 0)
  claim_token=int((m15 or {}).get("candle_time") or analysis.get("signal_candle_time") or 0)
  learning_decision_id=("LOCAL_REENTRY:%s:%s:%s:%s"%(symbol,claim_token,int(side),reentries)
    if entry_kind=="REENTRY" else "LOCAL_H1:%s:%s:%s"%(symbol,origin_signal,int(side)))
  features={**analysis,"symbol":symbol,"policy":HYPE_SWING_POLICY,"strategy_name":"local_h1_m15_swing_v5",
   "learning_decision_id":learning_decision_id,"entry_kind":entry_kind,"origin_h1_signal_candle":origin_signal,
   "swing_reentries":reentries,"allocation_margin_fraction":margin/equity,
   "reference_margin_fraction":HYPE_SWING_MARGIN_FRACTION,"reference_leverage":HYPE_SWING_LEVERAGE,
   "target_notional":target_notional,"desired_margin":desired_margin,"exposure_fill_ratio":exposure_fill_ratio,
   "leverage":leverage,"leverage_source":"hyperliquid_maxLeverage","mfe_price_move":0.0,"mae_price_move":0.0,"mfe_roe_pct":0.0,"mae_roe_pct":0.0,
   "entry_mark":price,"profit_lock_armed":False,"profit_lock_arm_move_pct":HYPE_PROFIT_LOCK_ARM_MOVE*100.0,
   "profit_lock_buffer_move_pct":max(HYPE_PROFIT_LOCK_BUFFER_MOVE,2*FEE+0.0004+0.0003)*100.0,
   "m15_entry_context":m15,"m15_reentry_context":m15 if entry_kind=="REENTRY" else None,
   "reentry_watch":copy.deepcopy(watch) if entry_kind=="REENTRY" else None,
   "estimated_round_trip_cost_move":2*FEE+0.0004,"execution_cost_budget_only":True,
   "profit_lock_arm_move":0.004,"profit_lock_mode":"fixed_cost_aware_breakeven","caterpillar_policy":CATERPILLAR_POLICY,
   "profit_lock_buffer_move":max(HYPE_PROFIT_LOCK_BUFFER_MOVE,2*FEE+0.0004+0.0003),
   "shadow_exit_modes":["opposite_h1_local_extreme","m15_momentum_weakening","profit_lock_stop","m15_adverse_pressure_profit_protect"]}
  pos={"symbol":symbol,"side":int(side),"entry":price,"notional":notional,"margin":margin,"leverage":leverage,
       "opened":opened,"t":epoch,"signal_candle_time":origin_signal,"features":features}
  with pg() as db:
   with db.transaction():
    STORE.fence(db)
    claim_id=("LOCAL_REENTRY:OPEN:%s:%s:%s:%s"%(symbol,claim_token,int(side),reentries)
      if entry_kind=="REENTRY" else "LOCAL_H1:OPEN:%s:%s:%s"%(symbol,origin_signal,int(side)))
    claim=db.execute("""insert into hype_swing_signal_journal(id,ts,candle_time,action,side,price,features)
      values(%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict(id) do nothing returning id""",
      (claim_id,opened,claim_token,"REENTRY" if entry_kind=="REENTRY" else "OPEN",int(side),price,json.dumps(features,default=str))).fetchone()
    if not claim:return False
    row=db.execute("""insert into hype_swing_positions(symbol,side,entry,notional,margin,leverage,opened,opened_epoch,signal_candle_time,features)
       values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict(symbol) do nothing returning symbol""",
       (symbol,int(side),price,notional,margin,leverage,opened,epoch,origin_signal,json.dumps(features,default=str))).fetchone()
    if not row:return False
    db.execute("""insert into hype_swing_shadow_exits(opened,entry_candle_time,side,entry,context,symbol)
      values(%s,%s,%s,%s,%s::jsonb,%s)""",(opened,origin_signal,int(side),price,json.dumps(features,default=str),symbol))
    if entry_kind=="REENTRY":db.execute("delete from local_swing_watchlist where symbol=%s",(symbol,))
    db.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'local_swing_trade_opened',%s::jsonb)",
      (now(),json.dumps({"strategy":"local_h1_m15_swing_v5","symbol":symbol,"side":int(side),"entry_kind":entry_kind,
       "entry":price,"margin":margin,"notional":notional,"leverage":leverage,"equity":equity,
       "origin_h1_signal_candle":origin_signal,"reentries":reentries,"pivot_type":analysis.get("pivot_type"),
       "pivot_price":analysis.get("pivot_price"),"policy":HYPE_SWING_POLICY},default=str)))
  with LOCK:
   S.setdefault("local_swing_positions",{})[symbol]=pos
   if symbol==HYPE_SWING_SYMBOL:S["hype_swing_position"]=pos
   if entry_kind=="REENTRY":S.setdefault("local_swing_watch",{}).pop(symbol,None)
  log_learning_decision(learning_decision_id,"local_h1_m15_swing_v5",symbol,int(side),"OPENED",
   "m15_recovery_reentry" if entry_kind=="REENTRY" else "h1_anchor_m15_entry",price,None,leverage,features)
  return True
 finally:_release_shared_entry(symbol,strategy="local_swing")

def hype_swing_open(side,price,analysis):
 return local_swing_open(HYPE_SWING_SYMBOL,side,analysis)

@account_mutation
def local_swing_close(symbol,price,reason,analysis=None,watch_context=None):
 with LOCK:
  pos=copy.deepcopy(S.get("local_swing_positions",{}).get(symbol))
  if not pos and symbol==HYPE_SWING_SYMBOL:pos=copy.deepcopy(S.get("hype_swing_position"))
 if not pos:return None
 price=float(price);pnl=paper_pnl(pos["notional"],pos["entry"],price,pos["side"],FEE)
 features=copy.deepcopy(pos.get("features") or {})
 if analysis:features["exit_analysis"]=analysis
 if watch_context:features["m15_profit_protection"]=watch_context
 features["actual_exit_reason"]=reason;features["actual_exit_mark"]=price
 watch=None
 if reason in ("m15_adverse_pressure_profit_protect","profit_lock_stop","m15_momentum_weakening","m15_pressure_reversal","m15_pressure_reversal_profit_only","caterpillar_breakeven"):
  watch={"symbol":symbol,"side":int(pos["side"]),
   "origin_signal_candle":int(features.get("origin_h1_signal_candle") or features.get("origin_m15_signal_candle") or pos.get("signal_candle_time") or 0),
   "exit_price":price,"exit_at":now(),"expires_epoch":0.0,
   "reentries":int(features.get("swing_reentries",0) or 0),"context":watch_context or {}}
  watch["context"].update(phase="WAIT_PULLBACK",counter_pressure_seen=reason in ("m15_pressure_reversal","m15_pressure_reversal_profit_only"),caterpillar_policy=CATERPILLAR_POLICY)
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   row=db.execute("delete from hype_swing_positions where symbol=%s and opened=%s returning symbol",(symbol,pos["opened"])).fetchone()
   if not row:return None
   acct=db.execute("""update hype_swing_account_state set equity=equity+%s,realized_pnl=realized_pnl+%s,updated_at=%s
     where id=1 returning equity,realized_pnl""",(pnl,pnl,now())).fetchone()
   shared=db.execute("update account_state set equity=equity+%s,realized_pnl=realized_pnl+%s,updated_at=%s where id=1 returning equity,realized_pnl",(pnl,pnl,now())).fetchone()
   db.execute("""insert into hype_swing_trade_history(opened,closed,symbol,side,entry,exit,pnl,reason,margin,notional,leverage,features)
     values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
     (pos["opened"],now(),symbol,pos["side"],pos["entry"],price,pnl,reason,pos["margin"],pos["notional"],pos["leverage"],json.dumps(features,default=str)))
   db.execute("""insert into trade_history(opened,closed,symbol,side,entry,exit,pnl,reason,strategy,features)
     values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
     (pos["opened"],now(),symbol,pos["side"],pos["entry"],price,pnl,reason,features.get("strategy_name","local_h1_m15_swing_v5"),json.dumps(features,default=str)))
   db.execute("""update hype_swing_shadow_exits set actual_exit_at=%s,actual_exit_price=%s,actual_exit_reason=%s
     where coalesce(symbol,'HYPE')=%s and opened=%s""",(now(),price,reason,symbol,pos["opened"]))
   if watch:
    db.execute("""insert into local_swing_watchlist(symbol,side,origin_signal_candle,exit_price,exit_at,expires_epoch,reentries,context)
      values(%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
      on conflict(symbol) do update set side=excluded.side,origin_signal_candle=excluded.origin_signal_candle,
      exit_price=excluded.exit_price,exit_at=excluded.exit_at,expires_epoch=excluded.expires_epoch,
      reentries=excluded.reentries,context=excluded.context""",
      (symbol,watch["side"],watch["origin_signal_candle"],watch["exit_price"],watch["exit_at"],watch["expires_epoch"],watch["reentries"],json.dumps(watch["context"],default=str)))
   db.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'local_swing_trade_closed',%s::jsonb)",
     (now(),json.dumps({"strategy":"local_h1_m15_swing_v5","symbol":symbol,"side":pos["side"],
      "entry":pos["entry"],"exit":price,"pnl":pnl,"reason":reason,"equity":float(acct["equity"]),
      "watch_armed":bool(watch),"mae_roe_pct":features.get("mae_roe_pct"),"mfe_roe_pct":features.get("mfe_roe_pct"),
      "policy":HYPE_SWING_POLICY},default=str)))
 with LOCK:
  S.setdefault("local_swing_positions",{}).pop(symbol,None)
  if symbol==HYPE_SWING_SYMBOL:S["hype_swing_position"]=None
  if watch:S.setdefault("local_swing_watch",{})[symbol]=watch
  S["hype_swing_equity"]=float(acct["equity"]);S["hype_swing_realized_pnl"]=float(acct["realized_pnl"])
  S["hype_swing_trades"]=int(S.get("hype_swing_trades",0))+1
  S["equity"]=float(shared["equity"]);S["realized_pnl"]=float(shared["realized_pnl"]);S["trades"]+=1
 return {"pnl":pnl,"equity":float(acct["equity"]),"reason":reason,"watch_armed":bool(watch)}

def hype_swing_close(price,reason,analysis=None):
 return local_swing_close(HYPE_SWING_SYMBOL,price,reason,analysis)

def _local_update_shadows(symbol,analysis,mark):
 with pg() as db:
  rows=db.execute("""select id,opened,side,entry,extreme_exit_at,weakening_exit_at from hype_swing_shadow_exits
    where status='OPEN' and coalesce(symbol,'HYPE')=%s order by id""",(symbol,)).fetchall()
  if not rows:return
  with db.transaction():
   STORE.fence(db)
   for row in rows:
    side=int(row["side"]);entry=float(row["entry"]);tr=hype_shadow_triggers(side,analysis)
    favorable=side*(float(mark)/entry-1.0)
    extreme_at=row["extreme_exit_at"];weak_at=row["weakening_exit_at"]
    if tr.get("extreme") and not extreme_at:
     extreme_at=now()
     db.execute("update hype_swing_shadow_exits set extreme_exit_at=%s,extreme_exit_price=%s where id=%s",(extreme_at,float(mark),row["id"]))
    if tr.get("weakening") and favorable>=0.0015 and not weak_at:
     weak_at=now()
     db.execute("update hype_swing_shadow_exits set weakening_exit_at=%s,weakening_exit_price=%s where id=%s",(weak_at,float(mark),row["id"]))
    if extreme_at and weak_at:db.execute("update hype_swing_shadow_exits set status='COMPLETE' where id=%s",(row["id"],))

def _hype_update_shadows(analysis,mark):
 return _local_update_shadows(HYPE_SWING_SYMBOL,analysis,mark)

@account_mutation
def hype_swing_mark_positions(prices):
 with LOCK:
  positions=copy.deepcopy(S.get("local_swing_positions",{}))
  if not positions and S.get("hype_swing_position"):positions={HYPE_SWING_SYMBOL:copy.deepcopy(S["hype_swing_position"])}
 for symbol,pos in positions.items():
  mark=prices.get(symbol)
  if not mark:continue
  features=pos.setdefault("features",{})
  if features.get("caterpillar_policy")!=CATERPILLAR_POLICY:
   features["previous_profit_lock_stop"]=features.pop("profit_lock_stop",None)
   features["profit_lock_armed"]=False
   features.update(caterpillar_policy=CATERPILLAR_POLICY,profit_lock_mode="fixed_cost_aware_breakeven",
    profit_lock_arm_move=.004,profit_lock_buffer_move=.0016)
  was_armed=bool(features.get("profit_lock_armed"))
  updated,liq=hype_update_path(pos,float(mark))
  newly_armed=(not was_armed) and bool((updated.get("features") or {}).get("profit_lock_armed"))
  lock_fill=caterpillar_breakeven(updated,float(mark))
  if lock_fill is not None:
   features=updated.setdefault("features",{})
   features["profit_lock_trigger_mark"]=float(mark);features["profit_lock_exit_price"]=float(lock_fill);features["profit_lock_triggered_at"]=now()
   with LOCK:
    live=S.get("local_swing_positions",{}).get(symbol)
    if live and live.get("opened")==pos.get("opened"):
     S["local_swing_positions"][symbol]=updated
     if symbol==HYPE_SWING_SYMBOL:S["hype_swing_position"]=updated
   local_swing_close(symbol,float(lock_fill),"caterpillar_breakeven")
   continue
  with LOCK:
   live=S.get("local_swing_positions",{}).get(symbol)
   if live and live.get("opened")==pos.get("opened"):
    S["local_swing_positions"][symbol]=updated
    if symbol==HYPE_SWING_SYMBOL:S["hype_swing_position"]=updated
  if liq:
   local_swing_close(symbol,float(mark),"paper_liquidation_proxy");continue
  stamp=time.time()
  with LOCK:last=float(S.setdefault("_local_path_persist_epoch",{}).get(symbol,0) or 0)
  if stamp-last<30 and not newly_armed:continue
  with LOCK:S["_local_path_persist_epoch"][symbol]=stamp
  with pg() as db:
   with db.transaction():
    STORE.fence(db)
    db.execute("update hype_swing_positions set features=%s::jsonb where symbol=%s and opened=%s",
      (json.dumps(updated.get("features",{}),default=str),symbol,pos["opened"]))
    if newly_armed:
     db.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'local_swing_profit_lock_armed',%s::jsonb)",
       (now(),json.dumps({"strategy":"local_h1_m15_swing_v5","symbol":symbol,"side":updated["side"],
        "entry":updated["entry"],"mark":float(mark),"stop":(updated.get("features") or {}).get("profit_lock_stop"),
        "arm_move_pct":(updated.get("features") or {}).get("profit_lock_arm_move_pct",HYPE_PROFIT_LOCK_ARM_MOVE*100.0),"buffer_move_pct":(updated.get("features") or {}).get("profit_lock_buffer_move_pct",HYPE_PROFIT_LOCK_BUFFER_MOVE*100.0)},default=str)))
    pnl=paper_pnl(updated["notional"],updated["entry"],float(mark),updated["side"],FEE)
    db.execute("""insert into position_snapshots(ts,strategy,symbol,opened,side,entry,mark,margin,notional,leverage,unrealized_pnl,roe_pct,features)
       values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
      (now(),"local_h1_m15_swing_v5",symbol,updated["opened"],updated["side"],updated["entry"],float(mark),
       updated["margin"],updated["notional"],updated["leverage"],pnl,pnl/updated["margin"]*100 if updated["margin"] else 0,
       json.dumps(updated.get("features",{}),default=str)))

def hype_swing_stats():
 try:
  with pg() as db:
   agg=db.execute("""select count(*) as samples,sum(case when pnl>0 then 1 else 0 end) as wins,
     coalesce(sum(pnl),0) as total_pnl,avg(pnl) as avg_pnl,
     avg(nullif(features->>'mae_roe_pct','')::double precision) as avg_mae_roe_pct,
     avg(nullif(features->>'mfe_roe_pct','')::double precision) as avg_mfe_roe_pct
     from hype_swing_trade_history""").fetchone()
   reasons=db.execute("select reason,count(*) as n from hype_swing_trade_history group by reason order by n desc").fetchall()
   shadows=db.execute("""select count(*) as samples,
     avg(case when extreme_exit_price is not null then side*(extreme_exit_price/entry-1)*%s*100 end) as extreme_avg_gross_roe_pct,
     avg(case when weakening_exit_price is not null then side*(weakening_exit_price/entry-1)*%s*100 end) as weakening_avg_gross_roe_pct
     from hype_swing_shadow_exits""",(HYPE_SWING_LEVERAGE,HYPE_SWING_LEVERAGE)).fetchone()
  n=int(agg["samples"] or 0);wins=int(agg["wins"] or 0)
  return {"samples":n,"wins":wins,"win_rate":round(wins/n,4) if n else None,
    "total_pnl":float(agg["total_pnl"] or 0),"avg_pnl":float(agg["avg_pnl"]) if agg["avg_pnl"] is not None else None,
    "avg_mae_roe_pct":float(agg["avg_mae_roe_pct"]) if agg["avg_mae_roe_pct"] is not None else None,
    "avg_mfe_roe_pct":float(agg["avg_mfe_roe_pct"]) if agg["avg_mfe_roe_pct"] is not None else None,
    "exit_reasons":[dict(x) for x in reasons],
    "shadow":{"samples":int(shadows["samples"] or 0),
      "extreme_avg_gross_roe_pct":float(shadows["extreme_avg_gross_roe_pct"]) if shadows["extreme_avg_gross_roe_pct"] is not None else None,
      "weakening_avg_gross_roe_pct":float(shadows["weakening_avg_gross_roe_pct"]) if shadows["weakening_avg_gross_roe_pct"] is not None else None}}
 except Exception as exc:return {"error":str(exc)[:180]}

def local_h1_direction(rows,now_ms,symbol):
 analysis=analyze_hype_h1(rows,now_ms,symbol)
 if not analysis.get("ready"):return analysis
 with LOCK:prior=copy.deepcopy(S.get("local_h1_direction",{}).get(symbol))
 if prior and int(prior.get("signal_candle_time") or 0)>int(analysis.get("signal_candle_time") or 0):
  # A shorter restart cache must never roll a newer persisted H1 anchor back.
  analysis={**prior,"ready":True,"last_candle_time":analysis.get("last_candle_time"),
    **local_pending_extreme(rows,now_ms,int(prior.get("entry_side") or 0))}
 if analysis.get("entry_side") not in (-1,1):return analysis
 if not prior or analysis.get("signal_candle_time")!=prior.get("signal_candle_time"):
  with pg() as db:
   with db.transaction():
    STORE.fence(db)
    db.execute("insert into local_h1_direction(symbol,analysis) values(%s,%s::jsonb) on conflict(symbol) do update set analysis=excluded.analysis",
      (symbol,json.dumps(analysis)))
  with LOCK:S.setdefault("local_h1_direction",{})[symbol]=copy.deepcopy(analysis)
 return analysis


def _local_experiment_margin_state():
 with LOCK:
  realized_equity=float(S.get("local_experiment_equity",LOCAL_EXPERIMENT_STARTING_EQUITY) or 0)
  positions=copy.deepcopy(S.get("local_v12_positions",{}))
  prices=dict(S.get("_prices",{}))
 used=sum(max(0.0,float(p.get("margin",0) or 0)) for p in positions.values())
 unrealized=0.0
 for sym,p in positions.items():
  mark=prices.get(sym)
  if not mark:continue
  try:unrealized+=paper_pnl(float(p.get("notional",0) or 0),float(p.get("entry",0) or 0),float(mark),int(p.get("side",0) or 0),FEE)
  except Exception:pass
 equity=max(0.0,realized_equity+unrealized)
 return equity,used,max(0.0,equity-used)

def _local_experiment_claim(symbol,action,side,analysis,price=None,extra=None):
 candle=int(analysis.get("signal_candle_time") or 0)
 payload={**analysis,"symbol":symbol,"action":action,"side":int(side or 0),"policy":CATERPILLAR_POLICY,
   "experiment":"Caterpillar 1.0","paper_leverage":25.0}
 if extra:payload.update(extra)
 ident="LOCAL_EXP:%s:%s:%s:%s"%(symbol,action,candle,int(side or 0))
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   row=db.execute("""insert into local_v12_signal_journal(id,ts,candle_time,action,side,price,features)
     values(%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict(id) do nothing returning id""",
     (ident,now(),candle,action,int(side or 0),price,json.dumps(payload,default=str))).fetchone()
   if row and action=="OBSERVE":
    db.execute("insert into scanner_observations(ts,module,payload) values(%s,%s,%s::jsonb)",
      (now(),"local_12token_h1_m15",json.dumps(payload,default=str)))
 if row:
  log_learning_decision("LOCAL12:%s:%s:%s:%s"%(symbol,action,candle,int(side or 0)),
    "local_12token_h1_m15",symbol,side,action,"local_signal_observed",price,None,
    25.0,payload)
 return bool(row)

def _local_experiment_watch_clear(symbol,reason):
 with LOCK:watch=copy.deepcopy(S.get("local_experiment_watch",{}).get(symbol))
 if not watch:return False
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   db.execute("delete from local_v12_watchlist where symbol=%s",(symbol,))
   db.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'local_experiment_watch_cleared',%s::jsonb)",
     (now(),json.dumps({"symbol":symbol,"reason":reason,"watch":watch},default=str)))
 with LOCK:S.setdefault("local_experiment_watch",{}).pop(symbol,None)
 return True

@account_mutation
def _local_experiment_watch_observe(symbol,watch,mark,m15,flow,stamp):
 updated=local4_update_watch(watch,mark,m15,flow,stamp)
 before=(watch or {}).get("context") or {};context=updated.get("context") or {}
 changed=before.get("phase")!=context.get("phase")
 with LOCK:last=float(S.setdefault("_local_experiment_watch_persist_epoch",{}).get(symbol,0) or 0)
 if changed or stamp-last>=30:
  with pg() as db:
   with db.transaction():
    STORE.fence(db)
    db.execute("update local_v12_watchlist set context=%s::jsonb where symbol=%s and exit_at=%s",
      (json.dumps(context,default=str),symbol,watch.get("exit_at")))
    if changed:
     db.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'local_experiment_caterpillar_phase',%s::jsonb)",
       (now(),json.dumps({"symbol":symbol,"side":watch.get("side"),"phase":context.get("phase"),"context":context},default=str)))
  with LOCK:S["_local_experiment_watch_persist_epoch"][symbol]=stamp
 with LOCK:
  live=S.get("local_experiment_watch",{}).get(symbol)
  if live and live.get("exit_at")==watch.get("exit_at"):S["local_experiment_watch"][symbol]=copy.deepcopy(updated)
 return updated

@account_mutation
def local_experiment_open(symbol,side,analysis,entry_kind="M15",m15=None,watch=None):
 if symbol not in LOCAL_EXPERIMENT_SYMBOLS or int(side or 0) not in (-1,1):return False
 if S.get("mode")!="PAPER_ONLY" or S.get("orders_enabled") or not analysis.get("ready"):return False
 if not analysis.get("h1_direction_anchor") or int(analysis.get("entry_side") or 0)!=int(side):return False
 if analysis.get("entry_blocked"):return False
 # Recheck at allocation time: scanning 12 markets and database writes take time.
 # A previously ranked candidate cannot bypass fresh flow or M15 confirmation.
 stamp=time.time()
 flow=MARKET_OBS.flow_context(symbol,stamp)
 selection=local4_entry_candidate(symbol,analysis,m15,flow,stamp)
 if not selection["eligible"]:return False
 with LOCK:current_anchor=copy.deepcopy(S.get("local_h1_direction",{}).get(symbol))
 if current_anchor and (int(current_anchor.get("entry_side") or 0)!=int(side) or
     int(current_anchor.get("signal_candle_time") or 0)!=int(analysis.get("signal_candle_time") or 0)):return False
 price=current_entry_price(symbol)
 if price is None:return False
 if entry_kind=="REENTRY":
  if not watch or int(watch.get("side") or 0)!=int(side):return False
  if int(analysis.get("entry_side") or 0)==-int(side):return False
  with LOCK:live_watch=copy.deepcopy(S.get("local_experiment_watch",{}).get(symbol))
  if not live_watch or live_watch.get("exit_at")!=watch.get("exit_at"):return False
  if not local4_reentry_ready(side,m15,price,live_watch,flow,stamp):return False
 leverage=25.0
 with LOCK:
  if not S.get("engine_active") or symbol in S.get("local_v12_positions",{}):return False
   # No arbitrary cap on sequential entries; one active position per symbol remains.
 equity,used,free=_local_experiment_margin_state()
 if equity<=0 or free<0.01:return False
 target_notional=equity*LOCAL_EXPERIMENT_MARGIN_FRACTION*leverage
 max_margin_per_position=equity*LOCAL_EXPERIMENT_MARGIN_FRACTION
 desired_margin=max_margin_per_position
 # Each new position receives 20% of CURRENT mark-to-market equity at 25x.
 # Five full positions can consume the initial $500. Further positions become
 # possible only when realized/unrealized profits create additional free equity.
 margin=min(desired_margin,free)
 if margin<0.01:return False
 notional=margin*leverage
 exposure_fill_ratio=(notional/target_notional) if target_notional>0 else 0.0
 price=float(price);opened=now();epoch=time.time()
 reentries=(int(watch.get("reentries") or 0)+1) if entry_kind=="REENTRY" and watch else 0
 origin_signal=int(analysis.get("signal_candle_time") or 0)
 claim_token=int((m15 or {}).get("candle_time") or origin_signal)
 features={**analysis,"symbol":symbol,"strategy_name":"Caterpillar 1.0","experiment":"Caterpillar 1.0",
  "policy":HYPE_SWING_POLICY,"caterpillar_policy":LOCAL4_FLOW_POLICY,"entry_kind":entry_kind,
  "candidate_selection":selection,
  "origin_h1_signal_candle":origin_signal,"swing_reentries":reentries,
  "reference_margin_fraction":LOCAL_EXPERIMENT_MARGIN_FRACTION,"reference_leverage":25.0,
  "target_notional":target_notional,"desired_margin":desired_margin,"max_margin_per_position":max_margin_per_position,
  "actual_margin":margin,"free_margin_before":free,"mark_to_market_equity_at_entry":equity,
  "exposure_fill_ratio":exposure_fill_ratio,"leverage":leverage,"leverage_source":"paper_fixed_25x",
  "mfe_price_move":0.0,"mae_price_move":0.0,"mfe_roe_pct":0.0,"mae_roe_pct":0.0,
  "entry_mark":price,"profit_lock_armed":False,
  "profit_lock_mode":"executed_flow_reversal_only","m15_entry_context":m15,
  "m15_reentry_context":m15 if entry_kind=="REENTRY" else None,
  "reentry_watch":copy.deepcopy(watch) if entry_kind=="REENTRY" else None,
  "estimated_round_trip_cost_move":2*FEE+0.0004,"execution_cost_budget_only":True}
 pos={"symbol":symbol,"side":int(side),"entry":price,"notional":notional,"margin":margin,"leverage":leverage,
   "opened":opened,"t":epoch,"signal_candle_time":origin_signal,"features":features}
 claim_id=("LOCAL_EXP:REENTRY:OPEN:%s:%s:%s:%s"%(symbol,claim_token,int(side),reentries)
   if entry_kind=="REENTRY" else "LOCAL_EXP:OPEN:%s:%s:%s"%(symbol,origin_signal,int(side)))
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   claim=db.execute("""insert into local_v12_signal_journal(id,ts,candle_time,action,side,price,features)
     values(%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict(id) do nothing returning id""",
     (claim_id,opened,claim_token,"REENTRY" if entry_kind=="REENTRY" else "OPEN",int(side),price,json.dumps(features,default=str))).fetchone()
   if not claim:return False
   row=db.execute("""insert into local_v12_positions(symbol,side,entry,notional,margin,leverage,opened,opened_epoch,signal_candle_time,features)
     values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict(symbol) do nothing returning symbol""",
     (symbol,int(side),price,notional,margin,leverage,opened,epoch,origin_signal,json.dumps(features,default=str))).fetchone()
   if not row:raise psycopg.Rollback()
   if entry_kind=="REENTRY":db.execute("delete from local_v12_watchlist where symbol=%s",(symbol,))
   db.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'local_experiment_trade_opened',%s::jsonb)",
    (now(),json.dumps({"strategy":"local_12token_h1_m15","symbol":symbol,"side":int(side),"entry_kind":entry_kind,
      "entry":price,"margin":margin,"notional":notional,"target_notional":target_notional,
      "exposure_fill_ratio":exposure_fill_ratio,"leverage":leverage,"equity":equity,"free_margin_before":free},default=str)))
 if not row:return False
 with LOCK:
  S.setdefault("local_v12_positions",{})[symbol]=pos
  if entry_kind=="REENTRY":S.setdefault("local_experiment_watch",{}).pop(symbol,None)
 log_learning_decision("LOCAL12:%s:%s:%s:%s"%(symbol,entry_kind,claim_token,int(side)),
   "local_12token_h1_m15",symbol,side,"OPEN" if entry_kind!="REENTRY" else "REENTRY",
   "confirmed_local_entry",price,None,leverage,features,opened)
 return True

@account_mutation
def local_experiment_close(symbol,price,reason,analysis=None,watch_context=None):
 with LOCK:pos=copy.deepcopy(S.get("local_v12_positions",{}).get(symbol))
 if not pos:return None
 price=float(price);pnl=paper_pnl(pos["notional"],pos["entry"],price,pos["side"],FEE)
 features=copy.deepcopy(pos.get("features") or {})
 if analysis:features["exit_analysis"]=analysis
 if watch_context:features["m15_profit_protection"]=watch_context
 features["actual_exit_reason"]=reason;features["actual_exit_mark"]=price
 watch=None
 if reason in ("m15_adverse_pressure_profit_protect","profit_lock_stop","m15_momentum_weakening",
               "m15_pressure_reversal","m15_pressure_reversal_profit_only","caterpillar_breakeven","executed_flow_counter_dominance","m15_opposite_control_exit"):
  watch={"symbol":symbol,"side":int(pos["side"]),
   "origin_signal_candle":int(features.get("origin_h1_signal_candle") or pos.get("signal_candle_time") or 0),
   "exit_price":price,"exit_at":now(),"expires_epoch":0.0,
   "reentries":int(features.get("swing_reentries",0) or 0),"context":copy.deepcopy(watch_context or {})}
  watch["context"].update(phase="WAIT_PULLBACK",counter_pressure_seen=False,
    caterpillar_policy=LOCAL4_FLOW_POLICY)
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   row=db.execute("delete from local_v12_positions where symbol=%s and opened=%s returning symbol",
     (symbol,pos["opened"])).fetchone()
   if not row:return None
   acct=db.execute("""update local_v12_account_state
     set equity=equity+%s,realized_pnl=realized_pnl+%s,updated_at=%s where id=1 returning equity,realized_pnl""",
     (pnl,pnl,now())).fetchone()
   db.execute("""insert into local_v12_trade_history(opened,closed,symbol,side,entry,exit,pnl,reason,margin,notional,leverage,features)
     values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
     (pos["opened"],now(),symbol,pos["side"],pos["entry"],price,pnl,reason,pos["margin"],pos["notional"],
      pos["leverage"],json.dumps(features,default=str)))
   if watch:
    db.execute("""insert into local_v12_watchlist(symbol,side,origin_signal_candle,exit_price,exit_at,expires_epoch,reentries,context)
      values(%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
      on conflict(symbol) do update set side=excluded.side,origin_signal_candle=excluded.origin_signal_candle,
      exit_price=excluded.exit_price,exit_at=excluded.exit_at,expires_epoch=excluded.expires_epoch,
      reentries=excluded.reentries,context=excluded.context""",
      (symbol,watch["side"],watch["origin_signal_candle"],watch["exit_price"],watch["exit_at"],0.0,
       watch["reentries"],json.dumps(watch["context"],default=str)))
   db.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'local_experiment_trade_closed',%s::jsonb)",
     (now(),json.dumps({"strategy":"local_12token_h1_m15","symbol":symbol,"side":pos["side"],"entry":pos["entry"],
       "exit":price,"pnl":pnl,"reason":reason,"equity":float(acct["equity"]),"watch_armed":bool(watch),
       "leverage":pos["leverage"],"exposure_fill_ratio":features.get("exposure_fill_ratio")},default=str)))
 with LOCK:
  S.setdefault("local_v12_positions",{}).pop(symbol,None)
  if watch:S.setdefault("local_experiment_watch",{})[symbol]=watch
  S["local_experiment_equity"]=float(acct["equity"])
  S["local_experiment_realized_pnl"]=float(acct["realized_pnl"])
  S["local_experiment_trades"]=int(S.get("local_experiment_trades",0) or 0)+1
 log_learning_decision("LOCAL12:CLOSE:%s:%s"%(symbol,pos.get("opened")),
   "local_12token_h1_m15",symbol,pos["side"],"CLOSED",reason,pos["entry"],None,
   pos["leverage"],features,pos.get("opened"))
 return {"symbol":symbol,"pnl":pnl,"reason":reason,"equity":float(acct["equity"])}

@account_mutation
def local_experiment_mark_positions(prices):
 with LOCK:positions=copy.deepcopy(S.get("local_v12_positions",{}))
 for symbol,pos in positions.items():
  mark=prices.get(symbol)
  if not mark:continue
  updated,liq=hype_update_path(pos,float(mark))
  updated.setdefault("features",{}).update(caterpillar_policy=LOCAL4_FLOW_POLICY,
    profit_lock_armed=False,profit_lock_mode="executed_flow_reversal_only")
  updated["features"].pop("profit_lock_stop",None)
  with LOCK:
   live=S.get("local_v12_positions",{}).get(symbol)
   if live and live.get("opened")==pos.get("opened"):S["local_v12_positions"][symbol]=updated
  flow=MARKET_OBS.flow_context(symbol,time.time())
  reason=local4_pressure_exit(updated,None,float(mark),flow)
  if reason:
   local_experiment_close(symbol,float(mark),reason,watch_context={"flow_context":flow,"observed_at":now()})
   continue
  if liq:
   local_experiment_close(symbol,float(mark),"paper_liquidation_proxy");continue
  stamp=time.time()
  with LOCK:last=float(S.setdefault("_local_experiment_path_persist_epoch",{}).get(symbol,0) or 0)
  if stamp-last<30:continue
  with pg() as db:
   with db.transaction():
    STORE.fence(db)
    db.execute("update local_v12_positions set features=%s::jsonb where symbol=%s and opened=%s",
      (json.dumps(updated["features"]),symbol,pos["opened"]))
  with LOCK:S["_local_experiment_path_persist_epoch"][symbol]=stamp

@account_mutation
def local4_fast_entries(prices):
 for symbol in LOCAL_EXPERIMENT_SYMBOLS:
  with LOCK:
   if symbol in S.get("local_v12_positions",{}):continue
   analysis=copy.deepcopy(S.get("_local4_analysis",{}).get(symbol))
   watch=copy.deepcopy(S.get("local_experiment_watch",{}).get(symbol))
  mark=prices.get(symbol)
  if not analysis or not mark:continue
  side=int(analysis.get("entry_side") or 0)
  if watch and int(watch.get("side") or 0)==-side:
   _local_experiment_watch_clear(symbol,"opposite_h1_pivot_invalidated_watch");watch=None
  flow=MARKET_OBS.flow_context(symbol,time.time())
  if watch:
   watch=_local_experiment_watch_observe(symbol,watch,float(mark),None,flow,time.time())
   if local4_reentry_ready(side,None,mark,watch,flow,time.time()):
    local_experiment_open(symbol,side,analysis,"REENTRY",None,watch)
  elif local4_entry_candidate(symbol,analysis,None,flow,time.time())["eligible"]:
   local_experiment_open(symbol,side,analysis,"ORDER_FLOW")

def local_experiment_risk_loop():
 # Protect observed peaks even while H1/M15 history fetches or scans are slow.
 # Use only fresh streamed/cached marks; never spend additional REST budget.
 while not SHUTDOWN.is_set():
  try:
   with LOCK:
    active=bool(S.get("engine_active")) and S.get("mode")=="PAPER_ONLY" and not S.get("orders_enabled")
    age=time.time()-float(S.get("_last_poll_epoch",0) or 0)
    prices=dict(S.get("_prices",{}))
   if active and 0<=age<=8 and prices:
    local_experiment_mark_positions(prices)
    # H1 -> M15 entries/reentries belong exclusively to local_experiment_loop.
    # Never submit orders from this price-only risk loop without M15 candles.
    with LOCK:S["sources"]["LocalRisk"]={"ok":True,"last_check":now(),"mode":"M15_entries_only_risk_price_monitor"}
  except LeaseLost as exc:
   with LOCK:
    S["engine_active"]=False;S["engine_error"]=str(exc)
  except Exception as exc:
   with LOCK:S["sources"]["LocalRisk"]={"ok":False,"last_check":now(),"error":type(exc).__name__+":"+str(exc)[:160]}
  SHUTDOWN.wait(.5)

def local_experiment_cancel_oversized_positions(prices):
 # One-time/routine guard for legacy PAPER positions created before the 20% cap.
 # Close at the current live mark so accounting/history remain truthful.
 equity,used,free=_local_experiment_margin_state()
 max_margin=max(0.0,equity*LOCAL_EXPERIMENT_MARGIN_FRACTION)
 with LOCK:items=[(sym,copy.deepcopy(pos)) for sym,pos in S.get("local_v12_positions",{}).items()]
 closed=[]
 for sym,pos in items:
  margin=float(pos.get("margin",0) or 0)
  mark=prices.get(sym)
  if margin<=max_margin+1e-9 or not mark:continue
  result=local_experiment_close(sym,float(mark),"operator_cancel_oversized_margin")
  if result:
   closed.append({"symbol":sym,"margin":margin,"max_margin":max_margin,"mark":float(mark)})
 if closed:
  try:journal("local_experiment_oversized_cleanup",None,{"closed":closed,"equity":equity,"limit_fraction":LOCAL_EXPERIMENT_MARGIN_FRACTION})
  except Exception:pass
 return closed

def local_experiment_stats():
 try:
  with pg() as db:
   agg=db.execute("""select count(*) as trades,sum(case when pnl>0 then 1 else 0 end) as wins,
      coalesce(sum(pnl),0) as pnl,avg(pnl) as avg_pnl
      from local_v12_trade_history""").fetchone()
   cutoff=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(hours=24)).isoformat()
   daily=db.execute("""select count(*) as trades,sum(case when pnl>0 then 1 else 0 end) as wins,
      coalesce(sum(pnl),0) as pnl from local_v12_trade_history where closed >= %s""",(cutoff,)).fetchone()
   rows=db.execute("""select symbol,count(*) as trades,sum(case when pnl>0 then 1 else 0 end) as wins,
      coalesce(sum(pnl),0) as pnl,avg(pnl) as avg_pnl,
      avg(coalesce((features->>'exposure_fill_ratio')::double precision,1)) as avg_fill
      from local_v12_trade_history group by symbol order by symbol""").fetchall()
  n=int(agg["trades"] or 0);w=int(agg["wins"] or 0)
  dn=int(daily["trades"] or 0);dw=int(daily["wins"] or 0)
  return {"rolling_24h":{"trades":dn,"wins":dw,"win_rate":round(dw/dn,4) if dn else None,"realized_pnl":float(daily["pnl"] or 0)},"trades":n,"wins":w,"win_rate":round(w/n,4) if n else None,"realized_pnl":float(agg["pnl"] or 0),
    "avg_pnl":float(agg["avg_pnl"]) if agg["avg_pnl"] is not None else None,
    "by_symbol":{r["symbol"]:{"trades":int(r["trades"] or 0),"wins":int(r["wins"] or 0),
      "win_rate":round(int(r["wins"] or 0)/int(r["trades"]),4) if int(r["trades"] or 0) else None,
      "pnl":float(r["pnl"] or 0),"avg_pnl":float(r["avg_pnl"]) if r["avg_pnl"] is not None else None,
      "avg_exposure_fill_ratio":float(r["avg_fill"]) if r["avg_fill"] is not None else None} for r in rows}}
 except Exception as exc:return {"error":type(exc).__name__+":"+str(exc)[:160]}

def _local_persisted_anchor(symbol):
 # During H1 bootstrap/restart keep trading the last confirmed local regime.
 # The regime remains valid until a newly completed H1 pivot confirms the opposite side.
 with LOCK:
  pos=copy.deepcopy(S.get("local_v12_positions",{}).get(symbol))
  watch=copy.deepcopy(S.get("local_experiment_watch",{}).get(symbol))
 for source in (pos,watch):
  if not source:continue
  features=copy.deepcopy(source.get("features") or source.get("context") or {})
  side=int(source.get("side") or features.get("entry_side") or 0)
  if side not in (-1,1):continue
  pivot_type=features.get("pivot_type") or ("LOCAL_HIGH" if side<0 else "LOCAL_LOW")
  pivot_price=features.get("pivot_price")
  candle=int(features.get("signal_candle_time") or features.get("origin_h1_signal_candle") or source.get("signal_candle_time") or source.get("origin_signal_candle") or 0)
  return {"ready":True,"persisted":True,"anchor_confirmed":True,"h1_direction_anchor":True,
    "pivot_type":pivot_type,"pivot_price":pivot_price,"entry_side":side,
    "signal_candle_time":candle,"pivot_candle_time":candle,
    "entry_blocked":False,"pending_pivot_type":None,"pending_pivot_price":None,
    "entry_block_reason":None,"reason":"persisted_confirmed_h1_local"}
 try:
  with pg() as db:
   row=db.execute("""select side,candle_time,features from local_v12_signal_journal
     where features->>'symbol'=%s and action in ('OBSERVE','OPEN','REENTRY')
     order by ts desc limit 1""",(symbol,)).fetchone()
  if not row:return None
  features=copy.deepcopy(row.get("features") or {})
  side=int(features.get("entry_side") or row.get("side") or 0)
  if side not in (-1,1):return None
  candle=int(features.get("signal_candle_time") or features.get("origin_h1_signal_candle") or row.get("candle_time") or 0)
  return {"ready":True,"persisted":True,"anchor_confirmed":True,"h1_direction_anchor":True,
    "pivot_type":features.get("pivot_type") or ("LOCAL_HIGH" if side<0 else "LOCAL_LOW"),
    "pivot_price":features.get("pivot_price"),"entry_side":side,
    "signal_candle_time":candle,"pivot_candle_time":int(features.get("pivot_candle_time") or candle),
    "entry_blocked":False,"pending_pivot_type":None,"pending_pivot_price":None,
    "entry_block_reason":None,"reason":"persisted_confirmed_h1_local"}
 except Exception:return None

def local_experiment_loop():
 last_observed={};pool=concurrent.futures.ThreadPoolExecutor(max_workers=24,thread_name_prefix="local-exp-m15")
 try:
  while not SHUTDOWN.is_set():
   try:
    with LOCK:
     active=bool(S.get("engine_active"))
     metadata_ready=bool(S.get("_day_volumes")) and bool(S.get("_max_leverage"))
    if not active:
     SHUTDOWN.wait(1);continue
    prices=refresh_market_prices(max_age=8.0)
    local_experiment_mark_positions(prices)
    jobs={}
    for symbol in LOCAL_EXPERIMENT_SYMBOLS:
     jobs[(symbol,"h1")]=pool.submit(_local_h1_candles,symbol)
     jobs[(symbol,"m15")]=pool.submit(_local_m15_candles,symbol)
    fetched={};fetch_errors={}
    for key,fut in jobs.items():
     try:fetched[key]=fut.result(timeout=12)
     except Exception as exc:fetch_errors[key]=type(exc).__name__+":"+str(exc)[:120]
    details={};entry_queue=[]
    for symbol in LOCAL_EXPERIMENT_SYMBOLS:
     mark=prices.get(symbol)
     if not mark:
      details[symbol]={"ok":False,"error":"mark_unavailable","max_leverage":market_max_leverage(symbol)}
      continue
     h1_error=fetch_errors.get((symbol,"h1"))
     persisted=None
     if h1_error:persisted=_local_persisted_anchor(symbol)
     if h1_error and not persisted:
      with LOCK:S.setdefault("_local4_analysis",{}).pop(symbol,None)
      details[symbol]={"ok":False,"error":h1_error,"max_leverage":market_max_leverage(symbol)}
      continue
     m15_rows,m15_ms=fetched.get((symbol,"m15"),([],int(time.time()*1000)))
     if persisted:
      analysis=persisted
      h1_rows=[];h1_ms=int(time.time()*1000)
     else:
      h1_rows,h1_ms=fetched[(symbol,"h1")]
      analysis=local_h1_direction(h1_rows,h1_ms,symbol)
     with LOCK:S.setdefault("_local4_analysis",{})[symbol]=copy.deepcopy(analysis)
     h1_context=({"ready":True,"persisted":True,"entry_side":analysis.get("entry_side"),
       "pivot_type":analysis.get("pivot_type"),"pivot_price":analysis.get("pivot_price")}
       if persisted else analyze_local_h1_context(h1_rows,h1_ms,symbol))
     with LOCK:
      pos=copy.deepcopy(S.get("local_v12_positions",{}).get(symbol))
      watch=copy.deepcopy(S.get("local_experiment_watch",{}).get(symbol))
     target_side=int((pos or watch or {}).get("side") or analysis.get("entry_side") or 1)
     m15_live=analyze_local_m15(m15_rows,m15_ms,target_side)
     flow=MARKET_OBS.flow_context(symbol,time.time())
     flow_imb=flow.get("flow_imbalance") if flow.get("trade_data_fresh") else None
     candle=analysis.get("signal_candle_time")
     if analysis.get("ready") and candle!=last_observed.get(symbol):
      _local_experiment_claim(symbol,"OBSERVE",analysis.get("entry_side",0),analysis,float(mark),
        {"m15":m15_live,"flow":flow,"flow_imbalance":flow_imb,"h1_context":h1_context})
      last_observed[symbol]=candle
     action=None
     if pos:
      h1_exit=("opposite_h1_local_emergency_exit" if analysis.get("ready") and analysis.get("anchor_confirmed") and int(analysis.get("entry_side") or 0)==-int(pos.get("side") or 0) else None)
      if not h1_exit:
       h1_exit=hype_position_exit(pos,analysis,float(mark)) if analysis.get("ready") else None
      if h1_exit:
       # Opposite H1 invalidates the trade thesis, regardless of PnL.
       # M15 exits likewise follow confirmed pressure, independently of PnL.
       closed=local_experiment_close(symbol,float(mark),h1_exit,analysis)
       action="H1_DIRECTION_INVALIDATION_EXIT:"+h1_exit if closed else None
      elif pressure_reason:=local4_pressure_exit(pos,m15_live,float(mark),flow):
       watch_context={"m15":m15_live,"h1_context":h1_context,"flow_imbalance":flow_imb,"flow_context":flow,
         "flow_source":"hyperliquid_ws_trades","observed_at":now(),"reason":pressure_reason}
       closed=local_experiment_close(symbol,float(mark),pressure_reason,analysis,watch_context)
       action="M15_COUNTER_PRESSURE_EXIT" if closed else None
     else:
      if analysis.get("entry_blocked"):action="WAIT_H1_CONFIRMATION:"+str(analysis.get("pending_pivot_type"))
      if watch:watch=_local_experiment_watch_observe(symbol,watch,float(mark),m15_live,flow,time.time())
      if watch:
       if analysis.get("ready") and int(analysis.get("entry_side") or 0)==-int(watch.get("side") or 0):
        _local_experiment_watch_clear(symbol,"opposite_h1_pivot_invalidated_watch");watch=None;action="WATCH_INVALIDATED_BY_H1"
       elif not analysis.get("entry_blocked") and local4_reentry_ready(int(watch.get("side") or 0),m15_live,float(mark),watch,flow,time.time()):
        selection=local4_entry_candidate(symbol,analysis,m15_live,flow,time.time())
        if selection["eligible"]:
         entry_queue.append({**selection,"analysis":analysis,"m15":m15_live,"watch":watch,"entry_kind":"REENTRY"})
         action="CANDIDATE_REENTRY"
      if not watch and not action:
       selection=local4_entry_candidate(symbol,analysis,m15_live,flow,time.time())
       if selection["eligible"]:
        entry_queue.append({**selection,"analysis":analysis,"m15":m15_live,"watch":None,"entry_kind":"ORDER_FLOW"})
        action="CANDIDATE_ENTRY"
       else:action="WAIT:"+selection["reason"]
     with LOCK:
      live=copy.deepcopy(S.get("local_v12_positions",{}).get(symbol))
      live_watch=copy.deepcopy(S.get("local_experiment_watch",{}).get(symbol))
     equity,used,free=_local_experiment_margin_state()
     ref_notional=equity*LOCAL_EXPERIMENT_MARGIN_FRACTION*25.0
     lev=25.0;required_margin=ref_notional/25.0
     details[symbol]={"ok":bool(analysis.get("ready")),"symbol":symbol,"mark":float(mark),"max_leverage":lev,
       "target_notional":round(ref_notional,4),"required_margin_for_full_target":round(required_margin,4),
       "position_open":bool(live),"side":int(live.get("side")) if live else None,
       "actual_margin":float(live.get("margin")) if live else None,"actual_notional":float(live.get("notional")) if live else None,
       "exposure_fill_ratio":float((live.get("features") or {}).get("exposure_fill_ratio",0)) if live else None,
       "watching_for_reentry":bool(live_watch),"watch_reentries":int(live_watch.get("reentries",0)) if live_watch else None,
       "caterpillar_phase":(live_watch.get("context") or {}).get("phase") if live_watch else ("IN_POSITION" if live else "WAIT_ENTRY"),
       "h1_local":{"ready":bool(analysis.get("ready")),"pivot_type":analysis.get("pivot_type"),
        "pivot_price":analysis.get("pivot_price"),"entry_side":analysis.get("entry_side"),"signal_candle_time":candle,
        "anchor_confirmed":analysis.get("anchor_confirmed"),"pivot_candle_time":analysis.get("pivot_candle_time"),
        "entry_blocked":analysis.get("entry_blocked",False),"pending_pivot_type":analysis.get("pending_pivot_type"),
        "pending_pivot_price":analysis.get("pending_pivot_price"),"entry_block_reason":analysis.get("entry_block_reason")},
       "m15_live":{"ready":bool(m15_live.get("ready")),"partial":m15_live.get("partial"),
        "adverse_score":m15_live.get("adverse_score"),"recovery_score":m15_live.get("recovery_score"),
        "flow_imbalance":flow_imb},"last_action":action,
       "error":analysis.get("reason") if not analysis.get("ready") else None}
    # Complete risk management for every symbol before allocating scarce margin.
    # The configured token order must never decide which signal receives capital.
    ranked=entry_queue
    for rank,candidate in enumerate(ranked,1):
     symbol=candidate["symbol"]
     selection={k:v for k,v in candidate.items() if k not in ("analysis","m15","watch")}
     details[symbol]["candidate_selection"]={**selection,"rank":rank}
     opened=local_experiment_open(symbol,candidate["side"],candidate["analysis"],candidate["entry_kind"],candidate["m15"],candidate["watch"])
     details[symbol]["last_action"]=("M15_RECOVERY_REENTRY" if candidate["entry_kind"]=="REENTRY" else "M15_ENTRY") if opened else "WAIT_ALLOCATION_OR_REVALIDATION"
     with LOCK:
      live=copy.deepcopy(S.get("local_v12_positions",{}).get(symbol))
      live_watch=copy.deepcopy(S.get("local_experiment_watch",{}).get(symbol))
     phase="IN_POSITION" if live else ((live_watch.get("context") or {}).get("phase","WAIT_ENTRY") if live_watch else "WAIT_ENTRY")
     details[symbol].update(position_open=bool(live),side=live.get("side") if live else None,
      actual_margin=live.get("margin") if live else None,actual_notional=live.get("notional") if live else None,
      exposure_fill_ratio=(live.get("features") or {}).get("exposure_fill_ratio") if live else None,
      watching_for_reentry=bool(live_watch),caterpillar_phase=phase)
    stats=local_experiment_stats()
    equity,used,free=_local_experiment_margin_state()
    ready_all=all(x.get("ok") for x in details.values())
    bootstrap_wait=bool(details) and all(x.get("ok") or "history_bootstrap_pending" in str(x.get("error") or "") for x in details.values())
    with LOCK:
     S["local_experiment_stats"]=stats
     S["sources"]["Caterpillar 1.0"]={"ok":ready_all or bootstrap_wait,"ready":ready_all,
       "warmup":bootstrap_wait and not ready_all,"last_check":now(),
       "mode":"Caterpillar 1.0 PAPER H1-M15 executed-flow","policy":LOCAL4_FLOW_POLICY,
       "symbols":list(LOCAL_EXPERIMENT_SYMBOLS),"paper_only":True,"starting_equity":LOCAL_EXPERIMENT_STARTING_EQUITY,
       "equity":equity,"used_margin":used,"free_margin":free,"realized_pnl":S.get("local_experiment_realized_pnl",0),
       "trades":S.get("local_experiment_trades",0),"open_positions":list(S.get("local_v12_positions",{})),
       "watching_for_reentry":list(S.get("local_experiment_watch",{})),"reference_margin_fraction":LOCAL_EXPERIMENT_MARGIN_FRACTION,
       "reference_leverage":25.0,"sizing":"20pct_current_mtm_equity_fixed25x_free_profit_reinvestment",
       "max_positions":"free_margin_and_one_active_position_per_symbol","compound":True,"details":details,"stats":stats,
       "selection_policy":LOCAL4_FLOW_POLICY,"ranked_candidates":[c["symbol"] for c in ranked],
       "rest_transport":HL_REST_BUDGET.status(),
       "error":None if (ready_all or bootstrap_wait) else "partial_symbol_scan_failure"}
   except LeaseLost as exc:
    with LOCK:S["sources"]["Caterpillar 1.0"]={"ok":False,"last_check":now(),"mode":"standby","error":str(exc)[:160]}
   except Exception as exc:
    with LOCK:S["sources"]["Caterpillar 1.0"]={"ok":False,"last_check":now(),"mode":"paper_h1_m15_caterpillar_exchange_max_leverage",
      "error":type(exc).__name__+":"+str(exc)[:160]}
    try:journal("local_experiment_error",None,{"error":type(exc).__name__+":"+str(exc)[:180]})
    except Exception:pass
   SHUTDOWN.wait(10)
 finally:
  pool.shutdown(wait=False,cancel_futures=True)


def _comparison_mtm(state_name,prices):
 with LOCK:
  realized=float(S.get(state_name+"_equity",500.0) or 0)
  positions=copy.deepcopy(S.get(state_name+"_positions",{}))
 unreal=0.0;used=0.0
 for symbol,pos in positions.items():
  mark=float(prices.get(symbol,pos["entry"]))
  unreal+=paper_pnl(pos["notional"],pos["entry"],mark,pos["side"],FEE)
  used+=float(pos.get("margin",0) or 0)
 total=realized+unreal
 return total,used,max(0.0,total-used),unreal

def _comparison_anchor(state_name,symbol):
 with LOCK:
  pos=copy.deepcopy(S.get(state_name+"_positions",{}).get(symbol))
  watch=copy.deepcopy(S.get(state_name+"_watch",{}).get(symbol)) if state_name in ("local_s1","local_s3") else None
 source=pos or watch
 if source:
  features=copy.deepcopy(source.get("features") or (source.get("context") or {}).get("anchor") or {})
  side=int(source.get("side") or features.get("entry_side") or 0)
  if side in (-1,1):
   candle=int(features.get("signal_candle_time") or features.get("origin_h1_signal_candle") or source.get("signal_candle_time") or source.get("origin_signal_candle") or 0)
   return {"ready":True,"persisted":True,"anchor_confirmed":True,"h1_direction_anchor":True,
    "pivot_type":features.get("pivot_type") or ("LOCAL_HIGH" if side<0 else "LOCAL_LOW"),
    "pivot_price":features.get("pivot_price"),"entry_side":side,"signal_candle_time":candle,
    "pivot_candle_time":int(features.get("pivot_candle_time") or candle),"entry_blocked":False,
    "pending_pivot_type":None,"pending_pivot_price":None,"entry_block_reason":None,
    "reason":"comparison_persisted_h1_anchor"}
 # Canonical Strategy 1 H1 regime is durable independently of any legacy
 # local_v12 book. A confirmed H1 local remains the structural side until a
 # later confirmed opposite H1 local replaces it.
 with LOCK:
  durable=copy.deepcopy(S.get("local_h1_direction",{}).get(symbol))
 if durable and durable.get("ready") and int(durable.get("entry_side") or 0) in (-1,1):
  durable["persisted"]=True
  durable["h1_direction_anchor"]=True
  durable["anchor_confirmed"]=True
  durable["reason"]="durable_local_h1_direction_fallback"
  return durable
 return _local_persisted_anchor(symbol)

@account_mutation
def _comparison_open(prefix,state_name,symbol,side,analysis,mark,entry_kind):
 if side not in (-1,1):return False
 with LOCK:
  if not S.get("engine_active") or symbol in S.get(state_name+"_positions",{}):return False
 prices=dict(S.get("_prices",{}))
 equity,used,free,_=_comparison_mtm(state_name,prices)
 margin=max(.01,equity*.20)
 if free+1e-9<margin:return False
 leverage=S1_REFERENCE_LEVERAGE if state_name=="local_s1" else 25.0
 notional=margin*leverage;opened=now();epoch=time.time()
 features={**copy.deepcopy(analysis),"strategy_name":state_name,"entry_kind":entry_kind,
   "reference_margin_fraction":.20,"reference_leverage":leverage,"estimated_round_trip_cost_move":2*FEE+.0004,
   "origin_h1_signal_candle":int(analysis.get("signal_candle_time") or 0)}
 pos={"symbol":symbol,"side":int(side),"entry":float(mark),"notional":notional,"margin":margin,"leverage":leverage,
      "opened":opened,"t":epoch,"signal_candle_time":int(analysis.get("signal_candle_time") or 0),"features":features}
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   row=db.execute(f"""insert into {prefix}_positions(symbol,side,entry,notional,margin,leverage,opened,opened_epoch,signal_candle_time,features)
     values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict(symbol) do nothing returning symbol""",
     (symbol,int(side),float(mark),notional,margin,leverage,opened,epoch,pos["signal_candle_time"],json.dumps(features,default=str))).fetchone()
   if not row:return False
   if state_name in ("local_s1","local_s3"):db.execute(f"delete from {prefix}_watchlist where symbol=%s",(symbol,))
 with LOCK:
  S.setdefault(state_name+"_positions",{})[symbol]=pos
  if state_name in ("local_s1","local_s3"):S.setdefault(state_name+"_watch",{}).pop(symbol,None)
 return True

@account_mutation
def _comparison_close(prefix,state_name,symbol,mark,reason,arm_watch=False,watch_phase="WAIT_PULLBACK"):
 with LOCK:pos=copy.deepcopy(S.get(state_name+"_positions",{}).get(symbol))
 if not pos:return None
 pnl=paper_pnl(pos["notional"],pos["entry"],float(mark),pos["side"],FEE)
 features=copy.deepcopy(pos.get("features") or {});features["actual_exit_reason"]=reason;features["actual_exit_mark"]=float(mark)
 watch=None
 if arm_watch and state_name in ("local_s1","local_s3"):
  watch={"symbol":symbol,"side":int(pos["side"]),"origin_signal_candle":int(pos.get("signal_candle_time") or 0),
   "exit_price":float(mark),"exit_at":now(),"reentries":int(features.get("swing_reentries",0) or 0),
   "context":{"phase":watch_phase,"counter_pressure_seen":False,"pullback_extreme":float(mark),"anchor":copy.deepcopy(features)}}
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   row=db.execute(f"delete from {prefix}_positions where symbol=%s and opened=%s returning symbol",(symbol,pos["opened"])).fetchone()
   if not row:return None
   acct=db.execute(f"""update {prefix}_account_state set equity=equity+%s,realized_pnl=realized_pnl+%s,updated_at=%s
     where id=1 returning equity,realized_pnl""",(pnl,pnl,now())).fetchone()
   db.execute(f"""insert into {prefix}_trade_history(opened,closed,symbol,side,entry,exit,pnl,reason,margin,notional,leverage,features)
     values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
     (pos["opened"],now(),symbol,pos["side"],pos["entry"],float(mark),pnl,reason,pos["margin"],pos["notional"],pos["leverage"],json.dumps(features,default=str)))
   if watch:
    db.execute(f"""insert into {prefix}_watchlist(symbol,side,origin_signal_candle,exit_price,exit_at,reentries,context)
      values(%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict(symbol) do update set side=excluded.side,
      origin_signal_candle=excluded.origin_signal_candle,exit_price=excluded.exit_price,exit_at=excluded.exit_at,
      reentries=excluded.reentries,context=excluded.context""",
      (symbol,watch["side"],watch["origin_signal_candle"],watch["exit_price"],watch["exit_at"],watch["reentries"],json.dumps(watch["context"],default=str)))
 with LOCK:
  S.setdefault(state_name+"_positions",{}).pop(symbol,None)
  S[state_name+"_equity"]=float(acct["equity"]);S[state_name+"_realized_pnl"]=float(acct["realized_pnl"])
  S[state_name+"_trades"]=int(S.get(state_name+"_trades",0) or 0)+1
  if watch:S.setdefault(state_name+"_watch",{})[symbol]=watch
 return {"pnl":pnl,"equity":float(acct["equity"]),"reason":reason}

@account_mutation
def _comparison_watch_update(prefix,state_name,symbol,watch,mark,m15,flow):
 updated=(local4_update_watch if state_name=="local_s1" else caterpillar_update_watch)(watch,float(mark),m15,flow,time.time())
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   db.execute(f"update {prefix}_watchlist set context=%s::jsonb where symbol=%s",
    (json.dumps(updated.get("context") or {},default=str),symbol))
 with LOCK:
  if symbol in S.get(state_name+"_watch",{}):S[state_name+"_watch"][symbol]=copy.deepcopy(updated)
 return updated

def _comparison_stats(prefix):
 try:
  with pg() as db:
   row=db.execute(f"""select count(*) n,coalesce(sum(pnl),0) pnl,
     sum(case when pnl>0 then 1 else 0 end) wins from {prefix}_trade_history""").fetchone()
  n=int(row["n"] or 0);wins=int(row["wins"] or 0)
  return {"trades":n,"wins":wins,"win_rate":round(wins/n,4) if n else None,"realized_pnl":float(row["pnl"] or 0)}
 except Exception as exc:return {"error":type(exc).__name__+":"+str(exc)[:120]}

@account_mutation
def _comparison_update_path(prefix,state_name,symbol,position,mark):
 updated,_=hype_update_path(position,float(mark))
 oldf=(position or {}).get("features") or {};newf=updated.get("features") or {}
 if newf==oldf:return updated
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   db.execute(f"update {prefix}_positions set features=%s::jsonb where symbol=%s and opened=%s",
    (json.dumps(newf,default=str),symbol,position.get("opened")))
 with LOCK:
  if symbol in S.get(state_name+"_positions",{}):S[state_name+"_positions"][symbol]=copy.deepcopy(updated)
 return updated

def _s1_weakening_exit(position,m15,mark,flow):
 if not position or not m15 or not m15.get("ready"):return False
 side=int(position.get("side") or 0);entry=float(position.get("entry") or 0);mark=float(mark or 0)
 if side not in (-1,1) or entry<=0 or mark<=0:return False
 features=position.get("features") or {}
 favorable=side*(mark/entry-1.0)
 floor=max(.0002,float(features.get("estimated_round_trip_cost_move",0) or 0))
 if favorable<=floor:return False
 if not (flow or {}).get("trade_data_fresh"):return False
 try:imb=float((flow or {}).get("flow_imbalance"))
 except (TypeError,ValueError):return False
 if side*imb>-0.12:return False
 adverse=int(m15.get("adverse_score") or 0)
 candle_reversal=(int(m15.get("candle_direction") or 0)==-side and float(m15.get("body_fraction") or 0)>=.42)
 if adverse<2 and not candle_reversal:return False
 peak=max(0.0,float(features.get("mfe_price_move",0) or 0),favorable)
 typical=float(m15.get("median_range_move") or .008)
 recoil_floor=max(.0006,min(.0015,typical*.15))
 return (peak-favorable)>=recoil_floor

def _s1_entry_not_chased(analysis,m15,mark):
 if not analysis or not m15 or not m15.get("ready"):return False
 try:
  ref=float(analysis.get("confirmation_close") or analysis.get("pivot_price") or 0)
  mark=float(mark or 0);typical=float(m15.get("median_range_move") or .008)
 except (TypeError,ValueError):return False
 if ref<=0 or mark<=0:return False
 # Do not execute an H1/M15 signal after price has already travelled far away
 # from the confirmation area. 2x the normal M15 range is allowed, bounded
 # between 0.40% and 2.00% so ordinary volatility is not treated as staleness.
 limit=max(.004,min(.020,typical*2.0))
 return abs(mark/ref-1.0)<=limit

S1_REFERENCE_LEVERAGE=25.0

def _s1_adaptive_stop(position,m15,mark,flow):
 """Universal protective stop for every Strategy 1 symbol.

 H1 decides direction. M15/flow decide whether we should remain in the trade.
 The stop is a last-resort guard, not the normal exit. It scales from each
 symbol's observed M15 range, so the same logic can be used for BTC/ETH/SOL
 and volatile alts without symbol-specific thresholds.
 """
 if not position or not m15 or not m15.get("ready"):return None
 try:
  side=int(position.get("side") or 0);entry=float(position.get("entry") or 0);mark=float(mark or 0)
  typical=max(.0005,float(m15.get("median_range_move") or .008))
  leverage=max(1.0,float(position.get("leverage") or S1_REFERENCE_LEVERAGE))
 except (TypeError,ValueError):return None
 if side not in (-1,1) or entry<=0 or mark<=0:return None
 adverse=max(0.0,-side*(mark/entry-1.0))

 # Soft protective level sits outside ordinary M15 noise. It only executes
 # when the adverse candle/flow confirms that this is not a random wick.
 soft_stop=max(.0075,min(.0180,typical*1.35))

 fresh=bool((flow or {}).get("trade_data_fresh"))
 try:imb=float((flow or {}).get("flow_imbalance")) if fresh else None
 except (TypeError,ValueError):imb=None
 counter_flow=(imb is not None and side*imb<=-.12)
 candle_adverse=(int(m15.get("candle_direction") or 0)==-side and float(m15.get("body_fraction") or 0)>=.45)
 strong_adverse=bool(m15.get("strong_adverse_pressure")) and int(m15.get("adverse_score") or 0)>=3

 if adverse>=soft_stop and candle_adverse and (counter_flow or strong_adverse):
  return {"reason":"s1_confirmed_protective_stop","adverse_move":adverse,"stop_move":soft_stop,
    "leverage":leverage,"approx_gross_roe_pct":-adverse*leverage*100.0}

 # Catastrophe level is wider than normal noise and also volatility-scaled.
 # This prevents a runaway loss when data/flow confirmation arrives late.
 hard_stop=max(.0150,min(.0250,typical*1.75))
 if adverse>=hard_stop:
  return {"reason":"s1_hard_catastrophe_stop","adverse_move":adverse,"stop_move":hard_stop,
    "leverage":leverage,"approx_gross_roe_pct":-adverse*leverage*100.0}
 return None

def comparison_strategies_loop():
 pool=concurrent.futures.ThreadPoolExecutor(max_workers=16,thread_name_prefix="local-compare")
 while not SHUTDOWN.is_set():
  try:
   with LOCK:
    if not S.get("engine_active"):
     SHUTDOWN.wait(1);continue
   prices=refresh_market_prices(max_age=8.0)
   jobs={}
   for symbol in LOCAL_EXPERIMENT_SYMBOLS:
    jobs[(symbol,"h1")]=pool.submit(_local_h1_candles,symbol)
    jobs[(symbol,"m15")]=pool.submit(_local_m15_candles,symbol)
   fetched={};errors={}
   for key,fut in jobs.items():
    try:fetched[key]=fut.result(timeout=12)
    except Exception as exc:errors[key]=type(exc).__name__+":"+str(exc)[:120]
   s1_details={};s2_details={}
   for symbol in LOCAL_EXPERIMENT_SYMBOLS:
    mark=prices.get(symbol)
    if not mark:
     s1_details[symbol]={"ok":False,"error":"mark_unavailable"};s2_details[symbol]={"ok":False,"error":"mark_unavailable"};continue
    h1_error=errors.get((symbol,"h1"))
    anchor1=_comparison_anchor("local_s1",symbol) if h1_error else None
    anchor2=_comparison_anchor("local_s2",symbol) if h1_error else None
    if h1_error and not anchor1 and not anchor2:
     s1_details[symbol]={"ok":False,"error":h1_error};s2_details[symbol]={"ok":False,"error":h1_error};continue
    if h1_error:
     a1=anchor1 or anchor2;a2=anchor2 or anchor1
    else:
     h1_rows,h1_ms=fetched[(symbol,"h1")]
     live=local_h1_direction(h1_rows,h1_ms,symbol)
     # A transient incomplete/new H1 reconstruction must never erase an
     # already-confirmed structural regime. Keep the durable H1 anchor until
     # a newly confirmed opposite pivot is available.
     if not live.get("ready"):
      durable=_comparison_anchor("local_s1",symbol)
      a1=copy.deepcopy(durable or live)
     else:
      a1=copy.deepcopy(live)
     a2=copy.deepcopy(a1)
    m15_rows,m15_ms=fetched.get((symbol,"m15"),([],int(time.time()*1000)))
    flow=MARKET_OBS.flow_context(symbol,time.time())

    # Strategy 1: restored profitable H1->M15 Caterpillar with cost-aware profit floor.
    with LOCK:
     p1=copy.deepcopy(S.get("local_s1_positions",{}).get(symbol));w1=copy.deepcopy(S.get("local_s1_watch",{}).get(symbol))
    side1=int((p1 or w1 or {}).get("side") or a1.get("entry_side") or 1)
    m15=analyze_local_m15(m15_rows,m15_ms,side1)
    act1=None
    if p1:
     p1=_comparison_update_path("local_s1","local_s1",symbol,p1,float(mark))
     h1exit=("opposite_h1_local_emergency_exit" if a1.get("ready") and a1.get("anchor_confirmed") and int(a1.get("entry_side") or 0)==-int(p1.get("side") or 0) else None)
     if not h1exit:h1exit=hype_position_exit(p1,a1,float(mark)) if a1.get("ready") else None
     entry=float(p1["entry"]);favorable=int(p1["side"])*(float(mark)/entry-1.0)
     floor=max(.0002,float((p1.get("features") or {}).get("estimated_round_trip_cost_move",0) or 0))
     weakening=_s1_weakening_exit(p1,m15,float(mark),flow)
     pressure_reason=local4_pressure_exit(p1,m15,float(mark),flow)
     stop_hit=_s1_adaptive_stop(p1,m15,float(mark),flow)
     if h1exit:
      # A confirmed opposite H1 local invalidates the old thesis regardless of PnL.
      if _comparison_close("local_s1","local_s1",symbol,float(mark),h1exit):act1="H1_OPPOSITE_EXIT"
     elif pressure_reason:
      # Real counter-pressure is an exit signal even if the trade is slightly red.
      # Waiting for it to recover is exactly what created the -30/-40% ROE tails.
      if _comparison_close("local_s1","local_s1",symbol,float(mark),pressure_reason,True,"WAIT_PULLBACK"):act1="M15_PRESSURE_EXIT"
     elif stop_hit:
      if _comparison_close("local_s1","local_s1",symbol,float(mark),stop_hit["reason"],True,"WAIT_PULLBACK"):act1="ADAPTIVE_STOP_EXIT"
     elif weakening:
      if _comparison_close("local_s1","local_s1",symbol,float(mark),"m15_weakening_profit_exit",True,"WAIT_PULLBACK"):act1="M15_WEAKENING_EXIT"
    else:
     # Fresh entries need an observed opposite M15 pullback before renewed H1-side movement.
     with LOCK:
      pullbacks=S.setdefault("_s1_initial_pullback",{})
      anchor_key=(int(a1.get("signal_candle_time") or 0),int(a1.get("entry_side") or 0))
      state=pullbacks.get(symbol)
      if not state or tuple(state.get("anchor",()))!=anchor_key:
       state={"anchor":anchor_key,"counter_seen":False}
       pullbacks[symbol]=state
      direction=local4_m15_direction(m15)
      if anchor_key[1] in (-1,1) and direction==-anchor_key[1]:
       state["counter_seen"]=True
      initial_ready=bool(state.get("counter_seen")) and direction==anchor_key[1]
     if w1:
      if a1.get("ready") and int(a1.get("entry_side") or 0)==-int(w1.get("side") or 0):
       with pg() as db:
        with db.transaction():STORE.fence(db);db.execute("delete from local_s1_watchlist where symbol=%s",(symbol,))
       with LOCK:S.setdefault("local_s1_watch",{}).pop(symbol,None)
       w1=None;act1="WATCH_INVALIDATED_BY_H1"
      else:w1=_comparison_watch_update("local_s1","local_s1",symbol,w1,float(mark),m15,flow)
     if w1 and local4_reentry_ready(int(w1["side"]),m15,float(mark),w1,flow,time.time()):
      if _comparison_open("local_s1","local_s1",symbol,int(w1["side"]),a1,float(mark),"REENTRY"):act1="M15_RECOVERY_REENTRY"
     elif not w1 and a1.get("ready") and not a1.get("entry_blocked"):
      side=int(a1.get("entry_side") or 0)
      candidate=local4_entry_candidate(symbol,a1,m15,flow,time.time())
      if side in (-1,1) and initial_ready and candidate.get("eligible"):
       if _comparison_open("local_s1","local_s1",symbol,side,a1,float(mark),"M15"):act1="M15_ENTRY"
    with LOCK:p1=copy.deepcopy(S.get("local_s1_positions",{}).get(symbol));w1=copy.deepcopy(S.get("local_s1_watch",{}).get(symbol))
    s1_details[symbol]={"ok":bool(a1.get("ready")),"h1_local":{"pivot_type":a1.get("pivot_type"),"pivot_price":a1.get("pivot_price"),
      "entry_side":a1.get("entry_side"),"signal_candle_time":a1.get("signal_candle_time"),"persisted":a1.get("persisted",False)},
      "position_open":bool(p1),"side":p1.get("side") if p1 else None,"watching_for_reentry":bool(w1),
      "m15":{"ready":m15.get("ready"),"adverse_score":m15.get("adverse_score"),"recovery_score":m15.get("recovery_score"),
       "flow_imbalance":flow.get("flow_imbalance"),"return_15m":m15.get("return_15m"),
       "strong_adverse_pressure":m15.get("strong_adverse_pressure"),"recovery_confirmed":m15.get("recovery_confirmed")},
      "last_action":act1 or ("IN_POSITION" if p1 else ("WAIT_RESUMPTION" if w1 else "WAIT_ENTRY")),"error":None}

    # Strategy 2 frozen in S1_ONLY_MODE.
    s2_details[symbol]={"ok":False,"disabled":True,"last_action":"FROZEN_S1_ONLY","error":None}
   s1_total,s1_used,s1_free,s1_unreal=_comparison_mtm("local_s1",prices)
   s2_total,s2_used,s2_free,s2_unreal=500.0,0.0,500.0,0.0
   s1stats=_comparison_stats("local_s1");s2stats={"trades":0,"wins":0,"win_rate":None,"realized_pnl":0.0}
   with LOCK:
    S["sources"]["Strategy 1 — Restored Caterpillar"]={"ok":all(x.get("ok") for x in s1_details.values()),"ready":all(x.get("ok") for x in s1_details.values()),
      "last_check":now(),"mode":"paper_universal_h1_m15_flow_weakening_reentry_25x_protective_stop","symbols":list(LOCAL_EXPERIMENT_SYMBOLS),
      "starting_equity":500.0,"equity":s1_total,"realized_equity":S.get("local_s1_equity",500.0),"unrealized_pnl":s1_unreal,
      "used_margin":s1_used,"free_margin":s1_free,"reference_margin_fraction":.20,"reference_leverage":25.0,
      "compound":True,"open_positions":list(S.get("local_s1_positions",{})),"details":s1_details,"stats":s1stats,"error":None}
    S["sources"]["Strategy 2 — H1 Pivot Swing"]={"ok":True,"ready":False,"disabled":True,
      "last_check":now(),"mode":"paper_h1_local_high_to_low_and_low_to_high","symbols":list(LOCAL_EXPERIMENT_SYMBOLS),
      "starting_equity":500.0,"equity":s2_total,"realized_equity":S.get("local_s2_equity",500.0),"unrealized_pnl":s2_unreal,
      "used_margin":s2_used,"free_margin":s2_free,"reference_margin_fraction":.20,"reference_leverage":25.0,
      "compound":True,"open_positions":list(S.get("local_s2_positions",{})),"details":s2_details,"stats":s2stats,
      "exit_rule":"LOCAL_HIGH short -> LOCAL_LOW close+long; LOCAL_LOW long -> LOCAL_HIGH close+short","error":None}
  except LeaseLost as exc:
   with LOCK:
    S["sources"]["Strategy 1 — Restored Caterpillar"]={"ok":False,"error":str(exc)[:160],"last_check":now()}
    S["sources"]["Strategy 2 — H1 Pivot Swing"]={"ok":False,"error":str(exc)[:160],"last_check":now()}
  except Exception as exc:
   err=type(exc).__name__+":"+str(exc)[:160]
   with LOCK:
    S["sources"]["Strategy 1 — Restored Caterpillar"]={"ok":False,"error":err,"last_check":now()}
    S["sources"]["Strategy 2 — H1 Pivot Swing"]={"ok":False,"error":err,"last_check":now()}
  SHUTDOWN.wait(5)
 pool.shutdown(wait=False,cancel_futures=True)

def strategy3_local12_loop():
 pool=concurrent.futures.ThreadPoolExecutor(max_workers=24,thread_name_prefix="local-s3-v10")
 try:
  while not SHUTDOWN.is_set():
   try:
    with LOCK:
     if not S.get("engine_active"):
      SHUTDOWN.wait(1);continue
    prices=refresh_market_prices(max_age=8.0)
    jobs={}
    for symbol in LOCAL_S3_SYMBOLS:
     jobs[(symbol,"h1")]=pool.submit(_local_h1_candles,symbol)
     jobs[(symbol,"m15")]=pool.submit(_local_m15_candles,symbol)
    fetched={};errors={}
    for key,fut in jobs.items():
     try:fetched[key]=fut.result(timeout=12)
     except Exception as exc:errors[key]=type(exc).__name__+":"+str(exc)[:120]
    details={}
    for symbol in LOCAL_S3_SYMBOLS:
     mark=prices.get(symbol)
     h1err=errors.get((symbol,"h1"))
     if not mark:
      details[symbol]={"ok":False,"error":"mark_unavailable"};continue
     if h1err:
      analysis=_comparison_anchor("local_s3",symbol)
      if not analysis:
       details[symbol]={"ok":False,"error":h1err};continue
     else:
      h1_rows,h1_ms=fetched[(symbol,"h1")]
      analysis=local_h1_direction(h1_rows,h1_ms,symbol)
     m15_rows,m15_ms=fetched.get((symbol,"m15"),([],int(time.time()*1000)))
     with LOCK:
      pos=copy.deepcopy(S.get("local_s3_positions",{}).get(symbol))
      watch=copy.deepcopy(S.get("local_s3_watch",{}).get(symbol))
     side=int((pos or watch or {}).get("side") or analysis.get("entry_side") or 1)
     m15=analyze_local_m15(m15_rows,m15_ms,side)
     flow=MARKET_OBS.flow_context(symbol,time.time())
     action=None
     if pos:
      h1exit=hype_position_exit(pos,analysis,float(mark)) if analysis.get("ready") else None
      entry=float(pos["entry"]);favorable=int(pos["side"])*(float(mark)/entry-1.0)
      floor=max(.0002,float((pos.get("features") or {}).get("estimated_round_trip_cost_move",0) or 0))
      be=caterpillar_breakeven(pos,float(mark))
      if h1exit and favorable>floor:
       if _comparison_close("local_s3","local_s3",symbol,float(mark),h1exit+"_profit_only"):action="H1_OPPOSITE_EXIT"
      elif be is not None:
       if _comparison_close("local_s3","local_s3",symbol,float(mark),"v10_cost_aware_profit_floor",True):action="PROFIT_FLOOR_EXIT"
      elif caterpillar_pressure_exit(pos,m15,float(mark),flow) and favorable>floor:
       if _comparison_close("local_s3","local_s3",symbol,float(mark),"m15_pressure_reversal_profit_only",True):action="M15_WEAKENING_EXIT"
     else:
      if watch:
       if analysis.get("ready") and int(analysis.get("entry_side") or 0)==-int(watch.get("side") or 0):
        with pg() as db:
         with db.transaction():
          STORE.fence(db);db.execute("delete from local_s3_watchlist where symbol=%s",(symbol,))
        with LOCK:S.setdefault("local_s3_watch",{}).pop(symbol,None)
        watch=None;action="WATCH_INVALIDATED_BY_H1"
       else:watch=_comparison_watch_update("local_s3","local_s3",symbol,watch,float(mark),m15,flow)
      if watch and caterpillar_reentry_ready(int(watch["side"]),m15,float(mark),watch,flow,time.time()):
       if _comparison_open("local_s3","local_s3",symbol,int(watch["side"]),analysis,float(mark),"REENTRY"):action="M15_RECOVERY_REENTRY"
      elif not watch and analysis.get("ready") and not analysis.get("entry_blocked"):
       imbalance=flow.get("flow_imbalance") if flow.get("trade_data_fresh") else None
       wanted=int(analysis.get("entry_side") or 0)
       if wanted in (-1,1) and imbalance is not None and wanted*float(imbalance)>=.12 and local_m15_reentry_ready(wanted,m15,imbalance):
        if _comparison_open("local_s3","local_s3",symbol,wanted,analysis,float(mark),"M15"):action="M15_ENTRY"
     with LOCK:
      live=copy.deepcopy(S.get("local_s3_positions",{}).get(symbol))
      live_watch=copy.deepcopy(S.get("local_s3_watch",{}).get(symbol))
     details[symbol]={"ok":bool(analysis.get("ready")),"h1_local":{"pivot_type":analysis.get("pivot_type"),
       "pivot_price":analysis.get("pivot_price"),"entry_side":analysis.get("entry_side"),
       "signal_candle_time":analysis.get("signal_candle_time"),"persisted":analysis.get("persisted",False)},
       "position_open":bool(live),"side":live.get("side") if live else None,"watching_for_reentry":bool(live_watch),
       "m15":{"ready":m15.get("ready"),"adverse_score":m15.get("adverse_score"),"recovery_score":m15.get("recovery_score")},
       "last_action":action or ("IN_POSITION" if live else ("WAIT_RESUMPTION" if live_watch else "WAIT_ENTRY")),"error":None}
    total,used,free,unreal=_comparison_mtm("local_s3",prices)
    stats=_comparison_stats("local_s3")
    with LOCK:
     S["sources"]["Strategy 3 — Local12 v10"]={"ok":all(x.get("ok") for x in details.values()),"ready":all(x.get("ok") for x in details.values()),
       "last_check":now(),"mode":"paper_local12_v10_h1_m15_profit_floor","policy":"local_h1_m15_caterpillar_v10_strict_reentry_profit_floor",
       "symbols":list(LOCAL_S3_SYMBOLS),"starting_equity":500.0,"equity":total,
       "realized_equity":S.get("local_s3_equity",500.0),"unrealized_pnl":unreal,"used_margin":used,"free_margin":free,
       "reference_margin_fraction":.20,"reference_leverage":25.0,"compound":True,
       "open_positions":list(S.get("local_s3_positions",{})),"details":details,"stats":stats,"error":None}
   except LeaseLost as exc:
    with LOCK:S["sources"]["Strategy 3 — Local12 v10"]={"ok":False,"error":str(exc)[:160],"last_check":now()}
   except Exception as exc:
    with LOCK:S["sources"]["Strategy 3 — Local12 v10"]={"ok":False,"error":type(exc).__name__+":"+str(exc)[:160],"last_check":now()}
   SHUTDOWN.wait(5)
 finally:
  pool.shutdown(wait=False,cancel_futures=True)

def hype_h1_local_swing_loop():
 last_observed={};last_observation=0.;pool=concurrent.futures.ThreadPoolExecutor(max_workers=4,thread_name_prefix="local-m15-swing")
 try:
  while not SHUTDOWN.is_set():
   try:
    with LOCK:active=bool(S.get("engine_active"))
    if not active:
     SHUTDOWN.wait(1);continue
    prices=refresh_market_prices(max_age=8.0)
    jobs={}
    for symbol in LOCAL_SWING_SYMBOLS:
     jobs[(symbol,"h1")]=pool.submit(_local_h1_candles,symbol)
     jobs[(symbol,"m15")]=pool.submit(_local_m15_candles,symbol)
    fetched={};fetch_errors={}
    for key,fut in jobs.items():
     try:fetched[key]=fut.result(timeout=12)
     except Exception as exc:fetch_errors[key]=type(exc).__name__+":"+str(exc)[:120]
    details={}
    for symbol in LOCAL_SWING_SYMBOLS:
     mark=prices.get(symbol)
     if symbol in fetch_errors or not mark:
      details[symbol]={"ok":False,"error":fetch_errors.get(symbol) or "mark_unavailable","position_open":symbol in S.get("local_swing_positions",{})}
      continue
     h1_rows,h1_ms=fetched[(symbol,"h1")]
     m15_rows,m15_ms=fetched.get((symbol,"m15"),([],int(time.time()*1000)))
     analysis=local_h1_direction(h1_rows,h1_ms,symbol)
     h1_context=analyze_local_h1_context(h1_rows,h1_ms,symbol)
     with LOCK:
      pos=copy.deepcopy(S.get("local_swing_positions",{}).get(symbol))
      watch=copy.deepcopy(S.get("local_swing_watch",{}).get(symbol))
     target_side=int((pos or watch or {}).get("side") or analysis.get("entry_side") or 1)
     m15_live=analyze_local_m15(m15_rows,m15_ms,target_side)
     flow=MARKET_OBS.context(symbol,time.time())
     flow_imb=flow.get("flow_imbalance") if flow.get("trade_data_fresh") else None
     candle=analysis.get("signal_candle_time")
     if analysis.get("ready") and candle!=last_observed.get(symbol):
      _local_claim(symbol,"OBSERVE",analysis.get("entry_side",0),analysis,float(mark))
      last_observed[symbol]=candle
     if analysis.get("ready"):_local_update_shadows(symbol,analysis,float(mark))

     action=None
     if pos:
      h1_exit=hype_position_exit(pos,analysis,float(mark)) if analysis.get("ready") else None
      if h1_exit:
       closed=local_swing_close(symbol,float(mark),h1_exit,analysis)
       action="H1_EXIT:"+h1_exit if closed else None
      elif caterpillar_pressure_exit(pos,m15_live,float(mark),flow):
       watch_context={"m15":m15_live,"h1_context":h1_context,"flow_imbalance":flow_imb,"flow_context":flow,
        "flow_source":"hyperliquid_ws_trades","observed_at":now(),"reason":"m15_counter_pressure_while_profitable"}
       closed=local_swing_close(symbol,float(mark),"m15_pressure_reversal",analysis,watch_context)
       action="M15_PROFIT_PROTECT_EXIT" if closed else None
     else:
      if watch:watch=_local_watch_observe(symbol,watch,float(mark),m15_live,flow,time.time())
      if watch:
       if analysis.get("ready") and int(analysis.get("entry_side") or 0)==-int(watch.get("side") or 0):
        _local_watch_clear(symbol,"opposite_h1_pivot_invalidated_watch");watch=None;action="WATCH_INVALIDATED_BY_H1"
       elif (analysis.get("ready") and int(analysis.get("entry_side") or 0)==int(watch.get("side") or 0)
             and int(analysis.get("signal_candle_time") or 0)>int(watch.get("origin_signal_candle") or 0)
             and caterpillar_reentry_ready(int(watch.get("side") or 0),m15_live,float(mark),watch,flow,time.time())):
        side=int(watch["side"])
        if local_swing_open(symbol,side,analysis,"M15",m15_live):
         _local_watch_clear(symbol,"new_same_side_h1_pivot")
         action="REENTER_NEW_H1_PIVOT";watch=None
       elif not analysis.get("entry_blocked") and caterpillar_reentry_ready(int(watch.get("side") or 0),m15_live,float(mark),watch,flow,time.time()):
        if local_swing_open(symbol,int(watch["side"]),analysis,"REENTRY",m15_live,watch):action="M15_RECOVERY_REENTRY"
      if (not watch and not action and analysis.get("ready") and int(analysis.get("entry_side") or 0) in (-1,1)
          and flow.get("trade_data_fresh") and flow_imb is not None and int(analysis["entry_side"])*float(flow_imb)>=.12
          and local_m15_reentry_ready(int(analysis["entry_side"]),m15_live,flow_imb)):
       if local_swing_open(symbol,int(analysis["entry_side"]),analysis,"M15",m15_live):action="M15_ENTRY"

     with LOCK:
      live=copy.deepcopy(S.get("local_swing_positions",{}).get(symbol))
      live_watch=copy.deepcopy(S.get("local_swing_watch",{}).get(symbol))
     details[symbol]={"ok":True,"symbol":symbol,"mark":float(mark),"max_leverage":market_max_leverage(symbol),
      "position_open":bool(live),"side":int(live.get("side")) if live else None,"watching_for_reentry":bool(live_watch),
      "watch_side":int(live_watch.get("side")) if live_watch else None,
      "watch_expires_epoch":live_watch.get("expires_epoch") if live_watch else None,
      "watch_reentries":int(live_watch.get("reentries",0)) if live_watch else None,
      "caterpillar_phase":(live_watch.get("context") or {}).get("phase") if live_watch else ("IN_POSITION" if live else "WAIT_ENTRY"),
      "h1_local":{"ready":bool(analysis.get("ready")),"pivot_type":analysis.get("pivot_type"),
       "pivot_price":analysis.get("pivot_price"),"entry_side":analysis.get("entry_side"),
       "signal_candle_time":candle,"long_weak_score":analysis.get("long_weak_score"),
       "short_weak_score":analysis.get("short_weak_score"),"reason":analysis.get("reason")},
      "m15_live":{"ready":bool(m15_live.get("ready")),"partial":m15_live.get("partial"),
       "adverse_score":m15_live.get("adverse_score"),"recovery_score":m15_live.get("recovery_score"),
       "strong_adverse_pressure":m15_live.get("strong_adverse_pressure"),
       "recovery_confirmed":m15_live.get("recovery_confirmed"),"flow_imbalance":flow_imb},
      "h1_context":h1_context,"last_action":action,"error":None}
    with LOCK:
     open_positions=copy.deepcopy(S.get("local_swing_positions",{}));watches=copy.deepcopy(S.get("local_swing_watch",{}))
     S["hype_swing_position"]=open_positions.get(HYPE_SWING_SYMBOL)
     S["sources"]["HypeH1LocalSwing"]={"ok":all(x.get("ok") for x in details.values()),"last_check":now(),
       "mode":"paper_h1_m15_caterpillar","policy":CATERPILLAR_POLICY,
       "symbols":list(LOCAL_SWING_SYMBOLS),"signal_interval":HYPE_SWING_INTERVAL,
       "h1_context_interval":LOCAL_SWING_H1_CONTEXT_INTERVAL,"protection_interval":LOCAL_SWING_M15_INTERVAL,
       "paper_only":True,"equity":S.get("hype_swing_equity"),"trades":S.get("hype_swing_trades",0),
       "open_positions":list(open_positions.keys()),"watching_for_reentry":list(watches.keys()),
       "position_count":len(open_positions),"watch_count":len(watches),"reference_margin_fraction":HYPE_SWING_MARGIN_FRACTION,
       "reference_leverage":HYPE_SWING_LEVERAGE,"exchange_max_leverage":{sym:market_max_leverage(sym) for sym in LOCAL_SWING_SYMBOLS},
       "sizing":"preserve_reference_notional_then_cap_to_free_margin","compound_from_shared_equity":True,"h1_blocks_entries":True,
       "profit_lock":{"enabled":True,"mode":"fixed_breakeven_not_peak_trailing","arm_move_pct":.4,
        "buffer_move_pct":.16},
       "m15_profit_protection":True,"m15_reentry":True,"reentry_watch_seconds":LOCAL_REENTRY_WATCH_SECONDS or None,
       "max_reentries_per_swing":LOCAL_REENTRY_MAX_PER_SWING or None,"parallel_scan_workers":4,"details":details,"rest_transport":HL_REST_BUDGET.status(),
       "candle_transport":"websocket_with_incremental_rest_recovery",
       "error":None if all(x.get("ok") for x in details.values()) else "partial_symbol_scan_failure"}
    if time.time()-last_observation>=30:
     try:save_scanner_observation(CATERPILLAR_POLICY,{"details":details,"policy":CATERPILLAR_POLICY,"observed_at":now()})
     except Exception as exc:
      with LOCK:S["sources"]["HypeH1LocalSwing"]["history_recording_error"]=str(exc)[:120]
     last_observation=time.time()
   except LeaseLost as exc:
    with LOCK:S["sources"]["HypeH1LocalSwing"]={"ok":False,"last_check":now(),"mode":"standby","symbols":list(LOCAL_SWING_SYMBOLS),"error":str(exc)[:160]}
   except Exception as exc:
    with LOCK:S["sources"]["HypeH1LocalSwing"]={"ok":False,"last_check":now(),"mode":"paper_h1_direction_m15_protection_reentry","symbols":list(LOCAL_SWING_SYMBOLS),"error":type(exc).__name__+":"+str(exc)[:160]}
    try:journal("local_swing_error",None,{"error":type(exc).__name__+":"+str(exc)[:180]})
    except Exception:pass
   SHUTDOWN.wait(10)
 finally:
  pool.shutdown(wait=False,cancel_futures=True)

@account_mutation
def emergency_profit_take(prices):
 stamp=time.time()
 with LOCK:
  if not S.get("engine_active") or S.get("mode")!="PAPER_ONLY":return []
  books=[("pump_dump",copy.deepcopy(S.get("pump_positions",{}))),
         ("local_12token_h1_m15",copy.deepcopy(S.get("local_v12_positions",{}))),
         ("local_legacy_exit_only",copy.deepcopy(S.get("local_swing_positions",{})))]
  history={s:list(S.get("_timeline",{}).get(s,[])) for s in ("BTC","ETH","SOL")}
  pending=copy.deepcopy(S.get("_emergency_pending",[]))
 shock=emergency_reversal(prices,history,stamp)
 if not pending and stamp>=float(S.get("_emergency_until",0) or 0):
  pending=profit_targets(books,prices,shock,FEE)
  if pending:
   with LOCK:
    S["_emergency_until"]=stamp+COOLDOWN_SECONDS;S["_emergency_pending"]=pending
    S["emergency_profit_guard"]={"enabled":True,"triggered_at":now(),"shock":shock,
       "targets":pending,"cooldown_until_epoch":stamp+COOLDOWN_SECONDS,"status":"CLOSING"}
   journal("portfolio_emergency_triggered",None,{"shock":shock,"targets":pending,"cooldown_seconds":COOLDOWN_SECONDS})
 if not pending:
  with LOCK:
   state=S.setdefault("emergency_profit_guard",{"enabled":True,"cooldown_seconds":COOLDOWN_SECONDS})
   state["status"]="MONITORING" if stamp<float(S.get("_emergency_until",0) or 0) else "ARMED"
  return []
 callbacks={"pump_dump":pump_close,"local_12token_h1_m15":local_experiment_close,"local_legacy_exit_only":local_swing_close}
 live_books=dict(books);closed=[];remaining=[]
 for target in pending:
  strategy=target["strategy"];sym=target["symbol"];pos=live_books.get(strategy,{}).get(sym)
  if not pos or pos.get("opened")!=target["opened"]:continue
  price=prices.get(sym)
  if not price:remaining.append(target);continue
  result=callbacks[strategy](sym,price,"portfolio_emergency_profit_take")
  if result:closed.append({**target,"exit":price,"pnl":result.get("pnl")})
  else:remaining.append(target)
 with LOCK:
  S["_emergency_pending"]=remaining
  S["emergency_profit_guard"].update(status="CLOSING" if remaining else "COOLDOWN",last_closed=closed,pending=len(remaining))
 if closed:journal("portfolio_emergency_profit_taken",None,{"closed":closed,"remaining":remaining})
 return closed

def confirmed_liquidation_stream():
 def report(state):
  with LOCK:S["sources"]["ConfirmedLiquidationStream"]={"last_check":now(),**state}
 run_liquidation_stream(LIQUIDATION_TAPE,SHUTDOWN,report)

def market():
 while not SHUTDOWN.is_set():
  S["_market_heartbeat"]=time.time()
  try:
   with LOCK:
    active=bool(S.get("engine_active"))
    metadata_ready=bool(S.get("_day_volumes")) and bool(S.get("_max_leverage"))
    cached=dict(S.get("_prices",{}))
    cached_age=time.time()-float(S.get("_last_poll_epoch",0) or 0) if S.get("_last_poll_epoch") else 1e9
   # Standby Render instances must never touch exchange REST. After lease
   # takeover, metadata owns the first REST request.
   if not active:
    SHUTDOWN.wait(.5)
    continue
   # Before metadata is ready, the market worker must not hammer allMids.
   if not metadata_ready:
    with LOCK:
     S["last_market_error"]=None
     if str(S.get("last_error") or "").startswith("market: hyperliquid_rest_deferred"):
      S["last_error"]=None
    SHUTDOWN.wait(.5)
    continue
   # Once websocket has delivered fresh allMids, use it and avoid REST entirely.
   valid=cached if cached and cached_age<=8.0 else refresh_market_prices(force=False,max_age=8.0)
   # Network and SQL work never owns the global state lock. Sources, health
   # and the lease heartbeat remain responsive during a slow checkpoint.
   if active and not SHUTDOWN.is_set():
    # Process Pump & Dump hard stops before any expensive news/db work.
    # A failure in the news strategy must not prevent Pump risk evaluation.
    try:
     pump_mark_positions(valid)
    except LeaseLost:
     raise
    except Exception as pump_exc:
     S["errors"]+=1
     S["last_error"]="pump_risk: "+str(pump_exc)[:180]
    emergency_profit_take(valid)
    with LOCK:
     positions=copy.deepcopy(S["positions"]);news_timelines={k:list(v) for k,v in S.get("_timeline",{}).items()}
    reconcile_open_paper_sizing(valid);protect_stamp=time.time()
    for sym,old_pos in positions.items():
     if sym not in valid:continue
     px=valid[sym]
     protected,protect_reason,protect_fill,protect_state=_profit_protection_eval(old_pos,sym,float(px),protect_stamp,news_timelines.get(sym,[]))
     _profit_protection_arm_journal("news",sym,bool(old_pos.get("profit_lock_armed")),protected)
     if protect_reason:
      with LOCK:
       if S["positions"].get(sym,{}).get("opened")==old_pos.get("opened"):S["positions"][sym]=protected
      close_news_position(sym,protected,protect_fill,protect_reason);continue
     pos,reason=evaluate_exit(protected,px,now())
     with ACCOUNT_LOCK:
      with LOCK:
       if S["positions"].get(sym,{}).get("opened")!=pos["opened"]:continue
       S["positions"][sym]=pos
      if reason:close_news_position(sym,pos,px,reason)
      elif not STORE.save(sym,pos):
       with LOCK:
        if S["positions"].get(sym,{}).get("opened")==pos["opened"]:S["positions"].pop(sym,None)
    hype_swing_mark_positions(valid)
    with LOCK:S["last_checkpoint"]=now()
  except LeaseLost as e:
   S["engine_active"]=False;S["engine_error"]=str(e)
  except RestDeferred as e:
   # Shared REST backoff is expected when websocket prices are already fresh.
   # It must not poison global health or increment the error counter.
   with LOCK:
    cached_ok=bool(S.get("_prices")) and float(S.get("_last_poll_epoch",0) or 0)>0 and time.time()-float(S.get("_last_poll_epoch",0) or 0)<=12
    if cached_ok:
     S["last_market_error"]=None
     if str(S.get("last_error") or "").startswith("market: hyperliquid_rest_deferred"):
      S["last_error"]=None
    else:
     S["last_market_error"]=str(e)[:180]
  except Exception as e:
   S["errors"]+=1;S["last_market_error"]=str(e)[:180];S["last_error"]="market: "+str(e)[:180]
  S["_market_heartbeat"]=time.time()
  SHUTDOWN.wait(2)

def impulse_scan():
 last_signal={};streaks={};candidate_queue={};last_observation=0
 micro_rejections={};micro_rejected_samples={}
 pool=concurrent.futures.ThreadPoolExecutor(max_workers=MICRO_ANALYSIS_THREADS,thread_name_prefix="pump-micro")
 def enrich(candidate):
  candidate=dict(candidate);sym=candidate["symbol"];side=int(candidate["side"])
  def rejected(reason):
   candidate["micro_reject_reason"]=reason
   with LOCK:
    micro_rejections[reason]=micro_rejections.get(reason,0)+1
    micro_rejected_samples[(sym,side)]=copy.deepcopy(candidate)
   return None
  try:
   book=_whale_liq_book(sym)
   if not book or not book.get("bid_depth_complete") or not book.get("ask_depth_complete"):return rejected("incomplete_orderbook")
   if book.get("epoch") is None or not 0<=time.time()-book["epoch"]<=5:return rejected("stale_orderbook")
   bd=book["bid_depth_usd"];ad=book["ask_depth_usd"];imb=book["imbalance"];spread=book["spread_bps"]
   candidate["orderbook_imbalance"]=round(imb,4);candidate["spread_bps"]=round(spread,2)
   candidate["book_depth_usd"]=round(bd+ad,2)
  except Exception as exc:
   candidate["book_error"]=str(exc)[:100];return rejected("orderbook_error")
  observed=MARKET_OBS.context(sym,time.time())
  if not observed.get("trade_data_fresh"):return rejected("missing_observed_trade_flow")
  base_score=float(candidate.get("score",0) or 0)
  candidate["cvd_1m"]=observed.get("cvd_1m");candidate["flow_imbalance"]=observed.get("flow_imbalance")
  candidate["trade_count_60s"]=observed.get("trade_count_60s")
  candidate["observed_notional_60s"]=observed.get("observed_notional_60s")
  candidate["volume_baseline_samples"]=observed.get("volume_baseline_samples")
  candidate["flow_coverage"]=observed.get("trade_coverage_seconds");candidate["flow_source"]="hyperliquid_ws_trades"
  imb=float(candidate.get("orderbook_imbalance",0) or 0);flow_imb=float(candidate.get("flow_imbalance",0) or 0)
  spread=float(candidate.get("spread_bps",9999) or 9999);oi=abs(float(candidate.get("oi_delta_60s",0) or 0))
  vol_z=candidate.get("volume_rate_z")
  continuation=candidate.get("candidate_kind")=="market_continuation"
  # Aggressive sell flow can consume a bid wall while the static book still
  # looks bid-heavy. A continuation allows mild opposing depth only with
  # strong *executed* flow; a wide or strongly opposing book still rejects it.
  book_ok=spread<=15 and (side*imb>=0.15 or (continuation and side*imb>=-.10 and side*flow_imb>=.25))
  flow_ok=side*flow_imb>=(.12 if continuation else .08)
  oi_ok=oi>=0.003
  abnormal_ok=(vol_z is not None and float(vol_z)>=3.0) or float(candidate.get("volume_burst_ratio",0) or 0)>=3.0
  participation_ok=(float(candidate.get("volume_burst_ratio",0) or 0)>=1.2 or
                    (vol_z is not None and float(vol_z)>=1.0) or oi>=.0025) if continuation else abnormal_ok
  confirmations=sum([book_ok,flow_ok,oi_ok,participation_ok])
  candidate["book_ok"]=book_ok;candidate["flow_ok"]=flow_ok;candidate["oi_ok"]=oi_ok;candidate["abnormal_volume_ok"]=abnormal_ok
  candidate["micro_confirmations"]=confirmations
  if book_ok:candidate["score"]=min(100,float(candidate["score"])+8)
  if flow_ok:candidate["score"]=min(100,float(candidate["score"])+8)
  if oi_ok:candidate["score"]=min(100,float(candidate["score"])+5)
  candidate["participation_ok"]=participation_ok
  if participation_ok:candidate["score"]=min(100,float(candidate["score"])+5)
  candidate["base_signal_score"]=base_score
  candidate["rank_score"]=round(base_score+8*book_ok+8*flow_ok+5*oi_ok+5*participation_ok,2)
  candidate["estimated_round_trip_cost_bps"]=round(2*FEE*10000+spread+4,3)
  if confirmations>=3 and book_ok and flow_ok and participation_ok and spread<=15:return candidate
  return rejected("book_pressure" if not book_ok else "flow_pressure" if not flow_ok else "participation" if not participation_ok else "insufficient_micro_confirmations")
 def portfolio_counts():
  with LOCK:
   news=len(S.get("positions",{}));pump=len(S.get("pump_positions",{}));whale=len(S.get("whale_positions",{}))
   sides=[int(p.get("side",0)) for book in (S.get("positions",{}),S.get("pump_positions",{}),S.get("whale_positions",{})) for p in book.values()]
  return news+pump+whale,pump,sides
 try:
  while not SHUTDOWN.is_set():
   started=time.monotonic()
   try:
    with LOCK:
     active=bool(S.get("engine_active"))
     metadata_ready=bool(S.get("_day_volumes")) and bool(S.get("_max_leverage"))
    if not active:
     SHUTDOWN.wait(0.5);continue
    if not metadata_ready:
     with LOCK:S["sources"]["PumpDumpScanner"]={"ok":True,"ready":False,"warmup":True,"last_check":now(),
       "mode":"waiting_for_market_metadata","error":None}
     SHUTDOWN.wait(0.5);continue
    prices=refresh_market_prices(max_age=8.0)
    with LOCK:
     history={k:list(v) for k,v in S.get("_timeline",{}).items()}
     volumes=dict(S.get("_day_volumes",{}));contexts=copy.deepcopy(S.get("_pump_ctx",{}))
    stamp=time.time()
    regime=market_regime(prices,history,volumes,stamp)
    for sym in contexts:contexts[sym].update(MARKET_OBS.context(sym,stamp))
    found=momentum_candidates(prices,history,volumes,stamp,minimum_day_volume=0.0,contexts=contexts)
    raw_impulses=len(found)
    continuation=continuation_candidates(prices,history,volumes,stamp,contexts,regime)
    combined={(x["symbol"],int(x["side"])):x for x in continuation}
    combined.update({(x["symbol"],int(x["side"])):x for x in found})
    blocked_counter=sum(int(x["side"])!=int(regime["side"]) for x in combined.values()) if regime.get("side") else 0
    found=[x for x in combined.values() if regime_candidate_guard(x,regime) is None]
    found.sort(key=lambda x:x["score"],reverse=True)
    for candidate in found:candidate["observed_at_epoch"]=stamp
    micro_rejections.clear();micro_rejected_samples.clear()
    futures=[pool.submit(enrich,x) for x in found[:30]]
    enriched=[]
    for future in concurrent.futures.as_completed(futures):
     x=future.result()
     if x:enriched.append(x)
    now_keys=set();primary=[];secondary=[]
    for x in enriched:
     key=(x["symbol"],int(x["side"]));now_keys.add(key);streaks[key]=streaks.get(key,0)+1
     x["confirmation_streak"]=streaks[key]
     score=float(x["score"])
     if score>=PUMP_PRIMARY_SCORE and x["confirmation_streak"]>=3:
      x["allocation_tier"]="PRIMARY";x["allocation_margin_fraction"]=TRADE_MARGIN_FRACTION;primary.append(x)
     elif score>=PUMP_SECONDARY_SCORE and x["confirmation_streak"]>=2:
      x["allocation_tier"]="SECONDARY";x["allocation_margin_fraction"]=PUMP_SECONDARY_MARGIN_FRACTION;secondary.append(x)
     if score>=PUMP_SECONDARY_SCORE and x["confirmation_streak"]>=2:
      candidate_queue[key]={"candidate":copy.deepcopy(x),"expires":stamp+PUMP_QUEUE_TTL_SECONDS}
    for key in list(streaks):
     if key not in now_keys:streaks.pop(key,None)
    for key,row in list(candidate_queue.items()):
     # Queue capacity is not permission to reuse an old signal. Every entry
     # must still pass this cycle's momentum, breadth, book and flow checks.
     if row["expires"]<stamp or key not in now_keys:candidate_queue.pop(key,None)
    primary.sort(key=lambda x:x.get("rank_score",x["score"]),reverse=True);secondary.sort(key=lambda x:x.get("rank_score",x["score"]),reverse=True)
    queued=[row["candidate"] for row in candidate_queue.values()]
    queued.sort(key=lambda x:(0 if x.get("allocation_tier")=="PRIMARY" else 1,-float(x.get("rank_score",x.get("score",0)))))
    opened_this_scan=[];qualified=primary+secondary
    pump_bucket=int(stamp//15)
    qualified_keys={(x["symbol"],int(x["side"])) for x in qualified}
    micro_keys={(x["symbol"],int(x["side"])) for x in enriched}
    for observed in found[:100]:
     sym=observed.get("symbol");side=int(observed.get("side") or 0)
     if not sym or side not in (-1,1):continue
     key=(sym,side)
     rejected_sample=micro_rejected_samples.get(key)
     if key in qualified_keys:obs_action="QUALIFIED";obs_reason="passed_current_filters";obs_features=observed
     elif key in micro_keys:obs_action="REJECTED";obs_reason="score_or_confirmation_streak";obs_features=observed
     else:
      obs_action="REJECTED";obs_reason=(rejected_sample or {}).get("micro_reject_reason") or "microstructure_filter"
      obs_features=rejected_sample or observed
     obs_id=hashlib.sha256(("PUMP_OBS:"+sym+":"+str(side)+":"+str(pump_bucket)).encode()).hexdigest()
     log_learning_decision(obs_id,"pump_dump",sym,side,obs_action,obs_reason,prices.get(sym),
       obs_features.get("score"),TRADE_LEVERAGE,obs_features)
    for candidate in queued:
     total_open,pump_open_count,open_sides=portfolio_counts()
     sym=candidate["symbol"];side=int(candidate["side"]);tier=candidate.get("allocation_tier","SECONDARY")
     learn_id=hashlib.sha256(("PUMP_ENTRY:"+sym+":"+str(side)+":"+str(pump_bucket)).encode()).hexdigest()
     candidate["learning_decision_id"]=learn_id
     if total_open>=MAX_OPEN_POSITIONS or pump_open_count>=PUMP_MAX_POSITIONS:
      log_learning_decision(learn_id,"pump_dump",sym,side,"SKIPPED","portfolio_position_cap" if total_open>=MAX_OPEN_POSITIONS else "pump_position_cap",
       prices.get(sym),candidate.get("score"),TRADE_LEVERAGE,candidate);continue
     if _symbol_open_anywhere(sym):
      log_learning_decision(learn_id,"pump_dump",sym,side,"SKIPPED","symbol_already_open_shared_account",
       prices.get(sym),candidate.get("score"),TRADE_LEVERAGE,candidate);continue
     if tier=="SECONDARY":
      if sum(1 for x in open_sides if x==side)>=PUMP_SECONDARY_SAME_SIDE_CAP:
       log_learning_decision(learn_id,"pump_dump",sym,side,"SKIPPED","secondary_same_side_cap",
        prices.get(sym),candidate.get("score"),TRADE_LEVERAGE,candidate);continue
      ranked_fraction=liquidity_margin_fraction(sym,candidate,PUMP_SECONDARY_MARGIN_FRACTION,regime)
      margin_fraction=ranked_fraction
     else:
      margin_fraction=liquidity_margin_fraction(sym,candidate,TRADE_MARGIN_FRACTION,regime)
     opened=bool(prices.get(sym)) and pump_open(sym,side,prices[sym],candidate["score"],candidate,margin_fraction)
     action="OPENED_"+tier if opened else "QUALIFIED_"+tier
     if opened:
      opened_this_scan.append(sym);candidate_queue.pop((sym,side),None)
     learn_reason="entry_opened" if opened else "qualified_but_entry_vetoed_or_capacity"
     log_learning_decision(learn_id,"pump_dump",sym,side,action,learn_reason,prices.get(sym),
       candidate.get("score"),TRADE_LEVERAGE,candidate)
     bucket=pump_bucket;ident=hashlib.sha256(("PUMP4:"+sym+":"+str(side)+":"+str(bucket)+":"+action).encode()).hexdigest()
     if stamp-last_signal.get((sym,side,action),0)<15:continue
     last_signal[(sym,side,action)]=stamp
     with pg() as db:
      db.execute("""insert into pump_signal_journal(id,ts,symbol,side,score,action,features)
        values(%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict(id) do nothing""",
        (ident,now(),sym,side,float(candidate["score"]),action,json.dumps(candidate,default=str)))
    if found or qualified or stamp-last_observation>=60:
     try:
      save_scanner_observation("pump_dump",{"policy":"momentum_breadth_continuation_v5","raw_candidates":found[:30],"micro_confirmed":enriched[:30],"primary":primary[:20],"secondary":secondary[:20],"queue":queued[:20],"opened":opened_this_scan,"market_regime":regime,"micro_rejections":dict(micro_rejections),"micro_rejected_samples":list(micro_rejected_samples.values())[:30],"counter_market_rejected":blocked_counter,"scan_epoch":stamp})
      last_observation=stamp
     except Exception as obs_exc:
      with LOCK:S["last_error"]="pump_observation: "+str(obs_exc)[:160]
    total_open,pump_open_count,_=portfolio_counts()
    with LOCK:
     S["sources"]["PumpDumpScanner"]={"ok":bool(prices and volumes),"last_check":now(),"markets":len(prices),
       "liquid_markets":sum(v>=5_000_000 for v in volumes.values()),"raw_candidates":len(found),"micro_confirmed":len(enriched),
       "qualified_candidates":len(qualified),"primary_candidates":len(primary),"secondary_candidates":len(secondary),
       "candidate_queue":len(candidate_queue),"top_candidates":qualified[:5],"mode":"pump_dump_H1_H4_direction_v6",
       "raw_impulses":raw_impulses,"continuation_candidates":len(continuation),"counter_market_rejected":blocked_counter,
       "micro_rejections":dict(micro_rejections),"queue_revalidation":"current_scan_required",
       "scan_seconds":PUMP_SCAN_SECONDS,"actual_scan_seconds":round(time.monotonic()-started,3),"min_day_volume":0,
       "market_scope":"all_hyperliquid_listed_perps","primary_score_min":PUMP_PRIMARY_SCORE,
       "secondary_score_min":PUMP_SECONDARY_SCORE,"primary_confirmation_scans":3,"secondary_confirmation_scans":2,
       "target_open_positions":TARGET_OPEN_POSITIONS,"max_open_positions":MAX_OPEN_POSITIONS,
       "pump_max_positions":PUMP_MAX_POSITIONS,"whale_margin_fraction":WHALE_MARGIN_FRACTION,"whale_max_active_positions":WHALE_MAX_ACTIVE_POSITIONS,"secondary_margin_fraction":PUMP_SECONDARY_MARGIN_FRACTION,
       "queue_ttl_seconds":PUMP_QUEUE_TTL_SECONDS,"open_positions_total":total_open,
       "signal_ready_markets":sum(bool(c.get("trade_data_fresh")) for c in contexts.values()),"flow_source":"hyperliquid_ws_trades",
       "analysis_threads":MICRO_ANALYSIS_THREADS,"paper_positions":pump_open_count,
       "shared_account_equity":round(S["equity"],4),"market_regime":regime,
       "error":None if prices and volumes else "missing_market_prices_or_metadata"}
   except Exception as exc:
    streaks={};candidate_queue={}
    with LOCK:S["sources"]["PumpDumpScanner"]={"ok":False,"last_check":now(),"mode":"portfolio_allocator_paper_v4","analysis_threads":MICRO_ANALYSIS_THREADS,"error":str(exc)[:180]}
   SHUTDOWN.wait(max(.05,PUMP_SCAN_SECONDS-(time.monotonic()-started)))
 finally:pool.shutdown(wait=False,cancel_futures=True)

def market_regime_history():
 # Read-only health view. MarketHistoryBootstrap is the sole REST owner for
 # historical seed candles; this worker never competes for exchange budget.
 while not SHUTDOWN.is_set():
  with LOCK:
   active=bool(S.get("engine_active"))
   snapshot={sym:list(S.get("_regime_candles",{}).get(sym,[])) for sym in REGIME_SEED_SYMBOLS}
   bootstrap=copy.deepcopy(S.get("sources",{}).get("MarketHistoryBootstrap",{}))
  if not active:
   SHUTDOWN.wait(2);continue
  stamp=time.time()
  def usable(rows):
   return bool(rows and stamp-rows[-1][0]<90 and any(0<=stamp-14400-t<=65 for t,_ in rows))
  ready=[sym for sym,rows in snapshot.items() if usable(rows)]
  ok=len(set(ready))>=5
  with LOCK:S["sources"]["MarketBreadthHistory"]={"ok":True,"ready":ok,"warmup":not ok,"last_check":now(),
    "loaded_markets":len(set(ready)),"requested_markets":len(REGIME_SEED_SYMBOLS),
    "mode":"completed_1m_H1_H4_context","refresh_seconds":15,
    "transport":"read_only_from_single_history_bootstrap_plus_live_ws",
    "seed_symbols":list(REGIME_SEED_SYMBOLS),"bootstrap":bootstrap,
    "error":None if ok else "waiting_for_single_history_bootstrap"}
  SHUTDOWN.wait(15)

def market_history_bootstrap():
 # One paced history owner. Local's fixed PAPER sizing and known symbols do
 # not require a successful optional universe/metadata HTTP request.
 completed=set()
 while not SHUTDOWN.is_set():
  with LOCK:
   active=bool(S.get("engine_active"))
   activated=float(S.get("_engine_activated_epoch",0) or 0)
   metadata_epoch=float(S.get("_metadata_ready_epoch",0) or 0)
  if not active:
   SHUTDOWN.wait(.5);continue
  checkpoint_local_candles()
  ready_after=(metadata_epoch+5.0) if metadata_epoch else (activated+70.0)
  quiet_remaining=max(0.0,ready_after-time.time())
  if quiet_remaining>0:
   with LOCK:S["sources"]["MarketHistoryBootstrap"]={"ok":True,"warmup":True,"degraded":False,
     "last_check":now(),"mode":"post_takeover_ip_quiet_window","quiet_remaining_seconds":round(quiet_remaining,1),
     "regime_ready":sum(1 for x in completed if x[0]=="regime"),
     "local_ready":sum(1 for x in LOCAL_EXPERIMENT_SYMBOLS if ("local",x,"1h") in completed and ("local",x,"15m") in completed),"error":None}
   SHUTDOWN.wait(min(2.0,quiet_remaining));continue
  try:
   stamp=time.time()
   # Trading-critical priority: restore Strategy 1 H1/M15 first. A deploy must
   # never spend the shared REST budget on breadth while Caterpillar is blind.
   priority_local=list(LOCAL_EXPERIMENT_SYMBOLS)+[x for x in ALL_LOCAL_CANDLE_SYMBOLS if x not in LOCAL_EXPERIMENT_SYMBOLS]
   # Native intervals avoid losing older H1 anchors.
   for sym in priority_local:
    for interval,hours in (("1h",120),("15m",12)):
     if SHUTDOWN.is_set():return
     key=("local",sym,interval)
     with _LOCAL_CANDLE_CACHE_LOCK:cached=_LOCAL_CANDLE_CACHE.get((sym,interval,hours))
     if _local_cached_interval_fresh(cached,interval):
      completed.add(key);continue
     stamp=time.time()
     rows=json.loads(get(API,{"type":"candleSnapshot","req":{"coin":sym,"interval":interval,
       "startTime":int((stamp-hours*3600)*1000),"endTime":int(stamp*1000)}}))
     if not isinstance(rows,list) or not rows:raise RuntimeError("empty_local_bootstrap:"+sym+":"+interval)
     accept_local_candles(rows,history=True)
     checkpoint_local_candles()
     completed.add(key)
     with LOCK:S["sources"]["MarketHistoryBootstrap"]={"ok":True,"warmup":True,"last_check":now(),
       "mode":"paced_native_local_history_before_breadth",
       "regime_ready":sum(1 for x in completed if x[0]=="regime"),
       "local_ready":sum(1 for x in LOCAL_EXPERIMENT_SYMBOLS if ("local",x,"1h") in completed and ("local",x,"15m") in completed),
       "error":None}
     SHUTDOWN.wait(3.0)
   # Breadth/regime history is secondary. Restore it only after every Local
   # symbol has its native H1/M15 cache, so Strategy 1 survives rolling deploys.
   for sym in REGIME_SEED_SYMBOLS:
    key=("regime",sym)
    if key in completed:continue
    stamp=time.time()
    rows=json.loads(get(API,{"type":"candleSnapshot","req":{"coin":sym,"interval":"1m",
      "startTime":int((stamp-6*3600)*1000),"endTime":int(stamp*1000)}}))
    if isinstance(rows,list) and rows:
     accept_regime_candles(rows);completed.add(key)
    SHUTDOWN.wait(2.0)
   with LOCK:S["sources"]["MarketHistoryBootstrap"]={"ok":True,"warmup":False,"last_check":now(),
     "mode":"paced_rest_after_lease","regime_ready":sum(1 for x in completed if x[0]=="regime"),
     "local_ready":sum(1 for x in LOCAL_EXPERIMENT_SYMBOLS if ("local",x,"1h") in completed and ("local",x,"15m") in completed),"error":None}
   SHUTDOWN.wait(30)
  except RestDeferred:
   with LOCK:S["sources"]["MarketHistoryBootstrap"]={"ok":True,"warmup":True,"degraded":False,"last_check":now(),
     "mode":"rest_budget_wait","regime_ready":sum(1 for x in completed if x[0]=="regime"),
     "local_ready":sum(1 for x in LOCAL_EXPERIMENT_SYMBOLS if ("local",x,"1h") in completed and ("local",x,"15m") in completed),"error":None}
   SHUTDOWN.wait(3)
  except urllib.error.HTTPError as exc:
   if exc.code==429:
    with LOCK:S["sources"]["MarketHistoryBootstrap"]={"ok":True,"warmup":True,"degraded":False,"last_check":now(),
      "mode":"exchange_429_backoff","regime_ready":sum(1 for x in completed if x[0]=="regime"),
      "local_ready":sum(1 for x in LOCAL_EXPERIMENT_SYMBOLS if ("local",x,"1h") in completed and ("local",x,"15m") in completed),"error":None}
    SHUTDOWN.wait(max(10.0,float(HL_REST_BUDGET.status().get("cooldown_seconds",0) or 0)))
   else:
    with LOCK:S["sources"]["MarketHistoryBootstrap"]={"ok":False,"last_check":now(),"error":str(exc)[:140]}
    SHUTDOWN.wait(5)
  except Exception as exc:
   with LOCK:S["sources"]["MarketHistoryBootstrap"]={"ok":False,"last_check":now(),
     "error":type(exc).__name__+":"+str(exc)[:140]}
   SHUTDOWN.wait(5)


def market_trade_stream():
 # Websocket requires the engine lease, never REST metadata. Known Local and
 # held symbols are immediately available; expand to the universe when loaded.
 while not SHUTDOWN.is_set():
  with LOCK:active=bool(S.get("engine_active"))
  if active:break
  SHUTDOWN.wait(.25)
 def symbols():
  # Pump/dump coverage is whole-market: subscribe to every currently listed
  # Hyperliquid perp with metadata, not only the high-volume subset. Deep
  # order-book work remains candidate-only, so broad trade coverage does not
  # multiply expensive REST book requests.
  with LOCK:
   volumes=dict(S.get("_day_volumes",{}));prices=set(S.get("_prices",{}));held=set(S["positions"])|set(S["pump_positions"])|set(S["whale_positions"])
  listed=set(volumes)&prices if prices else set(volumes)
  return listed|LIQ_WHALE_SYMBOLS|held|set(ALL_LOCAL_CANDLE_SYMBOLS)
 def report(status):
  with LOCK:S["sources"]["MarketTradeStream"]={"last_check":now(),**status}
 run_trade_stream(MARKET_OBS,SHUTDOWN,symbols,report,os.getenv("HYPERLIQUID_WS_API","wss://api.hyperliquid.xyz/ws"),on_mids=accept_market_prices,on_candles=accept_local_candles,candle_symbols=ALL_LOCAL_CANDLE_SYMBOLS,on_candle_history=accept_local_history,regime_symbols=REGIME_SEED_SYMBOLS,on_regime_candles=accept_regime_candles)

def market_metadata():
 while not SHUTDOWN.is_set():
  # Do not duplicate REST traffic from a standby Render instance during
  # blue/green rollout. Bootstrap metadata only after this process owns lease.
  with LOCK:
   active=bool(S.get("engine_active"))
   activated=float(S.get("_engine_activated_epoch",0) or 0)
  if not active:
   with LOCK:S["sources"]["MarketMetadata"]={"ok":True,"ready":False,"standby":True,"last_check":now(),"mode":"waiting_for_engine_lease","error":None}
   SHUTDOWN.wait(.5)
   continue
  quiet_remaining=max(0.0,65.0-(time.time()-activated)) if activated else 65.0
  if quiet_remaining>0:
   with LOCK:S["sources"]["MarketMetadata"]={"ok":True,"ready":False,"warmup":True,"last_check":now(),
     "mode":"post_takeover_ip_quiet_window","quiet_remaining_seconds":round(quiet_remaining,1),"error":None}
   SHUTDOWN.wait(min(2.0,quiet_remaining))
   continue
  try:
   raw=json.loads(get(API,{"type":"metaAndAssetCtxs"}))
   universe=raw[0].get("universe",[]);ctxs=raw[1]
   volumes={};pump_ctx={};max_leverage={};stamp=time.time()
   for asset,ctx in zip(universe,ctxs):
    try:
     name=asset["name"];v=float(ctx.get("dayNtlVlm",0) or 0);oi=float(ctx.get("openInterest",0) or 0)
     lev=float(asset.get("maxLeverage",0) or 0)
     if math.isfinite(lev) and lev>=1:max_leverage[name]=lev
     funding=float(ctx.get("funding",0) or 0);premium=float(ctx.get("premium",0) or 0)
     mark=float(ctx.get("markPx",0) or 0);oracle=float(ctx.get("oraclePx",0) or 0)
     if math.isfinite(v) and v>=0:volumes[name]=v
     MARKET_OBS.add_open_interest(name,stamp,oi)
     pump_ctx[name]={"epoch":stamp,"open_interest":oi,"day_volume":v,"funding":funding,"premium":premium,
       "mark_price":mark,"oracle_price":oracle,**MARKET_OBS.context(name,stamp)}
    except (TypeError,ValueError,KeyError,ZeroDivisionError):continue
   with LOCK:
    S["_day_volumes"]=volumes;S["_pump_ctx"]=pump_ctx;S["_max_leverage"]=max_leverage;S["_metadata_ready_epoch"]=time.time()
    S["sources"]["MarketMetadata"]={"ok":True,"last_check":now(),"markets":len(volumes),"max_leverage_markets":len(max_leverage),
      "local_max_leverage":{sym:max_leverage.get(sym,VALIDATED_MAX_LEVERAGE.get(sym)) for sym in ALL_LOCAL_CANDLE_SYMBOLS}}
  except Exception as e:
   with LOCK:
    cached=bool(S.get("_day_volumes")) and bool(S.get("_max_leverage"))
    S["sources"]["MarketMetadata"]={"ok":cached,"degraded":bool(cached),"warmup":not cached,"last_check":now(),
     "mode":"cached_metadata_rest_backoff" if cached else "metadata_bootstrap_retry",
     "markets":len(S.get("_day_volumes",{})),
     "max_leverage_markets":len(S.get("_max_leverage",{})),"error":str(e)[:140]}
   if not cached and isinstance(e,RestDeferred):
    SHUTDOWN.wait(2)
    continue
   if isinstance(e,urllib.error.HTTPError) and e.code==429:
    SHUTDOWN.wait(MARKET_METADATA_SECONDS if cached else 35.0)
    continue
  SHUTDOWN.wait(MARKET_METADATA_SECONDS)

def telemetry():
 # External context calls are slow and optional. They must never hold LOCK or
 # stall the price/exit loop, even if a source hangs or returns an error.
 while not SHUTDOWN.is_set():
  try:
   with LOCK:
    active=S["engine_active"];prices=dict(S.get("_prices",{}))
    symbols=sorted(set(S.get("positions",{}))|set(S.get("pump_positions",{}))|set(S.get("whale_positions",{})))
    count=S["market_count"];equity=S["equity"]
   if active:
    save_market_snapshot(now(),count,equity,len(symbols))
    save_capacity_snapshot()
    save_module_snapshots()
    save_position_snapshots(prices)
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
 semantic=analyze_headline(title,prices)
 return semantic["symbol"],semantic["side"]
def hyperdata(path):
 try:return json.loads(get("http://127.0.0.1:8420"+path))
 except Exception:return None

def deep_context(sym,prices):
 out={"symbol":sym,"price":prices.get(sym),"open_interest":None,"oi_delta":None,"funding":None,"premium":None,"day_volume":None,"orderbook_imbalance":None,"spread_bps":None,"market_momentum":None,"market_regime":None,"breadth":None,"liquidation_map":"unavailable","whale_onchain":"unavailable","tokenomics":"unlock" if False else "unknown"}
 # MarketMetadata already refreshes metaAndAssetCtxs for the whole exchange.
 # Reuse that last-good snapshot instead of issuing the same heavy request once
 # per telemetry position every 30 seconds.
 with LOCK:cached_market=copy.deepcopy((S.get("_pump_ctx") or {}).get(sym) or {})
 if cached_market:
  out["open_interest"]=cached_market.get("open_interest")
  out["oi_delta"]=cached_market.get("oi_delta_60s") if cached_market.get("oi_delta_60s") is not None else cached_market.get("oi_delta")
  out["funding"]=cached_market.get("funding")
  out["premium"]=cached_market.get("premium")
  out["day_volume"]=cached_market.get("day_volume")
 try:
  book=_whale_liq_book(sym)
  if book:
   out["orderbook_imbalance"]=book.get("imbalance")
   out["spread_bps"]=book.get("spread_bps")
   out["liquidation_map"]={"type":"estimated_pressure_not_confirmed_liquidations",
    "bid_depth_usd":book.get("bid_depth_usd"),"ask_depth_usd":book.get("ask_depth_usd"),
    "imbalance":book.get("imbalance"),"data_source":"hyperliquid_l2_book_cached"}
 except Exception:pass
 hist=S.get("_hist",{}).get(sym,[])
 if len(hist)>=3:out["market_momentum"]=hist[-1]/hist[max(0,len(hist)-3)]-1
 # Heavy HyperData wallet/history endpoints are intentionally not polled from
 # generic telemetry. WhaleLiquidationScanner owns the danger-zone feed; Local,
 # Pump and News use direct websocket/cache inputs. This keeps advisory logging
 # from consuming the exchange REST budget.
 out["hyperdata_telemetry"]="owned_by_specialized_workers"
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
 semantic=analyze_headline(title,prices)
 event_type=semantic["event_type"];event_side=semantic["side"]
 if event_type=="PRICE_ACTION":
  feature={"delegated_to":"PumpDumpScanner","reason":"price_action_report_not_news_trigger","event_type":event_type,
           "source":source,"published_at":published_at,"symbol":sym}
  save_event_feature(ident,now(),source,title,sym,0,0.0,feature)
  journal("delegated_price_action_news",ident,{"source":source,"title":title,"symbol":sym,
    "event_type":event_type,"reason":"handled_by_pump_dump_scanner"})
  return 0
 weight=source_weight(source);effective_side=event_side
 if not sym or sym not in prices:
  journal("decision",ident,{"symbol":sym,"raw_side":base_side,"event_side":event_side,"event_type":event_type,"source_weight":weight,"side":0,"reason":"no_tradable_market"})
  return 0
 side,conf,features=decide(title,sym,effective_side,prices)
 features["event_type"]=event_type;features["source_weight"]=weight;features["freshness"]=fresh
 features["semantic_analysis"]=semantic;features["confidence_kind"]="experimental_rule_weight_not_probability"
 features["freshness_window_seconds"]=fresh_window
 conf=min(1.0,conf*weight)
 if side and weight<0.50:side=0
 reaction_limit=100.0 if sym in ("BTC","ETH") else 150.0
 shadow=reaction_shadow(sym,side,published_at,prices.get(sym),reaction_limit)
 late=bool(side and shadow.get("available") and shadow.get("would_skip"))
 if late:side=0
 features["reaction_shadow"]=shadow;features["reaction_filter_active"]=True
 save_event_feature(ident,now(),source,title,sym,side,conf if side else 0.0,features)
 reason="news_already_priced" if late else ((semantic["reason"] if not effective_side else "direction_guard_or_low_source_weight") if not side else "eligible")
 journal("decision",ident,{"symbol":sym,"raw_side":base_side,"event_side":event_side,"effective_side":effective_side,
   "event_type":event_type,"source_weight":weight,"side":side,"confidence":conf if side else 0.0,
   "price":prices.get(sym),"features":features,"reaction_shadow":shadow,"reaction_filter_active":True,"reason":reason})
 if side:open_signal(sym,side,title,prices,ident,published_at,source)
 return side

@account_mutation
def open_signal(sym,side,title,prices,event_id=None,published_at=None,source=""):
 if not NEWS_NEW_ENTRIES_ENABLED:return False
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
  fresh=freshness(published_at,time.time(),fresh_window);price=current_entry_price(sym)
  if not fresh["allowed"] or price is None:
   journal("entry_skipped",event_id,{"strategy":"news","symbol":sym,"reason":fresh["reason"] if not fresh["allowed"] else "stale_market_or_risk_checkpoint_after_reservation"});return False
  notional=margin*TRADE_LEVERAGE
  pos={"entry":price,"side":side,"notional":notional,"opened":now(),"t":time.time(),"headline":title,
       "locked":False,"stop":None,"peak":price,"trail_armed":False,"trail_stop":None,"history":[],
       "leverage":TRADE_LEVERAGE,"margin":margin,"event_id":event_id}
  if not STORE.save(sym,pos,create=True):
   if event_id:log_learning_decision("NEWS:"+str(event_id),"news",sym,side,"SKIPPED","duplicate_symbol_or_event_claim",price,None,TRADE_LEVERAGE,{"headline":title,"source":source})
   return False
  with LOCK:S["positions"][sym]=pos
  if event_id:log_learning_decision("NEWS:"+str(event_id),"news",sym,side,"OPENED","entry_opened",price,None,TRADE_LEVERAGE,{"headline":title,"source":source})
  return True
 finally:_release_shared_entry(sym)

def ingest_event(ident,source,title,published_at=None,source_url=None):
 # Receipt and processing completion are separate durable steps. A failed
 # classifier/journal/entry write must be retried, rather than silently lost
 # because the scanner has already seen the post or saved its receipt.
 if not S["engine_active"] or SHUTDOWN.is_set():return False
 with LOCK:
  inflight=S.setdefault("_news_inflight",set())
  if ident in inflight:return False
  inflight.add(ident)
 received=time.time();hkey=None;owns_headline=False
 try:
  with LOCK:prices=dict(S.get("_prices",{}))
  sym,side=detect(title,prices)
  non_market=is_non_market_news(title);liquidation_news=is_liquidation_news(title)
  if non_market or liquidation_news:side=0
  inserted=save_news_event(ident,now(),source,title,sym,side,published_at,source_url)
  if inserted:
   with LOCK:S["news_seen"]+=1
  else:
   with pg() as c:
    pending=c.execute("select state from news_processing where event_id=%s",(ident,)).fetchone()
   # Existing legacy receipts are intentionally not replayed on this migration.
   if not pending or pending["state"]!="pending":return False
  if not S["engine_active"] or SHUTDOWN.is_set():return False
  fresh=freshness(published_at,received,source_freshness_window(source))
  if fresh["allowed"]:
   normalized=re.sub(r"[^a-z0-9$]+"," ",htmlmod.unescape(title).lower()).strip()
   if normalized:hkey=hashlib.sha256(normalized.encode()).hexdigest()
  duplicate=False
  if hkey:
   with LOCK:
    cache=S.setdefault("_recent_news_keys",{});last=cache.get(hkey)
    duplicate=last is not None and received-last<600
    busy=S.setdefault("_news_headlines_inflight",set())
    if not duplicate:
     if hkey in busy:return False  # receipt stays pending for recovery
     busy.add(hkey);owns_headline=True
  if duplicate:
   journal("duplicate_news_headline",ident,{"source":source,"title":title,"reason":"headline_already_processed"})
  elif non_market:
   journal("ignored_non_market_news",ident,{"source":source,"title":title,"symbol":sym,"reason":"promotional_or_non_market_event"})
  elif liquidation_news:
   feature={"delegated_to":"WhaleLiquidationScanner","reason":"liquidation_news_not_tradeable","source":source,
            "published_at":published_at,"source_url":source_url,"symbol":sym}
   save_event_feature(ident,now(),source,title,sym,0,0.0,feature)
   journal("delegated_liquidation_news",ident,{"source":source,"title":title,"symbol":sym,
     "reason":"handled_by_whale_liquidation_scanner","published_at":published_at,"source_url":source_url})
  else:
   record_event(ident,source,title,sym,side,prices,published_at)
  with pg() as c:
   c.execute("update news_processing set state='done',processed_at=%s where event_id=%s and state='pending'",(now(),ident))
  if hkey and not duplicate:
   with LOCK:
    cache=S.setdefault("_recent_news_keys",{});cache[hkey]=time.time()
    if len(cache)>2000:
     cutoff=time.time()-900
     for key,stamp in list(cache.items()):
      if stamp<cutoff:cache.pop(key,None)
  LATENCIES.record("processing:"+source,time.time()-received,time.time())
  return not duplicate
 finally:
  with LOCK:
   S.setdefault("_news_inflight",set()).discard(ident)
   if owns_headline:S.setdefault("_news_headlines_inflight",set()).discard(hkey)

def recover_news_processing():
 # Replays only receipts created by the durable-pending path. Publication-time
 # freshness is rechecked by record_event and again immediately before entry;
 # a recent receipt cannot turn an old publication into a new trading signal.
 while not SHUTDOWN.is_set():
  if not S["engine_active"]:
   SHUTDOWN.wait(0.5);continue
  try:
   with pg() as c:
    rows=c.execute("""select n.id,n.source,n.title,n.published_at,n.source_url
      from news_processing p join news_events n on n.id=p.event_id
      where p.state='pending' and n.ts::timestamptz >=
        clock_timestamp() - %s * interval '1 second'
      order by n.ts,n.id limit 20""",(NEWS_MAX_AGE_SECONDS,)).fetchall()
   handled=0
   for row in rows:
    if SHUTDOWN.is_set():break
    try:
     handled+=bool(ingest_event(row["id"],row["source"],row["title"],row.get("published_at"),row.get("source_url")))
    except Exception as exc:
     # Leave this receipt pending and continue with the other sources/events.
     with LOCK:S["last_error"]="news_recovery: "+str(exc)[:150]
   with LOCK:S["sources"]["NewsRecovery"]={"ok":True,"last_check":now(),"mode":"durable_pending_replay",
     "pending_batch":len(rows),"handled":handled,"poll_seconds":5,"error":None}
  except Exception as exc:
   with LOCK:S["sources"]["NewsRecovery"]={"ok":False,"last_check":now(),"mode":"durable_pending_replay","error":str(exc)[:180]}
  SHUTDOWN.wait(5)

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
  pool.shutdown(wait=False,cancel_futures=True);race_pool.shutdown(wait=False,cancel_futures=True);ingest_pool.shutdown(wait=False,cancel_futures=True)


CRITICAL_X_HANDLES=list(WATCH)

def ingest_with_retry(ident,source,title,published_at=None,source_url=None):
 # A source may already have advanced its seen-ID cursor when the very first
 # receipt write fails. Keep that event in the bounded worker queue while its
 # original publication is still actionable; never invent a newer timestamp.
 delay=.5
 while not SHUTDOWN.is_set():
  try:return ingest_event(ident,source,title,published_at,source_url)
  except Exception:
   fresh=freshness(published_at,time.time(),source_freshness_window(source))
   if not fresh["allowed"]:raise
   SHUTDOWN.wait(delay);delay=min(4,delay*2)
 return False

def x_critical_realtime():
 handles=list(CRITICAL_X_HANDLES)
 poll=max(4.0,float(os.getenv("X_CRITICAL_POLL_SECONDS","4")))
 firstsquawk_poll=max(2.0,float(os.getenv("FIRSTSQUAWK_POLL_SECONDS","2.5")))
 seen={};primed=set();last_success={};backend_used={};last_error={};inflight={};pending_ingests={};queued_ids=set();latest_publication={};poll_intervals={};fetch_started={}
 received_counts={h:{"new_posts_queued":0,"stale_posts_queued":0,"queue_backpressure":0} for h in handles}
 pool=concurrent.futures.ThreadPoolExecutor(max_workers=min(10,len(handles)),thread_name_prefix="x-critical")
 race_pool=concurrent.futures.ThreadPoolExecutor(max_workers=8,thread_name_prefix="x-freshest-race")
 ingest_pool=concurrent.futures.ThreadPoolExecutor(max_workers=8,thread_name_prefix="x-critical-ingest")
 next_due={h:time.monotonic() for h in handles}
 def newest_epoch(posts):
  stamps=[publication_epoch(p.get("created_at")) for p in posts or []]
  stamps=[x for x in stamps if x is not None and x<=time.time()+10]
  return max(stamps,default=-1)
 def fetch_one(handle,preferred=None):
  errors=[]
  chain=[
   ("syndication",lambda:free_x_syndication_fetch(handle,timeout=2.0)),
   ("embed",lambda:free_x_embed_fetch(handle,timeout=2.0)),
   ("fx",lambda:free_x_fetch(handle,timeout=2.0,attempts=1)),
   ("xlookup",lambda:free_x_lookup_fetch(handle,timeout=2.0)),
   ("fixupx",lambda:free_x_fixupx_fetch(handle,timeout=2.0)),
   ("nitter",lambda:free_x_nitter_fetch(handle,timeout=2.0)),
   ("vx",lambda:free_x_vx_fetch(handle,timeout=2.0)),
  ]
  # FirstSquawk is latency-critical. A merely healthy mirror can lag the
  # publisher by a minute, so race independent public routes and choose the
  # timeline with the newest real publication timestamp.
  if handle=="FirstSquawk":
   race=[
    ("syndication",lambda:free_x_syndication_fetch(handle,timeout=1.8)),
    ("fx",lambda:free_x_fetch(handle,timeout=1.8,attempts=1)),
    ("xlookup",lambda:free_x_lookup_fetch(handle,timeout=1.8)),
    ("fixupx",lambda:free_x_fixupx_fetch(handle,timeout=1.8)),
   ]
   futures={race_pool.submit(fn):name for name,fn in race}
   done,_=concurrent.futures.wait(futures,timeout=2.05)
   candidates=[]
   for fut in done:
    name=futures[fut]
    try:
     posts=fut.result()
     if posts:candidates.append((newest_epoch(posts),name,posts))
     else:errors.append(name+":empty")
    except Exception as exc:errors.append(name+":"+str(exc)[:70])
   for fut in futures:
    if not fut.done():fut.cancel()
   if candidates:
    _,name,posts=max(candidates,key=lambda row:row[0])
    return posts,"freshest_race:"+name
  # Other critical accounts keep the low-request preferred-backend path.
  chain.sort(key=lambda item:item[0]!=preferred)
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
    if h in fetch_started:poll_intervals[h]=mono-fetch_started[h]
    fetch_started[h]=mono
    hpoll=firstsquawk_poll if h=="FirstSquawk" else poll
    inflight[pool.submit(fetch_one,h,backend_used.get(h))]=(h,mono);next_due[h]=mono+hpoll
   for fut in list(pending_ingests):
    if not fut.done():continue
    handle,post_id=pending_ingests.pop(fut);queued_ids.discard((handle,post_id))
    try:
     fut.result();seen.setdefault(handle,set()).add(post_id)
    except Exception as exc:
     with LOCK:S["last_error"]="x_ingestion: "+type(exc).__name__+":"+str(exc)[:160]
   done=[f for f in list(inflight) if f.done()]
   for fut in done:
    h,started=inflight.pop(fut);src="XCritical:"+h
    try:
     posts,backend=fut.result();last_success[h]=time.time();backend_used[h]=backend;last_error.pop(h,None)
     ids=[str(p["id"]) for p in posts]
     if h not in primed:
      # Durable event IDs already prevent replay after a deploy. A publication
      # from 30 seconds before startup is still actionable under the 120s rule.
      fresh=[p for p in posts if freshness(p.get("created_at"),time.time(),source_freshness_window("XOfficial:"+h))["allowed"]]
      seen[h]=set(ids)-{str(p["id"]) for p in fresh};primed.add(h)
     else:
      old=seen.setdefault(h,set());fresh=[p for p in posts if str(p["id"]) not in old]
      if len(old)>250:old.intersection_update(ids)
     stamps=[publication_epoch(p.get("created_at")) for p in posts]
     stamps=[t for t in stamps if t is not None and t<=time.time()+10]
     if stamps:latest_publication[h]=max(stamps)
     latencies=[]
     for p in sorted(fresh,key=lambda q:publication_epoch(q.get("created_at")) or 0,reverse=True):
      stamp=publication_epoch(p.get("created_at"));age=time.time()-stamp if stamp is not None else None
      # A mirror can resurface an old/pinned post after a backend switch.
      # Its publication age is not a measured delivery delay while watching.
      if age is not None and age>=0 and stamp>=START:
       latencies.append(age);LATENCIES.record("delivery:XOfficial:"+h,age,time.time())
      post_id=str(p["id"])
      if (h,post_id) in queued_ids:continue
      ident=hashlib.sha256(("XFree:"+h+":"+str(p["id"])).encode()).hexdigest()
      if len(pending_ingests)<32 and (len(pending_ingests)<16 or freshness(p.get("created_at"),time.time(),source_freshness_window("XOfficial:"+h))["allowed"]):
       # Keep queue capacity for actionable fresh posts when backlog is high. The entry guard
       # rejects them; silently dropping them hid the actual source latency.
       future=ingest_pool.submit(ingest_with_retry,ident,"XOfficial:"+h,p["text"],p.get("created_at"),p.get("url"))
       pending_ingests[future]=(h,post_id);queued_ids.add((h,post_id))
       received_counts[h]["new_posts_queued"]+=1
       if not freshness(p.get("created_at"),time.time(),source_freshness_window("XOfficial:"+h))["allowed"]:received_counts[h]["stale_posts_queued"]+=1
      else:
       received_counts[h]["queue_backpressure"]+=1
       with LOCK:S["last_error"]="x_ingestion_queue_full"
     latency=min(latencies) if latencies else None
     with LOCK:S["sources"][src]={"ok":True,"active":True,"mode":backend+"_critical_4s","backend":backend,
      "last_check":now(),"posts":len(posts),"poll_seconds":poll,"last_request_seconds":round(time.monotonic()-started,2),
      "delivery_latency_seconds":round(latency,2) if latency is not None else None,
      "delivery":LATENCIES.summary("delivery:XOfficial:"+h,time.time()),
      "latest_post_age_seconds":round(time.time()-latest_publication[h],2) if h in latest_publication else None,
      "publication_age_limit_seconds":source_freshness_window("XOfficial:"+h),**received_counts[h],
      "realtime_verified":LATENCIES.summary("delivery:XOfficial:"+h,time.time())["realtime_verified"],"error":None}
    except Exception as exc:
     err=str(exc)[:420];last_error[h]=err
     with LOCK:S["sources"][src]={"ok":False,"active":False,"mode":"critical_fallback_chain","last_check":now(),
      "poll_seconds":poll,"last_request_seconds":round(time.monotonic()-started,2),"error":err}
   with LOCK:
    wall=time.time()
    status={h:{"ok":bool(last_success.get(h) and wall-last_success[h]<=max(12,poll*3)),
               "active":bool(last_success.get(h) and wall-last_success[h]<=max(12,poll*3)),
               "backend":backend_used.get(h),"last_success_epoch":last_success.get(h),
               "error":last_error.get(h),"observed_poll_interval_seconds":round(poll_intervals[h],3) if h in poll_intervals else None,
               "latest_post_age_seconds":round(wall-latest_publication[h],2) if h in latest_publication else None,
               **received_counts[h],
               "delivery":LATENCIES.summary("delivery:XOfficial:"+h,wall)} for h in handles}
    ok_count=sum(v["ok"] for v in status.values())
    _xcrit={"ok":ok_count==len(handles),"mode":"dedicated_critical_pool","last_check":now(),
      "accounts_ok":ok_count,"accounts_initialized":len(handles),"accounts_total":len(handles),"active_accounts":ok_count,
      "scan_label":"SCANNING %s / %s"%(ok_count,len(handles)),"target_poll_seconds":poll,
      "firstsquawk_target_poll_seconds":firstsquawk_poll,"firstsquawk_freshest_backend_race":True,
      "key_accounts":status,"scan_workers":len(handles),**aggregate_delivery(status),"pending_events":len(pending_ingests),
      "error":None if ok_count==len(handles) else "partial_critical_coverage"}
    S["sources"]["XCriticalMonitor"]=copy.deepcopy(_xcrit);S["sources"]["XMonitor"]=copy.deepcopy(_xcrit)
   SHUTDOWN.wait(0.20)
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
 handles={h.strip().lower() for h in os.getenv("TRUTH_WATCH_HANDLES","realDonaldTrump").split(",") if h.strip()}
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
 handles=[h.strip() for h in os.getenv("TRUTH_WATCH_HANDLES","realDonaldTrump").split(",") if h.strip()]
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
   if last_day!=day:
    save_learning_snapshot();last_day=day
  except Exception as e:
   with LOCK:S["last_error"]="adaptive: "+str(e)[:160]
  SHUTDOWN.wait(300)

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

def piq_direct_realtime():
 # Discovery and story resolution have separate bounds. A failed story remains
 # retryable instead of disappearing permanently into the seen-URL set.
 poll=max(2.0,float(os.getenv("PIQ_FAST_POLL_SECONDS","2.5")))
 seen={};pending={};fetching={};ingesting={};startup_ignored=set()
 primed=False;delay=poll;previous_started=None;error_log_at=0;visible=0
 next_discovery=0;transport_ok=False;err=None;last_request_seconds=None;cycle_interval=None
 totals={"story_fetch_failures_total":0,"story_retries_total":0,"exhausted_stories_total":0,
         "ingestion_errors_total":0,"ingested_total":0,"filtered_low_signal":0,"startup_old_filtered":0}
 last_story_error=None;last_ingest_error=None;last_delivery=None
 fetch_pool=concurrent.futures.ThreadPoolExecutor(max_workers=6,thread_name_prefix="piq-story")
 ingest_pool=concurrent.futures.ThreadPoolExecutor(max_workers=4,thread_name_prefix="piq-ingest")
 def finish(url):
  pending.pop(url,None);seen[url]=time.monotonic()
  if len(seen)>1200:
   for old in sorted(seen,key=seen.get)[:200]:seen.pop(old,None)
 def retry(url,record,kind,exc):
  nonlocal last_story_error,last_ingest_error
  message=type(exc).__name__+":"+str(exc)[:150]
  if kind=="fetch":
   totals["story_fetch_failures_total"]+=1;last_story_error=message
  else:
   totals["ingestion_errors_total"]+=1;last_ingest_error=message
   with LOCK:S["last_error"]="PiQDirect ingestion: "+message
  attempts=record["fetch_attempts"] if kind=="fetch" else record["ingest_attempts"]
  if attempts>=3 or time.monotonic()-record["first_seen"]>=60:
   totals["exhausted_stories_total"]+=1;finish(url)
   try:journal("piq_story_rejected",None,{"url":url,"stage":kind,"attempts":attempts,"reason":message})
   except Exception:pass
  else:
   totals["story_retries_total"]+=1
   record["state"]="fetch_wait" if kind=="fetch" else "ready"
   record["not_before"]=time.monotonic()+min(10,poll*attempts)
 try:
  while not SHUTDOWN.is_set():
   if not S["engine_active"]:
    SHUTDOWN.wait(0.25);continue
   started=time.monotonic();cycle_errors=0;new_visible=0;ingested_cycle=0
   try:
    for future in list(ingesting):
     if not future.done():continue
     url=ingesting.pop(future);record=pending.get(url)
     if record is None:continue
     try:
      ingested=bool(future.result());totals["ingested_total"]+=ingested;ingested_cycle+=ingested
      last_ingest_error=None;finish(url)
     except Exception as exc:
      cycle_errors+=1;retry(url,record,"ingest",exc)
    for future in list(fetching):
     if not future.done():continue
     url=fetching.pop(future);record=pending.get(url)
     if record is None:continue
     try:
      story=future.result();stamp=publication_epoch(story.get("created_at"))
      if stamp is None:raise ValueError("exact_publication_timestamp_missing")
      last_story_error=None
      if record["bootstrap"] and not freshness(story.get("created_at"),time.time(),source_freshness_window("PiQDirect"))["allowed"]:
       totals["startup_old_filtered"]+=1;finish(url);continue
      if not piq_high_signal(story["text"]):
       totals["filtered_low_signal"]+=1;finish(url);continue
      observed_at=time.time()
      age=observed_at-stamp
      # Delivery latency is evidence only for publications that happened after
      # this process began observing PiQ. Old pages discovered later are not
      # realtime samples and must not poison p95/max or realtime verification.
      if age>=0 and stamp>=START:
       last_delivery=age;LATENCIES.record("delivery:PiQDirect",age,observed_at)
      record["story"]=story;record["state"]="ready";record["not_before"]=0
     except Exception as exc:
      cycle_errors+=1;retry(url,record,"fetch",exc)
    if time.monotonic()>=next_discovery:
     discovery_started=time.monotonic()
     cycle_interval=discovery_started-previous_started if previous_started is not None else None
     previous_started=discovery_started
     rows=piq_discover(timeout=min(3.0,max(1.8,poll)),limit=40)
     last_request_seconds=time.monotonic()-discovery_started
     next_discovery=discovery_started+poll;visible=len(rows);transport_ok=True;err=None;delay=poll
     bootstrap=not primed
     if bootstrap:
      # Resolve a small startup sample using the same publication-age limit as
      # normal ingestion. Durable IDs prevent reopening a completed event.
      startup_ignored={item["url"] for item in rows[8:]};primed=True;rows=rows[:8]
     for item in rows:
      url=item["url"]
      if url in seen or url in pending or url in startup_ignored:continue
      if len(pending)>=32:break
      pending[url]={"item":item,"bootstrap":bootstrap,"state":"fetch_wait","first_seen":time.monotonic(),
                    "not_before":0,"fetch_attempts":0,"ingest_attempts":0};new_visible+=1
    for url,record in list(pending.items()):
     if record["state"] in ("fetching","ingesting"):continue
     if time.monotonic()-record["first_seen"]>=60:
      totals["exhausted_stories_total"]+=1;finish(url);continue
     if time.monotonic()<record["not_before"]:continue
     if record["state"]=="fetch_wait" and len(fetching)<24:
      record["fetch_attempts"]+=1;record["state"]="fetching";item=record["item"]
      fetching[fetch_pool.submit(piq_fetch_story,url,item.get("headline_hint"),timeout=3.0)]=url
     elif record["state"]=="ready" and len(ingesting)<24:
      record["ingest_attempts"]+=1;record["state"]="ingesting";story=record["story"]
      ident=hashlib.sha256(("PiQDirect:"+url).encode()).hexdigest()
      ingesting[ingest_pool.submit(ingest_event,ident,"PiQDirect",story["text"],story.get("created_at"),url)]=url
   except Exception as exc:
    err=str(exc)[:260] if str(exc) else type(exc).__name__
    transport_ok=False
    with LOCK:S["errors"]+=1;S["last_error"]="PiQDirect: "+err[:180]
    if time.time()-error_log_at>=120:
     error_log_at=time.time()
     try:journal("source_error",None,{"source":"PiQDirect","kind":"direct_site_scan","error":err})
     except Exception:pass
    delay=min(120,max(poll,delay*1.8));next_discovery=time.monotonic()+delay
   delivery=LATENCIES.summary("delivery:PiQDirect",time.time())
   with LOCK:S["sources"]["PiQDirect"]={"ok":transport_ok,"degraded":bool(cycle_errors or len(pending)>=32),
    "last_check":now(),"mode":"public_site_direct_scan","poll_seconds":poll,"stories_visible":visible,
    "new_visible":new_visible,"new_ingested":ingested_cycle,"pending_stories":len(pending),
    "fetches_inflight":len(fetching),"ingestions_inflight":len(ingesting),"story_workers":6,"ingest_workers":4,
    "retrying_stories":sum(r["fetch_attempts"]>1 or r["ingest_attempts"]>1 for r in pending.values()),
    "request_seconds":round(last_request_seconds,3) if last_request_seconds is not None else None,
    "cycle_seconds":round(time.monotonic()-started,3),
    "observed_poll_interval_seconds":round(cycle_interval,3) if cycle_interval is not None else None,
    "delivery_latency_seconds":round(last_delivery,3) if last_delivery is not None else None,
    "delivery":delivery,"realtime_verified":bool(transport_ok and delivery["realtime_verified"]),
    "last_story_error":last_story_error,"last_ingest_error":last_ingest_error,"error":err,**totals}
   # Completed story and ingestion futures are drained promptly between polls;
   # their latency does not include another full discovery interval per stage.
   SHUTDOWN.wait(min(0.10,max(0.03,next_discovery-time.monotonic())))
 finally:
  fetch_pool.shutdown(wait=False,cancel_futures=True);ingest_pool.shutdown(wait=False,cancel_futures=True)

def news_feed(source,url):
 # Every news source is isolated. Search feeds have an independent Bing RSS
 # fallback; direct publishers have browser-TLS fallback when urllib is blocked.
 candidates=_news_candidates(url)
 base_poll=max(15,NEWS_POLL_SECONDS) if candidates[0][0]=="direct_rss" else max(20,NEWS_POLL_SECONDS)
 delay=base_poll;error_log_at=0;seen=set()
 while not SHUTDOWN.is_set():
  if not S.get("engine_active"):
   SHUTDOWN.wait(.5);continue
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
    for item in sorted(items,key=lambda x:publication_epoch(x.findtext("pubDate") or x.findtext("{*}published")) or 0,reverse=True):
     if SHUTDOWN.is_set():break
     title=(item.findtext("title") or item.findtext("{*}title") or "").strip()
     if not title:continue
     pub=item.findtext("pubDate") or item.findtext("{*}published")
     link=item.findtext("link")
     if not link:
      node=item.find("{*}link")
      if node is not None:link=node.get("href")
     ident=hashlib.sha256((source+title).encode()).hexdigest()
     if ident in seen:continue
     count+=bool(ingest_event(ident,source,title,pub,link));seen.add(ident)
     if len(seen)>2000:seen={ident}
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
def today_realized_pnl_utc():
 try:
  with LOCK:baseline=copy.deepcopy(S.get("pump_history_baseline",{}))
  stats=strategy_performance(pg,baseline)
  rows=stats["periods"]["today_utc"].values()
  return {"pnl":round(sum(r["realized_pnl"] for r in rows),4),"trades":sum(r["trades"] for r in rows),
    "timezone":"UTC","basis":"deduplicated_realized_closed_trades"}
 except Exception as exc:
  return {"pnl":None,"trades":None,"timezone":"UTC","error":type(exc).__name__+":"+str(exc)[:100]}


def build_dashboard_snapshot(history=None):
 with LOCK:
  state={k:copy.deepcopy(v) for k,v in S.items() if not k.startswith("_")}
  state["_prices"]=dict(S.get("_prices",{}))
 trades=copy.deepcopy(history.get("trades",[])) if history is not None else [dict(x) for x in persistent_trades(100)]
 baseline=copy.deepcopy(state.get("pump_history_baseline",{}))
 if int(baseline.get("restored_closed_trades",0) or 0)>0:
  trades.append({"id":"RESTORED_PUMP_BASELINE","opened":None,"closed":PUMP_RESTORED_HISTORY_TIMESTAMP,
   "symbol":"PUMP/DUMP x%s"%int(baseline.get("restored_closed_trades",0) or 0),"side":0,
   "entry":None,"exit":None,"pnl":float(baseline.get("restored_realized_pnl",0) or 0),
   "reason":"restored historical aggregate; individual deleted rows unavailable",
   "headline":"PUMP_DUMP","event_id":None,"strategy":"pump_dump_restored_baseline","score":None,
   "features":{"restored_aggregate":True}})
 newsrows=copy.deepcopy(history.get("news",[])) if history is not None else [dict(x) for x in persistent_news(20)]
 feats=copy.deepcopy(history.get("features",[])) if history is not None else [dict(x) for x in persistent_features(10)]
 prices=state.get("_prices",{});positions=[];unreal=0.0
 for sym,p in state["positions"].items():
  px=prices.get(sym,p["entry"]);move=(px/p["entry"]-1)*p["side"];gross=p["notional"]*move;fees=p["notional"]*FEE+p["notional"]*(px/p["entry"])*FEE;pnl=paper_pnl(p["notional"],p["entry"],px,p["side"],FEE);lev=float(p.get("leverage",LEV));margin=float(p.get("margin",p["notional"]/lev));roi=(pnl/margin*100) if margin>0 else 0.0;unreal+=pnl
  positions.append({"strategy":"NEWS","symbol":sym,"side":"LONG" if p["side"]>0 else "SHORT","entry":p["entry"],"mark":px,"notional_usd":round(p["notional"],2),"margin_usd":round(margin,2),"leverage":lev,"roe_pct":round(roi,3),"unrealized_pnl":round(pnl,4),"opened":p["opened"],"headline":p["headline"],"protection_stop":p.get("stop"),"trailing_stop":p.get("trail_stop"),"peak":p.get("peak"),"trailing_armed":p.get("trail_armed",False),"last_evaluated_at":p.get("last_evaluated_at")})
 pump_positions=[];pump_unreal=0.0
 whale_positions=[];whale_unreal=0.0
 hype_swing_position=None;local_swing_positions=[];hype_swing_unreal=0.0
 local_book=state.get("local_swing_positions",{})
 if not local_book and state.get("hype_swing_position"):local_book={HYPE_SWING_SYMBOL:state["hype_swing_position"]}
 for lsym,hspos in local_book.items():
  hsmark=prices.get(lsym,hspos["entry"]);lspnl=paper_pnl(hspos["notional"],hspos["entry"],hsmark,hspos["side"],FEE);hype_swing_unreal+=lspnl
  card={"strategy":"LOCAL_H1_M15_SWING_V5","symbol":lsym,"side":"LONG" if hspos["side"]>0 else "SHORT",
   "entry":hspos["entry"],"mark":hsmark,"margin_usd":round(hspos["margin"],2),"notional_usd":round(hspos["notional"],2),
   "leverage":hspos["leverage"],"roe_pct":round(lspnl/hspos["margin"]*100,3) if hspos["margin"] else 0,
   "unrealized_pnl":round(lspnl,4),"opened":hspos["opened"],"features":hspos.get("features",{})}
  local_swing_positions.append(card)
  if lsym==HYPE_SWING_SYMBOL:hype_swing_position=card
 experiment_positions=[];experiment_unreal=0.0
 for esym,epos in state.get("local_v12_positions",{}).items():
  emark=prices.get(esym,epos["entry"]);epnl=paper_pnl(epos["notional"],epos["entry"],emark,epos["side"],FEE);experiment_unreal+=epnl
  experiment_positions.append({"strategy":"LOCAL_10TOKEN_24H","symbol":esym,"side":"LONG" if epos["side"]>0 else "SHORT",
   "entry":epos["entry"],"mark":emark,"margin_usd":round(epos["margin"],2),"notional_usd":round(epos["notional"],2),
   "leverage":epos["leverage"],"roe_pct":round(epnl/epos["margin"]*100,3) if epos["margin"] else 0,
   "unrealized_pnl":round(epnl,4),"opened":epos["opened"],"features":epos.get("features",{})})
 experiment_total=float(state.get("local_experiment_equity",LOCAL_EXPERIMENT_STARTING_EQUITY))+experiment_unreal
 hype_swing_total=float(state.get("hype_swing_equity",HYPE_SWING_STARTING_EQUITY))+hype_swing_unreal
 comparison={}
 for state_name,label in (("local_s1","Strategy 1 — Restored Caterpillar"),("local_s2","Strategy 2 — H1 Pivot Swing"),("local_s3","Strategy 3 — Local12 v10")):
  rows=[];unreal_cmp=0.0
  for csym,cpos in state.get(state_name+"_positions",{}).items():
   cmark=prices.get(csym,cpos["entry"])
   cpnl=paper_pnl(cpos["notional"],cpos["entry"],cmark,cpos["side"],FEE);unreal_cmp+=cpnl
   rows.append({"symbol":csym,"side":"LONG" if cpos["side"]>0 else "SHORT","entry":cpos["entry"],"mark":cmark,
     "margin_usd":round(cpos["margin"],2),"notional_usd":round(cpos["notional"],2),"leverage":cpos["leverage"],
     "roe_pct":round(cpnl/cpos["margin"]*100,3) if cpos["margin"] else 0,"unrealized_pnl":round(cpnl,4),
     "opened":cpos["opened"],"features":cpos.get("features",{})})
  src=copy.deepcopy(state.get("sources",{}).get(label,{}))
  realized_equity=float(state.get(state_name+"_equity",500.0) or 500.0)
  comparison[state_name]={"label":label,"positions":rows,"unrealized_pnl":round(unreal_cmp,4),
   "realized_equity":round(realized_equity,4),"total_equity":round(realized_equity+unreal_cmp,4),
   "pnl_pct":round((realized_equity+unreal_cmp)/500.0*100-100,3),"engine":src,
   "stats":copy.deepcopy(src.get("stats") or {}),"watch":copy.deepcopy(state.get(state_name+"_watch",{}))}
 for sym,p in state.get("whale_positions",{}).items():
  px=prices.get(sym,p["entry"]);move=(px/p["entry"]-1)*p["side"];gross=p["notional"]*move;fees=p["notional"]*FEE*2;pnl=paper_pnl(p["notional"],p["entry"],px,p["side"],FEE);whale_unreal+=pnl
  whale_positions.append({"strategy":"WHALE_LIQ","symbol":sym,"side":"LONG" if p["side"]>0 else "SHORT","entry":p["entry"],"mark":px,"notional_usd":round(p["notional"],2),"margin_usd":round(p["margin"],2),"leverage":p["leverage"],"roe_pct":round(pnl/p["margin"]*100,3) if p["margin"] else 0,"unrealized_pnl":round(pnl,4),"opened":p["opened"],"score":round(float(p.get("score",0)),2),"features":p.get("features",{})})
 for sym,p in state.get("pump_positions",{}).items():
  px=prices.get(sym,p["entry"]);move=(px/p["entry"]-1)*p["side"];gross=p["notional"]*move;fees=p["notional"]*FEE*2;pnl=paper_pnl(p["notional"],p["entry"],px,p["side"],FEE);pump_unreal+=pnl
  pump_positions.append({"strategy":"PUMP_DUMP","symbol":sym,"side":"LONG" if p["side"]>0 else "SHORT","entry":p["entry"],"mark":px,"notional_usd":round(p["notional"],2),"margin_usd":round(p["margin"],2),"leverage":p["leverage"],"roe_pct":round(pnl/p["margin"]*100,3) if p["margin"] else 0,"unrealized_pnl":round(pnl,4),"opened":p["opened"],"score":round(float(p.get("score",0)),2)})
 starts=[x.get("opened") for x in trades if x.get("opened")]+[x.get("opened") for x in positions if x.get("opened")]
 account_started=min(starts) if starts else now()
 try: account_age_seconds=max(0,int((datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(account_started.replace("Z","+00:00"))).total_seconds()))
 except Exception: account_age_seconds=0
 contributed=max(PAPER_RESET,float(state.get("contributed_capital",PAPER_RESET)));total=state["equity"]+unreal+pump_unreal+whale_unreal+hype_swing_unreal;account_pnl_pct=(total/contributed-1)*100;account_roi=account_pnl_pct;realized_pnl_pct=(float(state["realized_pnl"])/contributed)*100;total_pnl_pct=(total/PAPER_RESET-1)*100
 used_margin=sum(float(p.get("margin",float(p.get("notional",0))/max(1.0,float(p.get("leverage",TRADE_LEVERAGE))))) for book in (state.get("positions",{}),state.get("pump_positions",{}),state.get("whale_positions",{}),local_book) for p in book.values())
 free_margin=max(0.0,float(state["equity"])-used_margin);margin_utilization=(used_margin/float(state["equity"])*100.0) if float(state["equity"])>0 else 0.0
 visible_sources={k:v for k,v in state["sources"].items() if not k.startswith("XIndex:") and k!="XIndexMonitor" and not k.startswith("XFree:") and k not in SEARCH_INDEX_FEEDS and not v.get("disabled") and not (k.startswith("TruthDirect:") and k!="TruthDirect:realDonaldTrump")}
 return {"strategy_performance":strategy_capital_basis((history or {}).get("strategy_performance",{}),state.get("contributed_capital",PAPER_RESET),{"news":unreal,"pump_dump":pump_unreal,"whale_liquidation":whale_unreal,"local":hype_swing_unreal}),"strategy_open_pnl":{"news":round(unreal,4),"pump_dump":round(pump_unreal,4),"whale_liquidation":round(whale_unreal,4),"local":round(hype_swing_unreal,4)},"snapshot_at":now(),"history_updated_at":(history or {}).get("updated_at"),"history_error":(history or {}).get("error"),"today_pnl":history.get("today_pnl",{}) if history is not None else today_realized_pnl_utc(),"statistics_basis":state.get("statistics_basis","full_recorded_history"),"operator_cleanup":state.get("operator_cleanup",{}),"emergency_profit_guard":state.get("emergency_profit_guard",{}),"daily_activity":state.get("daily_activity",{}),"daily_entry_limit":None,"margin_budget":"shared_all_strategies","mode":state["mode"],"balance":round(state["equity"],4),"capital_contributed":round(float(state.get("contributed_capital",PAPER_RESET)),4),"unrealized_pnl":round(unreal+pump_unreal+whale_unreal+hype_swing_unreal,4),"total_equity":round(total,4),"realized_pnl":round(state["realized_pnl"],4),"account_started":account_started,"account_age_seconds":account_age_seconds,"account_roi_pct":round(account_roi,3),"account_pnl_pct":round(account_pnl_pct,3),"realized_pnl_pct":round(realized_pnl_pct,3),"total_pnl_pct":round(total_pnl_pct,3),"used_margin":round(used_margin,4),"free_margin":round(free_margin,4),"margin_utilization_pct":round(margin_utilization,3),"trade_margin_fraction_pct":round(TRADE_MARGIN_FRACTION*100,3),"trade_leverage":TRADE_LEVERAGE,"positions":positions+pump_positions+whale_positions+local_swing_positions,"pump_positions":pump_positions,
"pump_unrealized_pnl":round(pump_unreal,4),"pump_realized_pnl":round(float(state.get("pump_realized_pnl",0) or 0),4),
"pump_total_pnl":round(float(state.get("pump_realized_pnl",0) or 0)+pump_unreal,4),
"pump_history_baseline":copy.deepcopy(state.get("pump_history_baseline",{})),"pump_trades":state.get("pump_trades",0),"whale_liq_positions":whale_positions,"whale_liq_unrealized_pnl":round(whale_unreal,4),"whale_liq_trades":state.get("whale_trades",0),"whale_liq_engine":copy.deepcopy(state.get("sources",{}).get("WhaleLiquidationScanner",{})),"hype_h1_position":hype_swing_position,"local_swing_positions":local_swing_positions,"local_swing_watch":copy.deepcopy(state.get("local_swing_watch",{})),
"local_swing_symbols":list(LOCAL_SWING_SYMBOLS),"hype_h1_balance":round(float(state.get("hype_swing_equity",HYPE_SWING_STARTING_EQUITY)),4),
"hype_h1_unrealized_pnl":round(hype_swing_unreal,4),"hype_h1_total_equity":round(hype_swing_total,4),
"hype_h1_pnl_pct":round((hype_swing_total/HYPE_SWING_STARTING_EQUITY-1)*100,3),"hype_h1_realized_pnl":round(float(state.get("hype_swing_realized_pnl",0)),4),
"hype_h1_trades":state.get("hype_swing_trades",0),"hype_h1_engine":copy.deepcopy(state.get("sources",{}).get("HypeH1LocalSwing",{})),
"hype_h1_stats":history.get("hype_stats",{}) if history is not None else hype_swing_stats(),"hype_h1_policy":CATERPILLAR_POLICY,
"local_experiment_symbols":list(LOCAL_EXPERIMENT_SYMBOLS),"local_v12_positions":experiment_positions,
"local_experiment_watch":copy.deepcopy(state.get("local_experiment_watch",{})),
"local_experiment_balance":round(float(state.get("local_experiment_equity",LOCAL_EXPERIMENT_STARTING_EQUITY)),4),
"local_experiment_unrealized_pnl":round(experiment_unreal,4),"local_experiment_total_equity":round(experiment_total,4),
"local_experiment_pnl_pct":round((experiment_total/LOCAL_EXPERIMENT_STARTING_EQUITY-1)*100,3),
"local_experiment_realized_pnl":round(float(state.get("local_experiment_realized_pnl",0) or 0),4),
"local_experiment_trades":int(state.get("local_experiment_trades",0) or 0),
"local_v10_closed_trades":copy.deepcopy((history or {}).get("local_v10_closed_trades",[])),
"local_s1_causal_history":copy.deepcopy((history or {}).get("local_s1_causal_history",{})),
"local_v10_today_realized_pnl":float((history or {}).get("local_v10_today_realized_pnl",0) or 0),
"local_experiment_stats":copy.deepcopy(state.get("local_experiment_stats",{})),
"local_experiment_engine":copy.deepcopy(state.get("sources",{}).get("Caterpillar 1.0",{})),
"comparison_strategies":comparison,"strategy1_primary":{"starting_equity":500.0,
"realized_equity":round(float(state.get("local_s1_equity",500.0) or 500.0),4),
"realized_pnl":round(float(state.get("local_s1_equity",500.0) or 500.0)-500.0,4),
"unrealized_pnl":round(float((comparison.get("local_s1") or {}).get("unrealized_pnl",0) or 0),4),
"total_equity":round(float((comparison.get("local_s1") or {}).get("total_equity",state.get("local_s1_equity",500.0)) or 500.0),4),
"open_positions":copy.deepcopy((comparison.get("local_s1") or {}).get("positions",[])),
"closed_trades":copy.deepcopy((history or {}).get("local_s1_closed_trades",[])),
"watch":copy.deepcopy(state.get("local_s1_watch",{})),
"stats":copy.deepcopy((comparison.get("local_s1") or {}).get("stats",{})),
"engine":copy.deepcopy((comparison.get("local_s1") or {}).get("engine",{}))},
"strategy1_historical_benchmark":{"starting_equity":500.0,"mfe_upper_equity":877.36,"mfe_opportunity_pnl":377.36,"basis":"historical favorable-excursion upper bound from prior actual-entry analysis","executed":False,"causal":False,"label":"HISTORICAL MFE BENCHMARK — NOT EXECUTED"},"module_trading_enabled":{"strategy1":True,"news":False,"whale_liquidation":False,"pump_dump":False,"strategy2":False,"strategy3":False,"legacy_local":False},"account_model":"UNIFIED_PAPER_ACCOUNT_ALL_STRATEGIES","trades":trades,"news":newsrows,"features":feats,"sources":visible_sources,"errors":state["errors"],"last_error":state["last_error"],"news_seen":state["news_seen"],"market_count":state["market_count"],"last_poll":state["last_poll"],"uptime_seconds":int(time.time()-START),"engine_active":state["engine_active"],"engine_error":state["engine_error"],"last_checkpoint":state["last_checkpoint"],"last_market_error":state["last_market_error"],"news_max_age_seconds":NEWS_MAX_AGE_SECONDS,"news_health":copy.deepcopy(state.get("news_health",{})),"market_structure_filter_active":False,"entry_rejections":dict(S.get("_entry_rejections",{})),"decision_counts":dict(S.get("_decision_counts",{})),"learning":copy.deepcopy(S.get("adaptive",{})),"decision_learning":copy.deepcopy(state.get("learning_audit",{})),"latency_metrics":LATENCIES.snapshot(time.time()),"simulation":{"execution":"mid_price_paper","funding_modeled":False,"slippage_modeled":False,"exchange_liquidation_modeled":False,"profitability_validated":False},"version":os.getenv("RENDER_GIT_COMMIT","risk-state-v2")}

def dashboard():
 # Render open positions from current in-memory prices; slow history queries
 # must never pin an old account/price snapshot indefinitely.
 with LOCK:history=copy.deepcopy(S.get("_dashboard_history",{}))
 return build_dashboard_snapshot(history=history)


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


CORE_NEWS_SOURCES=("XOfficial:FirstSquawk","PiQDirect")
NEWS_SILENCE_WARN_SECONDS=max(300.0,float(os.getenv("NEWS_SILENCE_WARN_SECONDS","1800")))

def news_health_snapshot(daily=None):
 if daily is None:daily=daily_audit_stats()
 try:
  with pg() as c:
   rows=c.execute("""select ts,source,published_at,title,symbol,signal
     from news_events
     where ts::timestamptz >= date_trunc('day', now())
     order by ts desc limit 600""").fetchall()
   last_eligible=c.execute("""select recorded_at,event_id,payload
     from audit_journal
     where recorded_at::timestamptz >= date_trunc('day', now())
       and kind='decision' and payload->>'reason'='eligible'
     order by recorded_at desc limit 1""").fetchone()
  wall=time.time();latest_by_source={};fresh_rows=[]
  for row in rows:
   source=str(row.get("source") or "")
   if source not in CORE_NEWS_SOURCES:continue
   rec=publication_epoch(row.get("ts"));pub=publication_epoch(row.get("published_at"))
   lag=(rec-pub) if rec is not None and pub is not None else None
   if source not in latest_by_source:
    latest_by_source[source]={"received_at":row.get("ts"),"published_at":row.get("published_at"),
      "headline":row.get("title"),"symbol":row.get("symbol"),"signal":row.get("signal"),
      "publication_age_seconds":round(wall-pub,2) if pub is not None else None,
      "ingest_lag_seconds":round(lag,2) if lag is not None else None}
   if lag is not None and lag>=-10 and lag<=source_freshness_window(source):
    fresh_rows.append((rec or 0,row,lag))
  fresh_rows.sort(key=lambda item:item[0],reverse=True)
  last_fresh=fresh_rows[0] if fresh_rows else None
  reasons=daily.get("decision_reasons_today_utc",{}) if isinstance(daily,dict) else {}
  stale=int(reasons.get("stale_news",0) or 0);decision_total=sum(int(v or 0) for v in reasons.values())
  with LOCK:
   engine_active=bool(S.get("engine_active"))
   xmon=copy.deepcopy(S.get("sources",{}).get("XCriticalMonitor",{}))
   piq=copy.deepcopy(S.get("sources",{}).get("PiQDirect",{}))
  source_health={}
  xkeys=xmon.get("key_accounts") or {}
  for source in CORE_NEWS_SOURCES:
   latest=latest_by_source.get(source,{})
   if source.startswith("XOfficial:"):
    handle=source.split(":",1)[1];runtime=xkeys.get(handle,{})
    transport_ok=bool(runtime.get("ok"))
    latest_age=runtime.get("latest_post_age_seconds")
    rt_verified=bool((runtime.get("delivery") or {}).get("realtime_verified"))
   elif source=="PiQDirect":
    transport_ok=bool(piq.get("ok"));latest_age=latest.get("publication_age_seconds");rt_verified=bool(piq.get("realtime_verified"))
   else:
    with LOCK:runtime=copy.deepcopy(S.get("sources",{}).get(source,{}))
    transport_ok=bool(runtime.get("ok"));latest_age=latest.get("publication_age_seconds");rt_verified=bool(runtime.get("realtime_verified"))
   if not transport_ok:status="ERROR"
   elif latest_age is None:status="REALTIME_UNVERIFIED"
   elif float(latest_age)>NEWS_SILENCE_WARN_SECONDS:status="NO_FRESH_NEWS"
   else:status="ACTIVE"
   source_health[source]={"transport_ok":transport_ok,"status":status,"latest_post_age_seconds":latest_age,
     "realtime_verified":rt_verified,**latest}
  last_fresh_age=round(wall-last_fresh[0],2) if last_fresh else None
  scanners_ok=bool(xmon.get("ok")) and bool(piq.get("ok"))
  status=("STANDBY" if not engine_active else "SCANNER_ERROR" if not scanners_ok else
          "NO_FRESH_NEWS" if last_fresh_age is None or last_fresh_age>NEWS_SILENCE_WARN_SECONDS else "ACTIVE")
  eligible_at=last_eligible.get("recorded_at") if last_eligible else None
  eligible_epoch=publication_epoch(eligible_at) if eligible_at else None
  return {"status":status,"engine_active":engine_active,"scanner_transport_ok":scanners_ok if engine_active else None,
    "realtime_status":"VERIFIED" if bool(xmon.get("realtime_verified")) and bool(piq.get("realtime_verified")) else "UNVERIFIED",
    "fresh_ingests_today":len(fresh_rows),"eligible_today":int(reasons.get("eligible",0) or 0),
    "stale_today":stale,"decision_total_today":decision_total,
    "stale_rate_pct":round(stale/decision_total*100,2) if decision_total else 0.0,
    "last_fresh_received_at":last_fresh[1].get("ts") if last_fresh else None,
    "last_fresh_published_at":last_fresh[1].get("published_at") if last_fresh else None,
    "last_fresh_source":last_fresh[1].get("source") if last_fresh else None,
    "last_fresh_headline":last_fresh[1].get("title") if last_fresh else None,
    "last_fresh_age_seconds":last_fresh_age,
    "last_eligible_at":eligible_at,
    "last_eligible_age_seconds":round(wall-eligible_epoch,2) if eligible_epoch is not None else None,
    "silence_warn_seconds":NEWS_SILENCE_WARN_SECONDS,"sources":source_health}
 except Exception as exc:
  return {"status":"HEALTH_QUERY_ERROR","scanner_transport_ok":False,"error":str(exc)[:180]}


def operations_diagnostics():
 while not SHUTDOWN.is_set():
  try:
   health=health_state();daily=daily_audit_stats();news_health=news_health_snapshot(daily)
   do_news_health_journal=False
   with LOCK:
    S["news_health"]=copy.deepcopy(news_health);S["daily_activity"]=copy.deepcopy(daily)
    last_nh=float(S.get("_last_news_health_journal",0) or 0)
    if S.get("engine_active") and time.time()-last_nh>=300:
     S["_last_news_health_journal"]=time.time();do_news_health_journal=True
   if do_news_health_journal:
    try:journal("news_health_snapshot",None,news_health)
    except Exception:pass
   with LOCK:
    dash=copy.deepcopy(S.get("_dashboard_cache",{}))
    report={"kind":"pandora_diagnostics","time":now(),"engine_active":S["engine_active"],
     "engine_error":S.get("engine_error"),"last_error":S.get("last_error"),"market_count":S.get("market_count"),
     "market_error":S.get("last_market_error"),"positions":len(S["positions"]),
     "trades":S.get("trades"),"news_seen":S.get("news_seen"),
     "sources_ok":sum(bool(x.get("ok")) for x in S["sources"].values()),
     "sources_failed":[k for k,v in S["sources"].items() if not v.get("ok") and not v.get("disabled") and not k.startswith("XFree:") and not k.startswith("XIndex:") and k!="XIndexMonitor" and k not in SEARCH_INDEX_FEEDS and not (k.startswith("TruthDirect:") and k!="TruthDirect:realDonaldTrump")],
     "sources_degraded_noncritical":[k for k,v in S["sources"].items() if not v.get("ok") and (k.startswith("XIndex:") or k=="XIndexMonitor")],
     "news_failures":{k:str(v.get("error") or "")[:160] for k,v in S["sources"].items() if not v.get("ok") and ((k in FEEDS and k not in SEARCH_INDEX_FEEDS and not k.startswith("XIndex:")) or k in RESEARCH_PAGES)},
     "social_channels":{k:{"ok":v.get("ok"),"degraded":v.get("degraded"),"mode":v.get("mode"),"posts":v.get("posts"),"last_check":v.get("last_check"),"error":v.get("error"),"realtime_verified":v.get("realtime_verified"),"latest_post_age_seconds":v.get("latest_post_age_seconds"),"delivery_latency_seconds":v.get("delivery_latency_seconds"),"accounts_ok":v.get("accounts_ok"),"accounts_initialized":v.get("accounts_initialized"),"accounts_total":v.get("accounts_total"),"active_accounts":v.get("active_accounts"),"scan_label":v.get("scan_label"),"key_accounts":v.get("key_accounts"),"disabled_retry_accounts":v.get("disabled_retry_accounts"),"recently_polled_accounts":v.get("recently_polled_accounts"),"target_poll_seconds":v.get("target_poll_seconds"),"backend_accounts":v.get("backend_accounts"),"rate_limited_accounts":v.get("rate_limited_accounts"),"backoff_accounts":v.get("backoff_accounts"),"scan_workers":v.get("scan_workers")} for k,v in S["sources"].items() if k in ("XMonitor","XCriticalMonitor","XFilteredStream","XListMonitor","TruthMonitor","TruthStream","TruthDirect:realDonaldTrump","TruthSocialPublic","PiQDirect")},
     "pump_engine":copy.deepcopy(S["sources"].get("PumpDumpScanner",{})),
     "pump_positions":len(S.get("pump_positions",{})),"pump_trades":S.get("pump_trades"),
     "pump_realized_pnl":S.get("pump_realized_pnl"),"pump_history_baseline":copy.deepcopy(S.get("pump_history_baseline",{})),
     "shared_account_equity":S.get("equity"),
     "whale_liq_engine":copy.deepcopy(S["sources"].get("WhaleLiquidationScanner",{})),
     "whale_liq_positions":len(S.get("whale_positions",{})),"whale_liq_trades":S.get("whale_trades"),"account_model":"UNIFIED_PAPER_ACCOUNT_ALL_STRATEGIES",
     "hype_h1_engine":copy.deepcopy(S["sources"].get("HypeH1LocalSwing",{})),
     "hype_h1_position":bool(S.get("hype_swing_position")),"hype_h1_equity":S.get("hype_swing_equity",HYPE_SWING_STARTING_EQUITY),
     "hype_h1_trades":S.get("hype_swing_trades",0),
     "local_swing_symbols":list(LOCAL_SWING_SYMBOLS),"local_swing_positions":list(S.get("local_swing_positions",{}).keys()),
     "local_swing_watch":copy.deepcopy(S.get("local_swing_watch",{})),
     "sizing_policy":{"margin_fraction":TRADE_MARGIN_FRACTION,"secondary_margin_fraction":PUMP_SECONDARY_MARGIN_FRACTION,"leverage":TRADE_LEVERAGE,"target_open_positions":TARGET_OPEN_POSITIONS,"max_open_positions":MAX_OPEN_POSITIONS,"pump_max_positions":PUMP_MAX_POSITIONS,"auto_topup_enabled":False,"contributed_capital":S.get("contributed_capital",PAPER_RESET),"micro_analysis_threads":MICRO_ANALYSIS_THREADS},
     "universal_profit_protection":{"enabled":True,"strategies":["news","pump_dump","whale_liquidation","local_h1_m15_swing_v5"],"arm_move_pct":PROFIT_PROTECT_ARM_MOVE*100.0,"lock_move_pct":PROFIT_PROTECT_LOCK_MOVE*100.0,"reversal_min_move_pct":PROFIT_PROTECT_REVERSAL_MIN_MOVE*100.0,"r15_adverse_pct":PROFIT_PROTECT_R15*100.0,"r60_adverse_pct":PROFIT_PROTECT_R60*100.0,"flow_threshold":PROFIT_PROTECT_FLOW},
     "entry_rejections":dict(S.get("_entry_rejections",{})),
     "account_pnl_pct":dash.get("account_pnl_pct"),"realized_pnl_pct":dash.get("realized_pnl_pct"),
     "unrealized_pnl":dash.get("unrealized_pnl"),"total_equity":dash.get("total_equity"),
     "decision_learning":copy.deepcopy(S.get("learning_audit",{})),
     "decision_learning_source":copy.deepcopy(S["sources"].get("DecisionLearning",{})),
     "daily_audit":daily,"news_health":copy.deepcopy(S.get("news_health",{})),
     "learning":{"samples":S.get("adaptive",{}).get("samples",0),"generated_at":S.get("adaptive",{}).get("generated_at"),"policy":S.get("adaptive",{}).get("policy")},
     "risk_ready":health["risk_ready"],"latency_metrics":LATENCIES.snapshot(time.time()),
     "trade_stream":copy.deepcopy(S["sources"].get("MarketTradeStream",{})),
     "history_bootstrap":copy.deepcopy(S["sources"].get("MarketHistoryBootstrap",{})),
     "market_metadata":copy.deepcopy(S["sources"].get("MarketMetadata",{})),
     "local12_source":copy.deepcopy(S["sources"].get("Caterpillar 1.0",{}))}
   print(json.dumps(report,ensure_ascii=False,default=str),flush=True)
   with LOCK:s1src=copy.deepcopy(S.get("sources",{}).get("Strategy 1 — Restored Caterpillar",{}))
   print("S1_ONLINE_STATE "+json.dumps({"ok":s1src.get("ok"),"ready":s1src.get("ready"),
    "error":s1src.get("error"),"equity":s1src.get("equity"),"realized_equity":s1src.get("realized_equity"),
    "open_positions":s1src.get("open_positions"),"details":s1src.get("details")},ensure_ascii=False,default=str),flush=True)
  except Exception as e:print("diagnostics_error: "+str(e)[:180],flush=True)
  SHUTDOWN.wait(30)

def local_v10_history(limit=100):
 with pg() as db:
  return [dict(x) for x in db.execute("select closed,symbol,side,pnl,reason from local_v12_trade_history order by closed desc limit %s",(limit,)).fetchall()]

def local_v10_today_pnl():
 with pg() as db:
  row=db.execute("select coalesce(sum(pnl),0) as pnl from local_v12_trade_history where closed::timestamptz >= date_trunc('day',now())").fetchone()
  return float(row["pnl"] or 0)

def local_compare_history(prefix,limit=100):
 table={"local_s1":"local_s1_trade_history","local_s2":"local_s2_trade_history","local_s3":"local_s3_trade_history"}[prefix]
 with pg() as db:
  return [dict(x) for x in db.execute(f"""select opened,closed,symbol,side,entry,exit,pnl,reason,margin,notional,leverage
   from {table} order by closed desc limit %s""",(int(limit),)).fetchall()]

def _bybit_linear_m15_history(symbol,start_ms,end_ms):
 # Public Bybit market data: no API key is required for historical klines.
 pair=str(symbol).upper()+"USDT"
 urls=[
  "https://api.bybit.com/v5/market/kline",
  "https://api.bytick.com/v5/market/kline",
 ]
 last_error=None
 for base in urls:
  try:
   query=urllib.parse.urlencode({"category":"linear","symbol":pair,"interval":"15",
     "start":int(start_ms),"end":int(end_ms),"limit":1000})
   req=urllib.request.Request(base+"?"+query,headers={"User-Agent":"PANDORA-paper/1.0","Accept":"application/json"})
   with urllib.request.urlopen(req,timeout=12) as r:payload=json.load(r)
   if int(payload.get("retCode",0) or 0)!=0:raise RuntimeError("bybit_retCode_"+str(payload.get("retCode")))
   raw=((payload.get("result") or {}).get("list") or [])
   rows=[]
   for x in raw:
    if len(x)<5:continue
    rows.append({"t":int(x[0]),"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),
      "v":float(x[5]) if len(x)>5 else 0.0,"turnover":float(x[6]) if len(x)>6 else 0.0})
   rows.sort(key=lambda z:z["t"])
   # Keep only fully closed candles inside the requested window.
   rows=[x for x in rows if int(start_ms)<=int(x["t"])<int(end_ms)]
   if not rows:raise RuntimeError("empty_bybit_history")
   gaps=[]
   for a,b in zip(rows,rows[1:]):
    if int(b["t"])-int(a["t"])!=900000:gaps.append([int(a["t"]),int(b["t"])])
   return rows,{"source":"bybit_linear_public","pair":pair,"candles":len(rows),"gaps":gaps,
     "continuous":not gaps,"start_ms":int(start_ms),"end_ms":int(end_ms)}
  except Exception as exc:last_error=type(exc).__name__+":"+str(exc)[:120]
 raise RuntimeError(last_error or "bybit_history_failed")

def strategy1_counterfactual_replay_12h():
 # Diagnostic reconstruction. NEAR/GRASS are backfilled from public Bybit M15
 # so missing local checkpoints cannot hide overnight exit/re-entry cycles.
 # Historical executed-flow snapshots were not persisted, therefore this remains
 # a candle-causal reconstruction and is never written into actual PAPER fills.
 try:
  end_ms=(int(time.time()*1000)//900000)*900000
  start_ms=end_ms-12*3600*1000
  with pg() as db:
   positions=[dict(x) for x in db.execute("""select symbol,side,entry,opened,notional
      from local_s1_positions where symbol=any(%s) order by opened""",(list(LOCAL_EXPERIMENT_SYMBOLS),)).fetchall()]
   rows=db.execute("""select symbol,candles from local_candle_checkpoints
      where interval='15m' and symbol=any(%s)""",(list(LOCAL_EXPERIMENT_SYMBOLS),)).fetchall()
  saved={x["symbol"]:x["candles"] for x in rows}
  by_symbol={};coverage={}
  for symbol in LOCAL_EXPERIMENT_SYMBOLS:
   if symbol in ("NEAR","GRASS"):
    try:
     b,meta=_bybit_linear_m15_history(symbol,start_ms,end_ms)
     by_symbol[symbol]=b;coverage[symbol]=meta
     if not meta.get("continuous"):
      coverage[symbol]["usable"]=False
     else:
      coverage[symbol]["usable"]=True
    except Exception as exc:
     by_symbol[symbol]=saved.get(symbol,[]) or []
     coverage[symbol]={"source":"saved_checkpoint_fallback","usable":False,
       "error":type(exc).__name__+":"+str(exc)[:120],"candles":len(by_symbol[symbol])}
   else:
    by_symbol[symbol]=saved.get(symbol,[]) or []
    coverage[symbol]={"source":"saved_checkpoint","usable":True,"candles":len(by_symbol[symbol])}
  events=[];total=0.0;per_symbol={}
  for pos in positions:
   symbol=pos["symbol"];side=int(pos["side"]);original_entry=float(pos["entry"]);entry=original_entry;notional=float(pos["notional"])
   try:opened_epoch=datetime.datetime.fromisoformat(str(pos["opened"]).replace("Z","+00:00")).timestamp()
   except Exception:continue
   raw=by_symbol.get(symbol,[]) or []
   candles=[]
   for r in raw:
    try:
     t=float(r["t"])/1000.0
     if t>opened_epoch and int(r["t"])>=start_ms and int(r["t"])<end_ms:candles.append(r)
    except Exception:continue
   candles=sorted(candles,key=lambda r:int(r["t"]))
   if symbol in ("NEAR","GRASS") and not (coverage.get(symbol) or {}).get("usable"):
    per_symbol[symbol]={"status":"DATA_GAP","side":"LONG" if side>0 else "SHORT",
      "initial_entry":original_entry,"notional":notional,"realized_pnl":0.0,"unrealized_pnl":0.0,
      "cycles":0,"coverage":coverage.get(symbol)}
    continue
   events.append({"symbol":symbol,"type":"ENTRY","cycle":0,"time":str(pos.get("opened") or ""),
     "price":original_entry,"pnl":None,"source":"actual_starting_paper_position"})
   state="IN";hi=entry;lo=entry;prev2=None;prev1=None;cycle=0;last_price=entry
   for cur in candles:
    last_price=float(cur["c"]);close=float(cur["c"]);hi=max(hi,float(cur["h"]));lo=min(lo,float(cur["l"]))
    if prev2 is not None and prev1 is not None:
     if state=="IN":
      turn=(float(prev1["c"])<=float(prev2["c"]) and close>float(prev1["c"])) if side<0 else (float(prev1["c"])>=float(prev2["c"]) and close<float(prev1["c"]))
      favorable=side*(close/entry-1.0)
      if turn and favorable>max(.0013,2*FEE+.0004):
       pnl=notional*(favorable-2*FEE);total+=pnl;cycle+=1
       events.append({"symbol":symbol,"type":"EXIT","cycle":cycle,
        "time":datetime.datetime.fromtimestamp(float(cur["t"])/1000.0,datetime.timezone.utc).isoformat(),
        "price":close,"pnl":round(pnl,4),"source":coverage.get(symbol,{}).get("source")})
       state="WATCH";hi=close;lo=close;prev2=None;prev1=None;continue
     else:
      turn=(float(prev1["c"])>=float(prev2["c"]) and close<float(prev1["c"])) if side<0 else (float(prev1["c"])<=float(prev2["c"]) and close>float(prev1["c"]))
      resume=(hi/close-1.0) if side<0 else (close/lo-1.0)
      if turn and resume>=.0006:
       entry=close
       events.append({"symbol":symbol,"type":"REENTRY","cycle":cycle,
        "time":datetime.datetime.fromtimestamp(float(cur["t"])/1000.0,datetime.timezone.utc).isoformat(),
        "price":close,"pnl":None,"source":coverage.get(symbol,{}).get("source")})
       state="IN";hi=close;lo=close;prev2=None;prev1=None;continue
    prev2=prev1;prev1=cur
   unreal=0.0
   if state=="IN" and last_price>0:
    unreal=notional*(side*(last_price/entry-1.0)-2*FEE)
   sym_realized=sum(float(x.get("pnl",0) or 0) for x in events if x.get("symbol")==symbol and x.get("type")=="EXIT")
   per_symbol[symbol]={"status":"IN_POSITION" if state=="IN" else "WAIT_RESUMPTION","side":"LONG" if side>0 else "SHORT",
     "initial_entry":original_entry,"current_replay_entry":entry,"last_price":last_price,"notional":notional,
     "realized_pnl":round(sym_realized,4),"unrealized_pnl":round(unreal,4),
     "cycles":sum(1 for x in events if x.get("symbol")==symbol and x.get("type")=="EXIT"),
     "coverage":coverage.get(symbol)}
  unrealized_total=sum(float(x.get("unrealized_pnl",0) or 0) for x in per_symbol.values())
  mtm_equity=500.0+total+unrealized_total
  result={"window_hours":12,"window_start_utc":datetime.datetime.fromtimestamp(start_ms/1000,datetime.timezone.utc).isoformat(),
    "window_end_utc":datetime.datetime.fromtimestamp(end_ms/1000,datetime.timezone.utc).isoformat(),
    "basis":"causal_m15_candle_turns_with_bybit_backfill_for_NEAR_GRASS_without_historical_executed_flow",
    "not_executed":True,"coverage":coverage,"events":events,"per_symbol":per_symbol,"realized_pnl":round(total,4),
    "unrealized_pnl":round(unrealized_total,4),"reconstructed_equity":round(500.0+total,4),
    "mtm_equity":round(mtm_equity,4),"mtm_return_pct":round((mtm_equity/500.0-1.0)*100,3),
    "return_on_500_pct":round(total/500.0*100,3)}
  print("S1_REPLAY_12H "+json.dumps({"realized_pnl":result["realized_pnl"],"unrealized_pnl":result["unrealized_pnl"],
    "mtm_equity":result["mtm_equity"],"mtm_return_pct":result["mtm_return_pct"],
    "near":per_symbol.get("NEAR"),"grass":per_symbol.get("GRASS")},ensure_ascii=False,default=str),flush=True)
  return result
 except Exception as exc:
  return {"window_hours":12,"basis":"replay_unavailable","not_executed":True,"events":[],"realized_pnl":0.0,
   "return_on_500_pct":0.0,"error":type(exc).__name__+":"+str(exc)[:120]}

def latest_s1_research_run():
 try:
  with pg() as c:
   run=c.execute("select * from local_s1_research_runs order by created_at desc limit 1").fetchone()
   if not run:return None
   trades=c.execute("""select seq,opened,closed,symbol,side,entry,exit,margin,notional,leverage,pnl,reason,
     mfe_price_move,mae_price_move,equity_after,research_only
     from local_s1_research_trades where run_id=%s order by seq""",(run["run_id"],)).fetchall()
  out=dict(run);out["trades"]=[dict(x) for x in trades];out["status"]="done";out["durable"]=True
  return out
 except Exception as exc:
  return {"status":"error","error":type(exc).__name__+":"+str(exc)[:140]}

def persist_s1_research_result(result):
 if not result:return False
 run_id="s1:%s:%s:%s"%(result.get("start"),result.get("end_exclusive"),result.get("policy"))
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   db.execute("""insert into local_s1_research_runs
    (run_id,start_date,end_exclusive,starting_equity,final_equity,realized_pnl,open_pnl,return_pct,
     max_drawdown_pct,closed_trades,wins,win_rate,profit_factor,policy,research_only,result)
    values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,%s::jsonb)
    on conflict(run_id) do update set created_at=clock_timestamp(),final_equity=excluded.final_equity,
      realized_pnl=excluded.realized_pnl,open_pnl=excluded.open_pnl,return_pct=excluded.return_pct,
      max_drawdown_pct=excluded.max_drawdown_pct,closed_trades=excluded.closed_trades,wins=excluded.wins,
      win_rate=excluded.win_rate,profit_factor=excluded.profit_factor,result=excluded.result""",
    (run_id,result.get("start"),result.get("end_exclusive"),result.get("starting_equity",500),
     result.get("final_equity",500),result.get("realized_pnl",0),result.get("open_pnl",0),result.get("return_pct",0),
     result.get("max_drawdown_pct"),result.get("closed_trades",0),result.get("wins",0),result.get("win_rate"),
     result.get("profit_factor"),result.get("policy"),json.dumps(result,default=str)))
   db.execute("delete from local_s1_research_trades where run_id=%s",(run_id,))
   for seq,x in enumerate(result.get("trades") or [],1):
    db.execute("""insert into local_s1_research_trades
     (run_id,seq,opened,closed,symbol,side,entry,exit,margin,notional,leverage,pnl,reason,
      mfe_price_move,mae_price_move,equity_after,research_only)
     values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true)""",
     (run_id,seq,x.get("opened"),x.get("closed"),x.get("symbol"),x.get("side"),x.get("entry"),x.get("exit"),
      x.get("margin"),x.get("notional"),x.get("leverage"),x.get("pnl"),x.get("reason"),
      x.get("mfe_price_move"),x.get("mae_price_move"),x.get("equity_after")))
 return True

def dashboard_history_loop():
 while not SHUTDOWN.is_set():
  try:
   with LOCK:baseline=copy.deepcopy(S.get("pump_history_baseline",{}))
   stats=strategy_performance(pg,baseline)
   today_rows=list(stats["periods"]["today_utc"].values())
   today={"pnl":round(sum(r["realized_pnl"] for r in today_rows),4),"trades":sum(r["trades"] for r in today_rows),
    "timezone":"UTC","basis":"deduplicated_realized_closed_trades"}
   value={"strategy_performance":stats,"trades":[dict(x) for x in persistent_trades(500)],
          "local_v10_closed_trades":local_v10_history(300),
          "local_s1_closed_trades":local_compare_history("local_s1",300),
          "local_s2_closed_trades":local_compare_history("local_s2",300),
          "local_s3_closed_trades":local_compare_history("local_s3",300),
          "local_s1_replay_12h":None if S1_ONLY_MODE else strategy1_counterfactual_replay_12h(),
          "local_s1_causal_history":latest_s1_research_run() or s1_week_backtest_status(),
          "local_v10_today_realized_pnl":local_v10_today_pnl(),
          "news":[dict(x) for x in persistent_news(20)],
          "features":[dict(x) for x in persistent_features(10)],
          "today_pnl":today,"hype_stats":hype_swing_stats(),
          "updated_at":now(),"error":None}
   with LOCK:S["_dashboard_history"]=value
  except Exception as exc:
   with LOCK:
    previous=S.setdefault("_dashboard_history",{})
    previous["error"]=type(exc).__name__+":"+str(exc)[:120]
  SHUTDOWN.wait(15)

def dashboard_cache_loop():
 while not SHUTDOWN.is_set():
  try:
   value=dashboard()
   rendered=html_dashboard(value)
   with LOCK:
    S["_dashboard_cache"]=value
    S["_dashboard_html_cache"]=rendered
    S["_dashboard_html_cache_at"]=now()
  except Exception as exc:
   import traceback
   traceback.print_exc()
   with LOCK:S["last_error"]="dashboard_cache: "+type(exc).__name__+":"+str(exc)[:150]
  SHUTDOWN.wait(2)

def html_strategy1_only(data):
 esc=lambda x:html.escape(str(x),quote=True)
 p=data.get("strategy1_primary") or {}
 stats=p.get("stats") or {}
 engine=p.get("engine") or {}
 positions=p.get("open_positions") or []
 actual=p.get("closed_trades") or []
 watch=p.get("watch") or {}
 hist=data.get("local_s1_causal_history") or {}
 hr=(hist.get("result") or {}) if hist.get("status")=="done" else {}
 eq=float(p.get("total_equity",p.get("realized_equity",500)) or 500)
 realized=float(p.get("realized_pnl",0) or 0)
 unreal=float(p.get("unrealized_pnl",0) or 0)
 wr=stats.get("win_rate")
 wrtxt="—" if wr is None else "%.1f%%"%(float(wr)*100)
 posmap={x.get("symbol"):x for x in positions}
 details=engine.get("details") or {}
 rows=[]
 for sym in LOCAL_EXPERIMENT_SYMBOLS:
  x=posmap.get(sym) or {};d=details.get(sym) or {};a=d.get("h1_local") or {};w=watch.get(sym) or {}
  side=x.get("side") if x else None
  side_txt="LONG" if side in (1,"LONG") else ("SHORT" if side in (-1,"SHORT") else "—")
  phase=((w.get("context") or {}).get("phase") if w else None) or d.get("last_action") or ("IN_POSITION" if x else "WAIT_ENTRY")
  margin=float(x.get("margin_usd",0) or 0)
  notional=float(x.get("notional_usd",0) or 0)
  pnl=float(x.get("unrealized_pnl",0) or 0)
  roe=(100*pnl/margin) if margin>0 else None
  mark=x.get("mark") if x else None
  mark_valid=isinstance(mark,(int,float)) and float(mark)>0
  rows.append("<tr><td><b>%s</b></td><td><span class='%s'>%s</span></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class='%s'>%s</td><td class='%s'>%s</td></tr>"%(
   esc(sym),"short" if side_txt=="SHORT" else ("pos" if side_txt=="LONG" else "muted"),esc(side_txt),esc(phase),
   esc(a.get("pivot_type") or "—"),esc(a.get("pivot_price") or "—"),
   "$%.2f"%margin if x else "—","$%.2f"%notional if x else "—",
   "%.1fx"%float(x.get("leverage",0) or 0) if x else "—",
   esc(x.get("entry") if x else "—"),
   esc(mark) if mark_valid else ("DATA WAIT" if x else "—"),
   "pos" if pnl>=0 else "neg","$%+.4f"%pnl if x and mark_valid else "DATA WAIT" if x else "—",
   "pos" if pnl>=0 else "neg","%+.2f%%"%roe if roe is not None and mark_valid else "DATA WAIT" if x else "—"))
 actual_rows=[]
 for x in actual:
  pnl=float(x.get("pnl",0) or 0)
  actual_rows.append("<tr><td><b>PAPER CLOSED</b></td><td>%s</td><td>%s</td><td>%s</td><td>$%.2f</td><td>$%.2f</td><td>%sx</td><td>%s</td><td>%s</td><td class='%s'>$%.4f</td><td>%s</td></tr>"%(
   esc(x.get("closed","")),esc(x.get("symbol","")),"LONG" if int(x.get("side",0) or 0)>0 else "SHORT",
   float(x.get("margin",0) or 0),float(x.get("notional",0) or 0),float(x.get("leverage",0) or 0),
   esc(x.get("entry","—")),esc(x.get("exit","—")),"pos" if pnl>=0 else "neg",pnl,esc(x.get("reason",""))))
 paper_total=realized+unreal
 dream_reference=377.36  # historical hindsight MFE opportunity; display-only, never account equity
 dream_total=paper_total+dream_reference
 dream_total_pct=100*dream_total/500.0
 strategy_age="—"
 try:
  with pg() as strategy_db:
   strategy_start=strategy_db.execute("select started_at from local_s1_account_state where id=1").fetchone()
  if strategy_start and strategy_start.get("started_at"):
   start_text=str(strategy_start["started_at"])
   start_dt=datetime.datetime.fromisoformat(start_text.replace("Z","+00:00"))
   if start_dt.tzinfo is None:start_dt=start_dt.replace(tzinfo=datetime.timezone.utc)
   secs=max(0,int((datetime.datetime.now(datetime.timezone.utc)-start_dt).total_seconds()))
   strategy_age="%d д %02d ч %02d мин"%(secs//86400,(secs%86400)//3600,(secs%3600)//60)
 except Exception:pass
 # Per-market totals are derived from actual PAPER closed rows and open marks only.
 token_stats={sym:{"closed":0.0,"open":0.0,"margin":0.0,"trades":0,"wins":0,"active":0} for sym in LOCAL_EXPERIMENT_SYMBOLS}
 for trade in actual:
  sym=str(trade.get("symbol") or "")
  if sym not in token_stats:continue
  item=token_stats[sym];gain=float(trade.get("pnl",0) or 0)
  item["closed"]+=gain;item["margin"]+=float(trade.get("margin",0) or 0)
  item["trades"]+=1;item["wins"]+=int(gain>0)
 for position in positions:
  sym=str(position.get("symbol") or "")
  if sym not in token_stats:continue
  item=token_stats[sym];item["open"]+=float(position.get("unrealized_pnl",0) or 0)
  item["margin"]+=float(position.get("margin_usd",0) or 0);item["active"]+=1
 token_rows=[]
 for sym,item in token_stats.items():
  total=item["closed"]+item["open"]
  margin=item["margin"]
  pct=100*total/margin if margin>0 else None
  win=100*item["wins"]/item["trades"] if item["trades"] else None
  token_rows.append("<tr><td><b>%s</b></td><td>%d</td><td>%d</td><td>%s</td><td class='%s'>$%+.2f</td><td class='%s'>$%+.2f</td><td class='%s'>$%+.2f</td><td class='%s'>%s</td><td>$%.2f</td></tr>"%(
   esc(sym),item["trades"],item["active"],"%.1f%%"%win if win is not None else "—",
   "pos" if item["closed"]>=0 else "neg",item["closed"],"pos" if item["open"]>=0 else "neg",item["open"],
   "pos" if total>=0 else "neg",total,"pos" if total>=0 else "neg",
   "%.2f%%"%pct if pct is not None else "—",margin))
 history_rows=list(actual_rows)

 # New visible history starts here. Original trades remain in persistent audit storage.
 history_epoch=datetime.datetime(2026,10,28,12,26,tzinfo=datetime.timezone.utc)
 fresh=[]
 for trade in actual:
  try:
   ct=datetime.datetime.fromisoformat(str(trade.get("closed") or "").replace("Z","+00:00"))
   if ct.tzinfo is None:ct=ct.replace(tzinfo=datetime.timezone.utc)
   if ct>=history_epoch:fresh.append(trade)
  except Exception:continue
 fresh.sort(key=lambda t:str(t.get("closed") or ""))
 fresh_rows=[]
 for trade in reversed(fresh):
  gain=float(trade.get("pnl") or 0)
  fresh_rows.append("<tr><td>%s</td><td>%s</td><td class='%s'>%s</td><td>$%.2f</td><td>$%.2f</td><td>$%.2f</td><td>$%.2f</td><td class='%s'>$%+.2f</td><td>%s</td></tr>"%(
   esc(trade.get("closed","")),esc(trade.get("symbol","")),"pos" if int(trade.get("side",0) or 0)>0 else "neg",
   "LONG" if int(trade.get("side",0) or 0)>0 else "SHORT",
   float(trade.get("entry",0) or 0),float(trade.get("exit",0) or 0),float(trade.get("margin",0) or 0),
   float(trade.get("notional",0) or 0),"pos" if gain>=0 else "neg",gain,esc(trade.get("reason",""))))
 # Graph shows actual post-reset realized PnL path, shifted by displayed scenario baseline.
 graph_points=[377.36];cumulative=377.36
 for trade in fresh:
  cumulative+=float(trade.get("pnl",0) or 0)
  graph_points.append(cumulative)
 if len(graph_points)==1:graph_points.append(graph_points[0])
 ymin=min(graph_points)-max(1.0,(max(graph_points)-min(graph_points))*.2)
 ymax=max(graph_points)+max(1.0,(max(graph_points)-min(graph_points))*.2)
 chart_coords=" ".join("%.1f,%.1f"%(24+i*852/max(1,len(graph_points)-1),228-184*(v-ymin)/max(.0001,ymax-ymin)) for i,v in enumerate(graph_points))
 chart_svg='<svg viewBox="0 0 900 260" role="img" aria-label="PnL after history reset"><defs><linearGradient id="neon" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#a020f0"/><stop offset=".5" stop-color="#15a9ff"/><stop offset="1" stop-color="#b4ff37"/></linearGradient></defs><path d="M24 228H876 M24 136H876 M24 44H876" fill="none" stroke="#18334a" stroke-dasharray="4 8"/><polyline points="%s" fill="none" stroke="url(#neon)" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/></svg>'%chart_coords
 fresh_by_symbol={sym:{"pnl":0.0,"closed":0} for sym in LOCAL_EXPERIMENT_SYMBOLS}
 for trade in fresh:
  sym=str(trade.get("symbol") or "")
  if sym in fresh_by_symbol:
   fresh_by_symbol[sym]["pnl"]+=float(trade.get("pnl",0) or 0)
   fresh_by_symbol[sym]["closed"]+=1
 token_cards=[]
 for sym in LOCAL_EXPERIMENT_SYMBOLS:
  pos=posmap.get(sym) or {}
  item=fresh_by_symbol[sym]
  unreal_now=float(pos.get("unrealized_pnl",0) or 0) if pos else 0.0
  current=item["pnl"]+unreal_now
  d=details.get(sym) or {}
  status=("OPEN "+str(pos.get("side"))) if pos else ("H1/M15 READY" if d.get("ok") and (d.get("m15") or {}).get("ready") else "WAIT DATA")
  token_cards.append("<article class='tok'><span class='symbol'>%s</span><span class='gain %s'>$%+.2f</span><small>%d новых закрытий · %s</small><small>%s</small></article>"%(esc(sym),"pos" if current>=0 else "neg",current,item["closed"],"позиция открыта" if pos else "нет позиции",esc(status)))
 css="""*{box-sizing:border-box}html{scroll-behavior:smooth}body{background:radial-gradient(ellipse at 10% 0%,#24124b 0,transparent 40%),radial-gradient(ellipse at 95% 3%,#10254c 0,transparent 36%),#040712;color:#e9eaff;font-family:Inter,ui-sans-serif,system-ui,sans-serif;margin:0;padding:25px;max-width:1600px;margin-inline:auto}header{display:flex;align-items:center;justify-content:space-between;border:1px solid #3b286e;border-radius:18px;background:#090f21dd;padding:18px 24px;gap:16px;flex-wrap:wrap}h1{font-size:28px;letter-spacing:2px;margin:0;color:#d7afff;text-shadow:0 0 18px #8e3fff}.logo{color:#b43bff}nav{display:flex;gap:14px;flex-wrap:wrap}a{color:#a6c7ff;text-decoration:none;font-size:13px}a:hover{color:#b7ff32}.shell{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(280px,.8fr);gap:14px;margin:17px 0}.panel{background:linear-gradient(145deg,#0b1227,#090e1e);border:1px solid #283366;border-radius:19px;padding:20px;box-shadow:0 15px 34px #0007;min-width:0}.hero{border-color:#7439da;background:radial-gradient(ellipse at 80% 0,#1c2152,transparent 55%),#090d22}.eyebrow{text-transform:uppercase;font-weight:800;letter-spacing:2px;font-size:12px;color:#c8acff}.total{font:800 clamp(42px,6.5vw,90px)/1.1 ui-monospace,SFMono-Regular,Consolas,monospace;color:#baff48;text-shadow:0 0 28px #7bff3666;margin-top:16px}.percent{color:#baff48;font-weight:750;font-size:clamp(20px,2.5vw,31px)}.sub{color:#8498ba;font-size:12px;line-height:1.7}.pos{color:#aaff49!important}.neg{color:#ff6e9c!important}.caption{margin-top:6px;color:#90a6c5;font-size:12px}.chart svg{width:100%;height:auto;filter:drop-shadow(0 0 8px #30bcff66)}.timeline{display:flex;justify-content:space-between;color:#6c89ad;font-size:11px}h2{font-size:16px;letter-spacing:.5px;margin:0 0 14px;color:#d9e4fc}.summary{display:grid;gap:15px}.mini{border:1px solid #273965;border-radius:12px;background:#0b1730;padding:14px}.mini b{display:block;font:700 20px ui-monospace,monospace;margin-top:8px}.tokens{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:11px;margin-bottom:16px}.tok{min-width:0;background:linear-gradient(140deg,#0e1730,#0a0c1e);border:1px solid #36438a;border-radius:14px;padding:14px;display:flex;flex-direction:column;gap:9px}.tok:nth-child(3n+1){border-color:#6522bf}.tok:nth-child(3n+2){border-color:#116ac9}.tok:nth-child(3n){border-color:#547e20}.tok .symbol{font-weight:800;color:#e0dcff}.tok .gain{font:750 17px ui-monospace,monospace}.tok small{font-size:10px;color:#899bc3}table{width:100%;border-collapse:collapse}td,th{padding:13px 11px;border-bottom:1px solid #1f2b4f;text-align:left;font:12px ui-monospace,Consolas,monospace;white-space:nowrap}th{font-size:10px;text-transform:uppercase;letter-spacing:.7px;color:#f5df53;background:#111832}tr:hover{background:#151b35}.scroll{overflow:auto}.bottom{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px}.chip{display:inline-block;background:#1e204f;color:#c5b6ff;border:1px solid #6235cb;border-radius:50px;padding:6px 10px;font:11px ui-monospace,monospace}.status{color:#baff48}.empty{color:#7a8caa;padding:16px;font-size:13px}footer{color:#7c92af;font-size:11px;margin:22px 0;text-align:center}@media(max-width:1050px){.tokens{grid-template-columns:repeat(4,minmax(0,1fr))}.shell,.bottom{grid-template-columns:1fr}}@media(max-width:600px){body{padding:10px}header{padding:14px}.tokens{grid-template-columns:repeat(2,minmax(0,1fr))}.panel{padding:13px}.total{font-size:42px}.tok .gain{font-size:15px}td,th{font-size:11px;padding:9px}}"""
 page="""<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><meta http-equiv='refresh' content='10'><title>PANDORA · Neon Trading Terminal</title><style>%s</style></head><body>
 <header><h1><span class='logo'>⬡</span> PANDORA</h1><nav><a href='#overview'>Dashboard</a><a href='#positions'>Positions</a><a href='#tokens'>Markets</a><a href='#history'>History</a><a href='#strategy'>Strategy</a></nav><span class='chip status'>● PAPER LIVE</span></header>
 <main><div class='shell' id='overview'><section class='panel hero'><div class='eyebrow'>Total PNL</div><div class='total'>$%+.2f</div><div class='percent'>%+.2f%%</div><div class='caption'>Время работы: %s</div><div class='chart'>%s</div><div class='timeline'><span>Новая история · 28.10.2026</span><span>%d закрытых сделок после начала записи</span></div><div class='sub'>PAPER PnL + исторический потенциал $377.36. Сценарный показатель, не баланс исполненных сделок.</div></section>
 <aside class='panel summary'><h2>Статус терминала</h2><div class='mini'>Режим<b>Strategy 1 · PAPER</b></div><div class='mini'>Открытые позиции<b>%d</b></div><div class='mini'>Контролируемые рынки<b>7</b></div><div class='mini'>Закрыто в новой истории<b>%d</b></div><div class='sub'>Данные позиций поступают из PAPER-движка; сигналы ожидания не считаются открытыми сделками.</div></aside></div>
 <section id='tokens'><h2>Отслеживаемые рынки</h2><div class='tokens'>%s</div></section>
 <section class='panel' id='positions'><h2>Открытые позиции</h2><div class='scroll'><table><thead><tr><th>Token</th><th>Side</th><th>Phase</th><th>H1</th><th>Pivot</th><th>Margin</th><th>Notional</th><th>Lev</th><th>Entry</th><th>Mark</th><th>Open PNL</th><th>ROE</th></tr></thead><tbody>%s</tbody></table></div></section>
 <div class='bottom' style='margin-top:14px'><section class='panel' id='history'><h2>Новая история сделок</h2><div class='sub'>Показываются только PAPER-сделки, закрытые после 28 октября 2026, 12:26 UTC. Старые записи сохранены в аудите.</div><div class='scroll'><table><tr><th>Closed</th><th>Token</th><th>Side</th><th>Entry</th><th>Exit</th><th>Margin</th><th>Notional</th><th>PNL</th><th>Reason</th></tr>%s</table></div></section>
 <section class='panel' id='strategy'><h2>Как работает Strategy 1</h2><p class='sub'>H1 определяет подтверждённый Local High / Local Low и направление. На M15 алгоритм ищет вход по рыночному импульсу, закрывает позицию при ослаблении потока и ждёт возобновления движения для повторного входа. Позиции и цены обновляются по доступным рыночным данным; плечо и маржа отображаются по каждой открытой сделке.</p><span class='chip'>H1 → M15 → EXIT → RE-ENTRY</span></section></div>
 </main><footer>© PANDORA · Paper trading terminal · No live exchange orders</footer></body></html>"""%(css,dream_total,dream_total_pct,esc(strategy_age),chart_svg,len(fresh),len(positions),len(fresh),"".join(token_cards),"".join(rows),"".join(fresh_rows) if fresh_rows else "<tr><td colspan='9' class='empty'>Новая история пуста — записи появятся после закрытия новых PAPER-сделок.</td></tr>")
 return page

def html_dashboard(data):
 if S1_ONLY_MODE:return html_strategy1_only(data)
 esc=lambda x:str(x).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
 age=data.get("account_age_seconds",0);age_txt="%dd %02dh %02dm"%(age//86400,(age%86400)//3600,(age%3600)//60)
 today=data.get("today_pnl") or {}
 today_value=today.get("pnl")
 today_card='<b>TODAY P&L (UTC, REALIZED)<br><span class="%s">%s</span></b>'%("posv" if (today_value or 0)>=0 else "negv",("$ %.4f"%today_value) if today_value is not None else "UNAVAILABLE")
 cards='<div class="grid"><b>MODE<br>%s</b><b>ACCOUNT BALANCE<br>$ %s</b><b>CONTRIBUTED<br>$ %s</b><b>UNREALIZED P&L<br>$ %s</b><b>TOTAL EQUITY<br>$ %s</b><b>ACCOUNT P&L %% (OPEN + REALIZED)<br>%s%%</b><b>TOTAL P&L FROM $100<br><span class="%s">%s%%</span></b><b>USED MARGIN<br>$ %s</b><b>FREE MARGIN<br>$ %s</b><b>MARGIN LOAD<br>%s%%</b><b>SIZE / LEV<br>%s%% / %sx</b><b>ACCOUNT AGE<br>%s</b><b>OPEN POSITIONS<br>%s</b><b>PUMP POSITIONS<br>%s</b><b>WHALE POSITIONS<br>%s</b></div>'%(esc(data["mode"]),data["balance"],data.get("capital_contributed",100),data["unrealized_pnl"],data["total_equity"],data["account_roi_pct"],"posv" if data.get("total_pnl_pct",data["account_roi_pct"])>=0 else "negv",data.get("total_pnl_pct",data["account_roi_pct"]),data.get("used_margin",0),data.get("free_margin",0),data.get("margin_utilization_pct",0),data.get("trade_margin_fraction_pct",0),data.get("trade_leverage",TRADE_LEVERAGE),age_txt,len(data["positions"]),len(data.get("pump_positions",[])),len(data.get("whale_liq_positions",[])))
 cards=cards.replace("</div>",today_card+"</div>",1)
 history_at=data.get("history_updated_at")
 history_error=data.get("history_error")
 cards+='<p class="muted">History updated: %s%s</p>'%(esc(history_at or "loading")," · "+esc(history_error) if history_error else "")

 pos="".join('<tr><td>%s</td><td>%s</td><td>$%s</td><td>$%s</td><td>%sx</td><td>%s</td><td>%s</td><td class="%s">%s%%</td><td class="%s">$%s</td><td>%s</td><td><button onclick="closePos(this.dataset.sym)" data-sym="%s">Close</button></td></tr>'%(esc(x["symbol"]),x["side"],x.get("margin_usd",0),x.get("notional_usd",0),x.get("leverage",LEV),x["entry"],x["mark"],"posv" if x.get("roe_pct",0)>=0 else "negv",x.get("roe_pct",0),"posv" if x["unrealized_pnl"]>=0 else "negv",x["unrealized_pnl"],esc(x.get("headline") or x.get("strategy") or x.get("features",{}).get("engine") or "PAPER_SIGNAL"),esc(x["symbol"])) for x in data["positions"]) or '<tr><td colspan=11>No open positions</td></tr>'
 data=dict(data)
 trs="".join('<tr><td>%s</td><td>%s</td><td>%s</td><td class="%s">$%s</td><td>%s</td></tr>'%(esc(x["closed"]),esc(x["symbol"]),"LONG" if x["side"]>0 else ("SHORT" if x["side"]<0 else "MIXED"),"posv" if float(x["pnl"] or 0)>=0 else "negv",round(float(x["pnl"] or 0),4),esc(x["reason"])) for x in data.get("local_v10_closed_trades",[])) or '<tr><td colspan=5>No Local v10 closed trades yet</td></tr>'
 whale_engine=data.get("whale_liq_engine",{}) or {}
 whale_positions=data.get("whale_liq_positions",[]) or []
 whale_candidates=whale_engine.get("top_candidates",[]) or []
 whale_cards='<div class="grid"><b>PRICE TO VALUE<br>%s</b><b>DANGER ZONE<br>%s</b><b>EVALUATED<br>%s</b><b>QUALIFIED<br>%s</b><b>OPEN WHALE POS<br>%s</b><b>SCAN<br>%ss</b></div>'%("OK" if whale_engine.get("ok") else "ERROR",whale_engine.get("danger_positions",0),whale_engine.get("eligible_candidates",0),whale_engine.get("qualified_candidates",0),len(whale_positions),whale_engine.get("scan_seconds","-"))
 whale_cards+=strategy_cards_html(data.get("strategy_performance"),"whale_liquidation",data.get("whale_liq_unrealized_pnl",0),"Whale Liquidation",data.get("capital_contributed"))
 whale_pos_html="".join('<tr><td>%s</td><td>%s</td><td>$%s</td><td>$%s</td><td>%sx</td><td>%s</td><td>%s</td><td class="%s">%s%%</td><td class="%s">$%s</td><td>%s</td></tr>'%(esc(x["symbol"]),x["side"],x["margin_usd"],x["notional_usd"],x["leverage"],x["entry"],x["mark"],"posv" if x["roe_pct"]>=0 else "negv",x["roe_pct"],"posv" if x["unrealized_pnl"]>=0 else "negv",x["unrealized_pnl"],x.get("score",0)) for x in whale_positions) or '<tr><td colspan=10>No whale liquidation positions</td></tr>'
 whale_candidates_html="".join('<tr><td>%s</td><td>%s</td><td>$%s</td><td>%s%%</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(esc(x.get("symbol","")),("LONG" if int(x.get("side",0))>0 else "SHORT"),round(float(x.get("whale_size_usd",0) or 0),2),round(float(x.get("distance_pct",0) or 0),4),round(float(x.get("ptv_quality_score",x.get("score",0)) or 0),2),esc(x.get("victim_side","")),esc(x.get("liquidation_price",""))) for x in whale_candidates) or '<tr><td colspan=7>No active Price-to-Value candidates now</td></tr>'

 local_positions=data.get("local_swing_positions",[]) or []
 hype_engine=data.get("hype_h1_engine") or {}
 hype_stats=data.get("hype_h1_stats") or {}
 local_symbols=data.get("local_swing_symbols",["HYPE","NEAR"])
 hype_lev_text=" / ".join("%s %sx"%(sym,int(market_max_leverage(sym))) for sym in local_symbols)
 hype_cards='<div class="grid"><b>LOCAL H1 / M15 ENGINE<br>%s</b><b>TOKENS<br>%s</b><b>TOTAL EQUITY<br>$%s</b><b>P&L<br><span class="%s">%s%%</span></b><b>OPEN POSITIONS<br>%s</b><b>TRADES<br>%s</b><b>EXCHANGE MAX LEV<br>%s</b><b>REFERENCE EXPOSURE<br>25%% × 25x</b></div>'%("OK" if hype_engine.get("ok") else "ERROR",esc(" + ".join(local_symbols)),data.get("hype_h1_total_equity",100),"posv" if data.get("hype_h1_pnl_pct",0)>=0 else "negv",data.get("hype_h1_pnl_pct",0),len(local_positions),data.get("hype_h1_trades",0),esc(hype_lev_text))
 hype_cards+=strategy_cards_html(data.get("strategy_performance"),"local",data.get("hype_h1_unrealized_pnl",0),"Local H1/M15",data.get("capital_contributed"))
 hype_pos_html="".join('<tr><td>%s</td><td>%s</td><td>$%s</td><td>$%s</td><td>%sx</td><td>%s</td><td>%s</td><td class="%s">%s%%</td><td class="%s">$%s</td><td>%s / %s</td></tr>'%(esc(x.get("symbol","")),esc(x.get("side","FLAT")),x.get("margin_usd",0),x.get("notional_usd",0),x.get("leverage",market_max_leverage(x.get("symbol",""))),x.get("entry","-"),x.get("mark","-"),"posv" if x.get("roe_pct",0)>=0 else "negv",x.get("roe_pct",0),"posv" if x.get("unrealized_pnl",0)>=0 else "negv",x.get("unrealized_pnl",0),round(float((x.get("features") or {}).get("mae_roe_pct",0) or 0),2),round(float((x.get("features") or {}).get("mfe_roe_pct",0) or 0),2)) for x in local_positions) or '<tr><td colspan=10>No HYPE / NEAR M15 position</td></tr>'
 hype_note='<div class="muted">HYPE + NEAR: H1 local low → LONG; H1 local high → SHORT. Leverage is the current Hyperliquid maxLeverage. Sizing preserves the old reference gross exposure (25%% margin × 25x) by increasing required margin when exchange leverage is lower; if shared free margin is insufficient, notional is capped to the real available margin. M15 manages protective exits, WAIT_PULLBACK → WAIT_RESUMPTION and same-direction re-entry. Samples: %s · win rate: %s · avg MAE: %s%% · avg MFE: %s%%</div>'%(hype_stats.get("samples",0),hype_stats.get("win_rate","-"),hype_stats.get("avg_mae_roe_pct","-"),hype_stats.get("avg_mfe_roe_pct","-"))

 exp_engine=data.get("local_experiment_engine") or {}
 exp_positions=data.get("local_v12_positions") or []
 exp_pos_by_symbol={x.get("symbol"):x for x in exp_positions}
 exp_stats=data.get("local_experiment_stats") or {}
 exp_by_symbol=exp_stats.get("by_symbol") or {}
 exp_day=exp_stats.get("rolling_24h") or {}
 exp_day_wr="—" if exp_day.get("win_rate") is None else str(round(float(exp_day["win_rate"])*100,1))+"%"
 exp_cards='<div class="grid"><b>4-TOKEN LOCAL · ORDER FLOW<br>%s</b><b>START<br>$500</b><b>MTM EQUITY<br>$%s</b><b>P&L<br><span class="%s">%s%%</span></b><b>OPEN POSITIONS<br>%s</b><b>CLOSED TRADES<br>%s</b><b>POSITION<br>20%% MTM EQUITY</b><b>LEVERAGE<br>FIXED 25x PAPER</b></div>'%("OK" if exp_engine.get("ok") else "ERROR",data.get("local_experiment_total_equity",500),"posv" if data.get("local_experiment_pnl_pct",0)>=0 else "negv",data.get("local_experiment_pnl_pct",0),len(exp_positions),data.get("local_experiment_trades",0))
 s1=(data.get("sources") or {}).get("Strategy 1 — Restored Caterpillar",{}) or {}
 s2=(data.get("sources") or {}).get("Strategy 2 — H1 Pivot Swing",{}) or {}
 s1stats=s1.get("stats") or {};s2stats=s2.get("stats") or {}
 comparison=(
   '<h2>LOCAL STRATEGY COMPARISON · FRESH $500 + $500</h2><div class="grid">'
   '<b>STRATEGY 1 · RESTORED CATERPILLAR<br>%s</b><b>S1 EQUITY<br>$%.4f</b><b>S1 OPEN<br>%s</b><b>S1 CLOSED<br>%s</b><b>S1 REALIZED<br>$%.4f</b>'
   '<b>STRATEGY 2 · H1 PIVOT→PIVOT<br>%s</b><b>S2 EQUITY<br>$%.4f</b><b>S2 OPEN<br>%s</b><b>S2 CLOSED<br>%s</b><b>S2 REALIZED<br>$%.4f</b></div>'
  )%(
   "OK" if s1.get("ok") else "WARMUP/ERROR",float(s1.get("equity",500) or 500),len(s1.get("open_positions",[]) or []),int(s1stats.get("trades",0) or 0),float(s1stats.get("realized_pnl",0) or 0),
   "OK" if s2.get("ok") else "WARMUP/ERROR",float(s2.get("equity",500) or 500),len(s2.get("open_positions",[]) or []),int(s2stats.get("trades",0) or 0),float(s2stats.get("realized_pnl",0) or 0))
 comparison+='<div class="muted">S1: H1 direction + M15 weakening/profit floor + pullback/resumption re-entry. S2: LOCAL HIGH → SHORT until confirmed LOCAL LOW; LOCAL LOW → LONG until confirmed LOCAL HIGH. Both: INIT / NEAR / GRASS / HYPE / BTC / ETH / SOL · 20%% margin · 25x paper reference · compounding.</div>'
 with LOCK:
  s1_positions=copy.deepcopy(S.get("local_s1_positions",{}))
  s2_positions=copy.deepcopy(S.get("local_s2_positions",{}))
 comparison_rows=[]
 for label,book in (("S1",s1_positions),("S2",s2_positions)):
  for sym in LOCAL_EXPERIMENT_SYMBOLS:
   p=book.get(sym) or {}
   raw_side=int(p.get("side",0) or 0)
   side_txt="LONG" if raw_side==1 else ("SHORT" if raw_side==-1 else "—")
   notional=float(p.get("notional",0) or 0)
   margin=float(p.get("margin",0) or 0)
   lev=float(p.get("leverage",0) or 0)
   entry=float(p.get("entry",0) or 0)
   comparison_rows.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>20%% equity</td><td>25x</td><td>$%.2f</td><td>$%.2f</td><td>%sx</td><td>%s</td></tr>'%(
    label,esc(sym),esc(side_txt),notional,margin,round(lev,2) if lev else "—",round(entry,8) if entry else "—"))
 comparison+='<h3>OPEN POSITIONS · FIXED RULE: 20% EQUITY × 25x</h3><table><tr><th>Strategy</th><th>Token</th><th>Side</th><th>Margin Rule</th><th>Target Lev</th><th>Position $</th><th>Margin $</th><th>Actual Lev</th><th>Entry</th></tr>'+''.join(comparison_rows)+'</table>'
 s1_closed=(data.get("local_s1_closed_trades") or [])[:50]
 s1_closed_rows="".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class="%s">$%.4f</td><td>%s</td></tr>'%(
   esc(x.get("closed","")),esc(x.get("symbol","")),"LONG" if int(x.get("side",0) or 0)>0 else "SHORT",
   esc(round(float(x.get("entry",0) or 0),8)),esc(round(float(x.get("exit",0) or 0),8)),
   "posv" if float(x.get("pnl",0) or 0)>=0 else "negv",float(x.get("pnl",0) or 0),esc(x.get("reason","")))
   for x in s1_closed)
 comparison+='<h3>STRATEGY 1 · ACTUAL CLOSED TRADES</h3><div class="muted">Executed PAPER history only. Counterfactual/replay trades are never mixed into these totals.</div><table><tr><th>Closed</th><th>Token</th><th>Side</th><th>Entry</th><th>Exit</th><th>PnL</th><th>Reason</th></tr>'+(
   s1_closed_rows or '<tr><td colspan=7>No actual Strategy 1 closes recorded yet</td></tr>')+'</table>'
 replay=data.get("local_s1_replay_12h") or {}
 replay_events=replay.get("events") or []
 replay_symbol_rows="".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>$%.4f</td><td>$%.4f</td><td>%s</td></tr>'%(
   esc(sym),esc(x.get("side","")),esc(x.get("status","")),float(x.get("realized_pnl",0) or 0),
   float(x.get("unrealized_pnl",0) or 0),int(x.get("cycles",0) or 0))
   for sym,x in (replay.get("per_symbol") or {}).items())
 replay_rows="".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(
   esc(x.get("time","")),esc(x.get("symbol","")),esc(x.get("type","")),esc(x.get("price","")),
   ("$%.4f"%float(x.get("pnl",0) or 0)) if x.get("type")=="EXIT" else "—") for x in replay_events[:50])
 comparison+='<h3>STRATEGY 1 · 12H COUNTERFACTUAL REPLAY · NOT EXECUTED</h3><div class="grid"><b>REPLAY REALIZED P&L<br>$%.4f</b><b>REALIZED-EQUITY EQUIV.<br>$%.4f</b><b>OPEN P&L<br>$%.4f</b><b>MTM EQUITY<br>$%.4f</b><b>MTM RETURN<br>%.3f%%</b><b>EVENTS<br>%s</b></div><div class="muted">Causal M15 candle-turn replay only. Historical executed-flow snapshots were not persisted, so this is diagnostic, not actual PAPER history.</div><table><tr><th>Token</th><th>Side</th><th>End state</th><th>Realized PnL</th><th>Open PnL</th><th>Cycles</th></tr>%s</table><table><tr><th>Time UTC</th><th>Token</th><th>Event</th><th>Price</th><th>PnL</th></tr>%s</table>'%(
   float(replay.get("realized_pnl",0) or 0),float(replay.get("reconstructed_equity",500) or 500),
   float(replay.get("unrealized_pnl",0) or 0),float(replay.get("mtm_equity",500) or 500),
   float(replay.get("mtm_return_pct",0) or 0),len(replay_events),
   replay_symbol_rows or '<tr><td colspan=6>No reconstructed symbol states</td></tr>',
   replay_rows or '<tr><td colspan=5>No replay event in saved candle window</td></tr>')
 exp_cards=comparison+exp_cards
 exp_realized=float(data.get("local_experiment_realized_pnl",0) or 0)
 exp_open=float(data.get("local_experiment_unrealized_pnl",0) or 0)
 exp_total_pnl=exp_realized+exp_open
 exp_today=float(data.get("local_v10_today_realized_pnl",0) or 0)
 exp_today_open=exp_today+exp_open
 exp_cards+='<div class="grid"><b>V10 REALIZED P&L<br><span class="%s">$%.4f</span></b><b>V10 OPEN P&L<br><span class="%s">$%.4f</span></b><b>V10 TOTAL P&L<br><span class="%s">$%.4f</span></b><b>V10 TOTAL RETURN<br><span class="%s">%.3f%%</span></b><b>TODAY REALIZED P&L (UTC)<br><span class="%s">$%.4f</span></b><b>TODAY INCLUDING OPEN P&L<br><span class="%s">$%.4f</span></b><b>TODAY INCLUDING OPEN RETURN<br><span class="%s">%.3f%%</span></b></div>'%("posv" if exp_realized>=0 else "negv",exp_realized,"posv" if exp_open>=0 else "negv",exp_open,"posv" if exp_total_pnl>=0 else "negv",exp_total_pnl,"posv" if exp_total_pnl>=0 else "negv",exp_total_pnl/500*100,"posv" if exp_today>=0 else "negv",exp_today,"posv" if exp_today_open>=0 else "negv",exp_today_open,"posv" if exp_today_open>=0 else "negv",exp_today_open/500*100)
 exp_cards+='<div class="grid"><b>LOCAL LAST 24H<br>ROLLING</b><b>REALIZED P&L<br>$%s</b><b>TRADES<br>%s</b><b>WIN RATE<br>%s</b></div>'%(round(float(exp_day.get("realized_pnl",0) or 0),4),exp_day.get("trades",0),esc(exp_day_wr))
 direction_rows=[]
 for sym in data.get("local_experiment_symbols",[]):
  detail=(exp_engine.get("details") or {}).get(sym,{})
  anchor=detail.get("h1_local") or {}
  side=int(anchor.get("entry_side") or 0)
  signal_time=anchor.get("signal_candle_time")
  confirmed_at=(datetime.datetime.fromtimestamp((float(signal_time)+3600000)/1000,datetime.timezone(datetime.timedelta(hours=4))).strftime("%d.%m %H:%M") if signal_time else "—")
  allowed="WAIT CONFIRMATION" if anchor.get("entry_blocked") else ("LONG ONLY" if side==1 else ("SHORT ONLY" if side==-1 else "WAIT H1 DATA"))
  current_action=detail.get("last_action") or detail.get("error") or detail.get("caterpillar_phase") or "WAIT DATA"
  selection=detail.get("candidate_selection") or {}
  if selection.get("rank"):
   current_action+=" · rank %s · M15 %s · aligned flow %.2f"%(selection["rank"],selection.get("recovery_score","—"),float(selection.get("aligned_flow",0)))
  direction_rows.append('<tr><td>%s</td><td>%s @ %s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(
   esc(sym),esc(anchor.get("pivot_type") or "—"),esc(anchor.get("pivot_price") or "—"),esc(confirmed_at),esc(allowed),
   esc(anchor.get("pending_pivot_type") or "—"),esc(current_action)))
 direction_table='<h3>H1 direction and execution status · confirmation time Samara UTC+4</h3><table><tr><th>Token</th><th>Confirmed H1 anchor</th><th>Confirmed at</th><th>Allowed entry</th><th>Pending opposite extreme</th><th>Current action</th></tr>'+"".join(direction_rows)+'</table>'
 exp_rows=[]
 for sym in data.get("local_experiment_symbols",[]):
  d=(exp_engine.get("details") or {}).get(sym,{})
  p=exp_pos_by_symbol.get(sym) or {}
  st=exp_by_symbol.get(sym) or {}
  wr=("-" if st.get("win_rate") is None else round(float(st.get("win_rate"))*100,1))
  fill=(p.get("features") or {}).get("exposure_fill_ratio")
  fill_txt=("-" if fill is None else round(float(fill)*100,1))
  phase=d.get("caterpillar_phase","WAIT_ENTRY")
  entry_kind=(p.get("features") or {}).get("entry_kind","-")
  raw_side_value=(p.get("side",0) if p else 0)
  raw_side=(1 if str(raw_side_value).upper()=="LONG" else (-1 if str(raw_side_value).upper()=="SHORT" else int(raw_side_value or 0)))
  side_txt="LONG" if raw_side==1 else ("SHORT" if raw_side==-1 else "—")
  side_class="posv" if raw_side==1 else ("negv" if raw_side==-1 else "")
  entry_txt=("-" if not p else round(float(p.get("entry",0) or 0),8))
  mark_txt=("-" if not p else round(float(p.get("mark",0) or 0),8))
  roe_txt=("-" if not p else round(float(p.get("roe_pct",0) or 0),2))
  exp_rows.append('<tr><td>%s</td><td class="%s">%s</td><td>%sx</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s%%</td><td>$%s</td><td>$%s</td><td>$%s</td><td>$%s</td><td>%s%%</td><td class="%s">$%s</td><td>%s / %s%%</td></tr>'%(
   esc(sym),side_class,esc(side_txt),25,esc(phase),esc(entry_kind),entry_txt,mark_txt,roe_txt,round(float(d.get("target_notional",0) or 0),2),
   round(float(d.get("required_margin_for_full_target",0) or 0),2),round(float(p.get("margin_usd",0) or 0),2),
   round(float(p.get("notional_usd",0) or 0),2),fill_txt,
   "posv" if float(p.get("unrealized_pnl",0) or 0)>=0 else "negv",round(float(p.get("unrealized_pnl",0) or 0),4),
   st.get("trades",0),wr))
 exp_rows_html="".join(exp_rows) or '<tr><td colspan=10>No experiment data yet</td></tr>'
 exp_note=direction_table+'<div class="muted">Four-token PAPER Local: INIT, NEAR, GRASS, HYPE. Start $500. Every new position uses up to 20%% of current mark-to-market equity at fixed 25x PAPER leverage. Only INIT, NEAR, GRASS and HYPE are traded. Open positions are never retroactively resized merely because equity changes. H1 owns direction. Fresh executed buys versus sells over one minute trigger exit and same-direction re-entry; five-minute flow is context. No M15 candle score or candle-close wait is used.</div>'
 pump_positions_data=data.get("pump_positions",[]) or []
 pump_total=float(data.get("pump_total_pnl",0) or 0)
 pump_cards='<div class="grid"><b>PUMP/DUMP ENGINE<br>%s</b><b>OPEN POSITIONS<br>%s</b><b>CLOSED TRADES<br>%s</b><b>REALIZED P&L<br><span class="%s">$%s</span></b><b>UNREALIZED P&L<br><span class="%s">$%s</span></b><b>TOTAL P&L<br><span class="%s">$%s</span></b></div>'%(
  "OK" if (data.get("sources",{}).get("PumpDumpScanner",{}) or {}).get("ok") else "ERROR",len(pump_positions_data),
  data.get("pump_trades",0),"posv" if float(data.get("pump_realized_pnl",0) or 0)>=0 else "negv",data.get("pump_realized_pnl",0),
  "posv" if float(data.get("pump_unrealized_pnl",0) or 0)>=0 else "negv",data.get("pump_unrealized_pnl",0),
  "posv" if pump_total>=0 else "negv",pump_total)
 pump_cards+=strategy_cards_html(data.get("strategy_performance"),"pump_dump",data.get("pump_unrealized_pnl",0),"Pump/Dump",data.get("capital_contributed"))
 pump_pos="".join('<tr><td>%s</td><td>%s</td><td>$%s</td><td>$%s</td><td>%sx</td><td>%s</td><td>%s</td><td class="%s">%s%%</td><td class="%s">$%s</td><td>%s</td></tr>'%(esc(x["symbol"]),x["side"],x["margin_usd"],x["notional_usd"],x["leverage"],x["entry"],x["mark"],"posv" if x["roe_pct"]>=0 else "negv",x["roe_pct"],"posv" if x["unrealized_pnl"]>=0 else "negv",x["unrealized_pnl"],x.get("score",0)) for x in pump_positions_data) or '<tr><td colspan=10>No pump/dump positions</td></tr>'
 src="".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(esc(k),(esc(v.get("scan_label")) if k=="XMonitor" and v.get("scan_label") else ("OK" if v.get("ok") else "ERROR")),esc(v.get("last_check","")),esc(v.get("error",""))) for k,v in data["sources"].items())

 nh=data.get("news_health",{}) or {}
 nh_status=nh.get("status","UNKNOWN")
 nh_class="posv" if nh_status=="ACTIVE" else ("negv" if nh_status in ("SCANNER_ERROR","HEALTH_QUERY_ERROR") else "warnv")
 last_fresh_age=nh.get("last_fresh_age_seconds")
 last_fresh_txt=("-" if last_fresh_age is None else ("%ss"%round(float(last_fresh_age),1)))
 news_health_cards='<div class="grid"><b>NEWS SCANNER<br><span class="%s">%s</span></b><b>REALTIME<br><span class="%s">%s</span></b><b>FRESH INGESTS TODAY<br>%s</b><b>ELIGIBLE TODAY<br>%s</b><b>STALE TODAY<br>%s (%s%%)</b><b>LAST FRESH AGE<br>%s</b></div>'%(nh_class,esc(nh_status),"posv" if nh.get("realtime_status")=="VERIFIED" else "warnv",esc(nh.get("realtime_status","UNVERIFIED")),nh.get("fresh_ingests_today",0),nh.get("eligible_today",0),nh.get("stale_today",0),nh.get("stale_rate_pct",0),last_fresh_txt)
 nh_sources=nh.get("sources",{}) or {}
 news_health_rows="".join('<tr><td>%s</td><td class="%s">%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(esc(k),"posv" if v.get("status")=="ACTIVE" else ("negv" if v.get("status")=="ERROR" else "warnv"),esc(v.get("status","-")),esc(v.get("latest_post_age_seconds","-")),esc(v.get("ingest_lag_seconds","-")),esc(v.get("realtime_verified",False))) for k,v in nh_sources.items()) or '<tr><td colspan=5>No news health data yet</td></tr>'
 news_health_note='<div class="muted">Last fresh: %s · %s · %s</div>'%(esc(nh.get("last_fresh_received_at") or "-"),esc(nh.get("last_fresh_source") or "-"),esc(nh.get("last_fresh_headline") or "-"))
 news="".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(esc(x["ts"]),esc(x["source"]),esc(x["symbol"]),esc(x["signal"]),esc(x["title"])) for x in data["news"][:12])
 s1p=data.get("strategy1_primary") or {}
 s1bench=data.get("strategy1_historical_benchmark") or {}
 s1start=float(s1p.get("starting_equity",500) or 500)
 s1real=float(s1p.get("realized_pnl",0) or 0)
 s1unreal=float(s1p.get("unrealized_pnl",0) or 0)
 s1total=float(s1p.get("total_equity",s1start+s1real+s1unreal) or 0)
 s1closed=s1p.get("closed_trades") or []
 s1open=s1p.get("open_positions") or []
 s1watch=s1p.get("watch") or {}
 s1stats=s1p.get("stats") or {}
 s1wins=sum(1 for x in s1closed if float(x.get("pnl",0) or 0)>0)
 s1wr=(s1wins/len(s1closed)*100.0) if s1closed else 0.0
 s1target=float(s1bench.get("mfe_upper_equity",877.36) or 877.36)
 s1opp=max(.000001,s1target-s1start)
 s1capture=max(0.0,min(100.0,(s1total-s1start)/s1opp*100.0))
 s1gap=s1target-s1total
 s1_engine=s1p.get("engine") or {}
 s1status="ACTIVE" if s1_engine.get("ok") else ("WARMUP" if s1_engine.get("warmup") else "ATTENTION")
 s1pos_rows="".join('<tr><td>%s</td><td>%s</td><td>$%.2f</td><td>$%.2f</td><td>%sx</td><td>%s</td><td>%s</td><td class="%s">%.3f%%</td><td class="%s">$%.4f</td><td>%s</td></tr>'%(
   esc(x.get("symbol","")),esc(x.get("side","FLAT")),float(x.get("margin_usd",0) or 0),float(x.get("notional_usd",0) or 0),
   float(x.get("leverage",0) or 0),esc(x.get("entry","—")),esc(x.get("mark","—")),
   "posv" if float(x.get("roe_pct",0) or 0)>=0 else "negv",float(x.get("roe_pct",0) or 0),
   "posv" if float(x.get("unrealized_pnl",0) or 0)>=0 else "negv",float(x.get("unrealized_pnl",0) or 0),
   esc(x.get("opened","—"))) for x in s1open) or '<tr><td colspan=10>No Strategy 1 positions open right now</td></tr>'
 s1life_rows="".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>$%.2f</td><td>$%.2f</td><td>%sx</td><td>%s</td><td>%s</td><td class="%s">$%.4f</td><td>%s</td></tr>'%(
   esc(x.get("opened","")),esc(x.get("closed","")),esc(x.get("symbol","")),
   "LONG" if int(x.get("side",0) or 0)>0 else "SHORT",esc(x.get("entry","—")),
   float(x.get("margin",0) or 0),float(x.get("notional",0) or 0),float(x.get("leverage",0) or 0),
   esc(x.get("exit","—")),esc(x.get("reason","")),
   "posv" if float(x.get("pnl",0) or 0)>=0 else "negv",float(x.get("pnl",0) or 0),esc("CLOSED"))
   for x in s1closed) or '<tr><td colspan=12>No closed Strategy 1 trades yet</td></tr>'
 s1watch_rows="".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(
   esc(sym),"LONG" if int((w or {}).get("side",0) or 0)>0 else "SHORT",
   esc(((w or {}).get("context") or {}).get("phase","WATCH")),
   esc((w or {}).get("exit_at","—"))) for sym,w in s1watch.items()) or '<tr><td colspan=4>No re-entry watches</td></tr>'
 s1_primary_html='<section class="s1hero"><h2>STRATEGY 1 · PRIMARY · H1 → M15 CATERPILLAR</h2><div class="grid"><b>STATUS<br><span class="%s">%s</span></b><b>START<br>$%.2f</b><b>REALIZED EQUITY<br><span class="%s">$%.4f</span></b><b>REALIZED P&L<br><span class="%s">$%+.4f</span></b><b>OPEN P&L<br><span class="%s">$%+.4f</span></b><b>TOTAL EQUITY<br><span class="%s">$%.4f</span></b><b>CLOSED TRADES<br>%s</b><b>WIN RATE<br>%.1f%%</b><b>OPEN POSITIONS<br>%s</b><b>RE-ENTRY WATCH<br>%s</b><b>BENCHMARK<br>$%.2f</b><b>CAPTURE TO BENCHMARK<br>%.1f%%</b><b>GAP TO BENCHMARK<br>$%+.2f</b></div><div class="progress"><span style="width:%.2f%%"></span></div><div class="muted">Actual PAPER state is authoritative. Benchmark $%.2f is the historical MFE opportunity ceiling, not executed PnL. Goal: improve causal capture without lookahead.</div><h3>STRATEGY 1 · OPEN NOW</h3><div class="scroll"><table><tr><th>Token</th><th>Side</th><th>Margin $</th><th>Position $</th><th>Lev</th><th>Entry</th><th>Mark</th><th>ROE</th><th>Open P&L</th><th>Opened</th></tr>%s</table></div><h3>STRATEGY 1 · ACTUAL ORDER LIFECYCLE</h3><div class="scroll"><table><tr><th>Opened</th><th>Closed</th><th>Token</th><th>Side</th><th>Entry</th><th>Margin $</th><th>Position $</th><th>Lev</th><th>Exit</th><th>Exit reason</th><th>PnL</th><th>Status</th></tr>%s</table></div><h3>STRATEGY 1 · RE-ENTRY WATCH</h3><div class="scroll"><table><tr><th>Token</th><th>Side</th><th>Phase</th><th>Exited at</th></tr>%s</table></div></section>'%(
   "posv" if s1status=="ACTIVE" else "warnv",esc(s1status),s1start,
   "posv" if s1total>=s1start else "negv",s1p.get("realized_equity",s1start),
   "posv" if s1real>=0 else "negv",s1real,
   "posv" if s1unreal>=0 else "negv",s1unreal,
   "posv" if s1total>=s1start else "negv",s1total,
   len(s1closed),s1wr,len(s1open),len(s1watch),s1target,s1capture,s1gap,s1capture,s1target,
   s1pos_rows,s1life_rows,s1watch_rows)
 all_open_rows=[]
 for x in data.get("positions",[]) or []:
  all_open_rows.append((x.get("strategy","GENERAL"),x))
 for key in ("local_s1","local_s2","local_s3"):
  block=(data.get("comparison_strategies") or {}).get(key,{}) or {}
  label=block.get("label") or key.upper()
  for x in block.get("positions",[]) or []:
   all_open_rows.append((label,x))
 def _open_row(label,x):
  pnl=float(x.get("unrealized_pnl",0) or 0);roe=float(x.get("roe_pct",0) or 0)
  return '<tr><td>%s</td><td>%s</td><td>%s</td><td>$%.2f</td><td>$%.2f</td><td>%sx</td><td>%s</td><td>%s</td><td class="%s">%.3f%%</td><td class="%s">$%.4f</td><td>%s</td></tr>'%(
   esc(label),esc(x.get("symbol","")),esc(x.get("side","FLAT")),float(x.get("margin_usd",0) or 0),
   float(x.get("notional_usd",0) or 0),float(x.get("leverage",0) or 0),esc(x.get("entry","—")),
   esc(x.get("mark","—")),"posv" if roe>=0 else "negv",roe,"posv" if pnl>=0 else "negv",pnl,
   esc(x.get("opened","—")))
 all_open_html="".join(_open_row(label,x) for label,x in all_open_rows) or '<tr><td colspan=11>No open positions now</td></tr>'

 all_closed=[]
 for x in data.get("trades",[]) or []:
  all_closed.append({"closed":x.get("closed"),"strategy":x.get("strategy") or x.get("headline") or "GENERAL",
    "symbol":x.get("symbol"),"side":x.get("side"),"entry":x.get("entry"),"exit":x.get("exit"),
    "pnl":x.get("pnl"),"reason":x.get("reason")})
 for key in ("local_s1","local_s2","local_s3"):
  label=((data.get("comparison_strategies") or {}).get(key,{}) or {}).get("label") or key.upper()
  for x in data.get(key+"_closed_trades",[]) or []:
   all_closed.append({"closed":x.get("closed"),"strategy":label,"symbol":x.get("symbol"),"side":x.get("side"),
    "entry":x.get("entry"),"exit":x.get("exit"),"pnl":x.get("pnl"),"reason":x.get("reason")})
 all_closed.sort(key=lambda x:str(x.get("closed") or ""),reverse=True)
 def _closed_row(x):
  side=x.get("side")
  try:side_txt="LONG" if int(side or 0)>0 else ("SHORT" if int(side or 0)<0 else "MIXED")
  except Exception:side_txt=esc(side or "—")
  pnl=float(x.get("pnl",0) or 0)
  return '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class="%s">$%.4f</td><td>%s</td></tr>'%(
   esc(x.get("closed","")),esc(x.get("strategy","")),esc(x.get("symbol","")),esc(side_txt),
   esc(x.get("entry","—")),esc(x.get("exit","—")),"posv" if pnl>=0 else "negv",pnl,esc(x.get("reason","")))
 all_closed_html="".join(_closed_row(x) for x in all_closed[:500]) or '<tr><td colspan=8>No closed trades recorded</td></tr>'

 bench=data.get("strategy1_historical_benchmark") or {}
 bench_html='<div class="benchmark"><b>%s</b><div class="benchnum">$%.2f → $%.2f</div><div class="posv">Opportunity +$%.2f / +%.2f%%</div><div class="muted">%s</div></div>'%(
  esc(bench.get("label","HISTORICAL BENCHMARK")),float(bench.get("starting_equity",500) or 500),
  float(bench.get("mfe_upper_equity",0) or 0),float(bench.get("mfe_opportunity_pnl",0) or 0),
  (float(bench.get("mfe_upper_equity",500) or 500)/max(1,float(bench.get("starting_equity",500) or 500))-1)*100,
  esc(bench.get("basis","")))
 s1block=(data.get("comparison_strategies") or {}).get("local_s1",{}) or {}
 s1engine=s1block.get("engine") or {}
 s1stats=s1block.get("stats") or {}
 s1positions=s1block.get("positions") or []
 s1details=s1engine.get("details") or {}
 s1watch=s1block.get("watch") or {}
 s1wr="—" if s1stats.get("win_rate") is None else ("%.1f%%"%(float(s1stats.get("win_rate") or 0)*100.0))
 s1_realized=float(s1stats.get("realized_pnl",0) or 0)
 s1_eq=float(s1block.get("total_equity",500) or 500)
 s1_open=float(s1block.get("unrealized_pnl",0) or 0)
 s1_primary_rows=[]
 s1posmap={x.get("symbol"):x for x in s1positions}
 for sym in LOCAL_EXPERIMENT_SYMBOLS:
  p=s1posmap.get(sym) or {};d=s1details.get(sym) or {};a=d.get("h1_local") or {};w=s1watch.get(sym) or {}
  raw_side=p.get("side")
  side=raw_side or ("SHORT" if int((w or {}).get("side") or 0)<0 else ("LONG" if int((w or {}).get("side") or 0)>0 else "FLAT"))
  phase=(w.get("context") or {}).get("phase") if w else None
  phase=phase or ("IN_POSITION" if p else d.get("last_action") or "WAIT_ENTRY")
  pnl=float(p.get("unrealized_pnl",0) or 0)
  s1_primary_rows.append('<tr><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s @ %s</td><td>$%.2f</td><td>$%.2f</td><td>%s</td><td>%s</td><td class="%s">$%.4f</td><td>%s</td></tr>'%(
   esc(sym),esc(side),esc(phase),esc(a.get("pivot_type") or "—"),esc(a.get("pivot_price") or "—"),
   float(p.get("margin_usd",0) or 0),float(p.get("notional_usd",0) or 0),esc(p.get("entry","—")),
   esc(p.get("mark","—")),"posv" if pnl>=0 else "negv",pnl,esc(d.get("last_action") or phase)))
 s1_actual_history=data.get("local_s1_closed_trades") or []
 s1_history_rows="".join('<tr><td>%s</td><td><b>%s</b></td><td>%s</td><td>$%.2f</td><td>$%.2f</td><td>%sx</td><td>%s</td><td>%s</td><td class="%s">$%.4f</td><td>%s</td></tr>'%(
   esc(x.get("closed","")),esc(x.get("symbol","")),"LONG" if int(x.get("side",0) or 0)>0 else "SHORT",
   float(x.get("margin",0) or 0),float(x.get("notional",0) or 0),float(x.get("leverage",0) or 0),
   esc(x.get("entry","—")),esc(x.get("exit","—")),"posv" if float(x.get("pnl",0) or 0)>=0 else "negv",
   float(x.get("pnl",0) or 0),esc(x.get("reason",""))) for x in s1_actual_history) or '<tr><td colspan=10>No actual Strategy 1 closes recorded</td></tr>'
 s1_primary_html=(
  '<section id="strategy1-primary" class="primary">'
  '<h2>STRATEGY 1 · MAIN · H1 LOCAL → M15 FLOW → EXIT / PULLBACK / RE-ENTRY</h2>'
  '<div class="grid"><b>STATUS<br><span class="%s">%s</span></b><b>START<br>$500.00</b>'
  '<b>REALIZED EQUITY<br>$%.4f</b><b>REALIZED P&L<br><span class="%s">$%.4f</span></b>'
  '<b>OPEN P&L<br><span class="%s">$%.4f</span></b><b>MTM EQUITY<br>$%.4f</b>'
  '<b>CLOSED TRADES<br>%s</b><b>WIN RATE<br>%s</b><b>OPEN POSITIONS<br>%s</b>'
  '<b>RE-ENTRY WATCH<br>%s</b><b>SIZE<br>20%% CURRENT EQUITY</b><b>REFERENCE LEVERAGE<br>25x PAPER</b></div>'
  '<div class="muted">ACTUAL PAPER state from durable Neon tables. H1 controls direction; M15 + executed flow control entry, weakening exit, pullback and same-direction re-entry. No replay/MFE values are mixed into actual P&L.</div>'
  '<h3>LIVE STATE · INIT / NEAR / GRASS / HYPE / BTC / ETH / SOL</h3><div class="scroll"><table><tr><th>Token</th><th>Side</th><th>Phase</th><th>H1 Local</th><th>Margin $</th><th>Position $</th><th>Entry</th><th>Mark</th><th>Open P&L</th><th>Action</th></tr>%s</table></div>'
  '<h3>ACTUAL STRATEGY 1 TRADE HISTORY</h3><div class="scroll"><table><tr><th>Closed</th><th>Token</th><th>Side</th><th>Margin $</th><th>Position $</th><th>Lev</th><th>Entry</th><th>Exit</th><th>PnL</th><th>Reason</th></tr>%s</table></div>'
  '</section>'
 )%(
   "posv" if s1engine.get("ok") else "warnv","ACTIVE" if s1engine.get("ok") else "WARMUP / PARTIAL DATA",
   float(s1block.get("realized_equity",500) or 500),"posv" if s1_realized>=0 else "negv",s1_realized,
   "posv" if s1_open>=0 else "negv",s1_open,s1_eq,int(s1stats.get("trades",0) or 0),esc(s1wr),
   len(s1positions),len(s1watch),"".join(s1_primary_rows),s1_history_rows)
 comparison_html=""
 for key,title in (("local_s2","STRATEGY 2 — H1 PIVOT-TO-PIVOT"),("local_s3","STRATEGY 3 — LOCAL12 V10")):
  block=(data.get("comparison_strategies") or {}).get(key,{})
  engine=block.get("engine") or {};stats=block.get("stats") or {};positions_cmp=block.get("positions") or []
  wr="—" if stats.get("win_rate") is None else ("%.1f%%"%(float(stats.get("win_rate") or 0)*100))
  token_label="HYPE / NEAR / INIT / USELESS / GRASS / APT / TAO / CHIP / BABY / SPX / LIT / CASHCAT" if key=="local_s3" else "INIT / NEAR / GRASS / HYPE"
  comparison_html+='<h2>%s · %s · $500</h2>'%(esc(title),esc(token_label))
  comparison_html+='<div class="grid"><b>STATUS<br>%s</b><b>TOTAL EQUITY<br>$%s</b><b>RETURN<br><span class="%s">%s%%</span></b><b>REALIZED P&L<br>$%s</b><b>OPEN P&L<br>$%s</b><b>CLOSED TRADES<br>%s</b><b>WIN RATE<br>%s</b><b>OPEN POSITIONS<br>%s</b></div>'%(
   "OK" if engine.get("ok") else "ERROR",block.get("total_equity",500),"posv" if float(block.get("pnl_pct",0) or 0)>=0 else "negv",
   block.get("pnl_pct",0),stats.get("realized_pnl",0),block.get("unrealized_pnl",0),stats.get("trades",0),esc(wr),len(positions_cmp))
  details=engine.get("details") or {};posmap={p.get("symbol"):p for p in positions_cmp}
  rows=[]
  for sym in (LOCAL_S3_SYMBOLS if key=="local_s3" else LOCAL_EXPERIMENT_SYMBOLS):
   d=details.get(sym,{}) or {};anchor=d.get("h1_local") or {};p=posmap.get(sym) or {}
   side=p.get("side") or "—";pnl=float(p.get("unrealized_pnl",0) or 0)
   margin=float(p.get("margin_usd",0) or 0);notional=float(p.get("notional_usd",0) or 0);lev=float(p.get("leverage",0) or 0)
   rows.append('<tr><td>%s</td><td>%s @ %s</td><td>%s</td><td>$%.2f</td><td>$%.2f</td><td>%sx</td><td>%s</td><td>%s</td><td>%s</td><td class="%s">$%s</td><td>%s</td></tr>'%(
    esc(sym),esc(anchor.get("pivot_type") or "—"),esc(anchor.get("pivot_price") or "—"),esc(side),
    margin,notional,(round(lev,2) if lev else "—"),
    esc(p.get("entry","—")),esc(p.get("mark","—")),esc(p.get("roe_pct","—")),
    "posv" if pnl>=0 else "negv",round(pnl,4),esc(d.get("last_action") or "—")))
  comparison_html+='<table><tr><th>Token</th><th>Confirmed H1 local</th><th>Side</th><th>Margin $</th><th>Position $</th><th>Leverage</th><th>Entry</th><th>Mark</th><th>ROE%%</th><th>Open P&L</th><th>Action</th></tr>'+''.join(rows)+'</table>'
  if key=="local_s1":comparison_html+='<div class="muted">H1 sets direction. M15 weakening/profit floor closes profitable legs; confirmed pullback + resumption re-enters in the same H1 direction.</div>'
  elif key=="local_s2":comparison_html+='<div class="muted">Pure H1 swing: LOCAL HIGH → SHORT and hold until confirmed LOCAL LOW; then close and flip LONG. LOCAL LOW → LONG and hold until confirmed LOCAL HIGH; then close and flip SHORT. No M15 exits.</div>'
  else:comparison_html+='<div class="muted">Restored Local12 v10: 12 tokens · H1 direction · M15 weakening/profit floor · WAIT_PULLBACK → WAIT_RESUMPTION re-entry · 20% current MTM equity · fixed 25x PAPER · compounding.</div>'
 s1_hist=data.get("local_s1_closed_trades") or []
 s2_hist=data.get("local_s2_closed_trades") or []
 s3_hist=data.get("local_s3_closed_trades") or []
 def cmp_hist_rows(rows):
  return "".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>$%.2f</td><td>$%.2f</td><td>%sx</td><td>%s</td><td>%s</td><td class="%s">$%.4f</td><td>%s</td></tr>'%(
   esc(x.get("closed","")),esc(x.get("symbol","")),"LONG" if int(x.get("side",0) or 0)>0 else "SHORT",
   float(x.get("notional",0) or 0),float(x.get("margin",0) or 0),float(x.get("leverage",0) or 0),
   esc(x.get("entry","—")),esc(x.get("exit","—")),"posv" if float(x.get("pnl",0) or 0)>=0 else "negv",
   float(x.get("pnl",0) or 0),esc(x.get("reason",""))) for x in rows) or '<tr><td colspan=10>No closed trades yet</td></tr>'
 compare_history_html='<h2>STRATEGY 1 — CLOSED TRADES</h2><table><tr><th>Closed</th><th>Token</th><th>Side</th><th>Position $</th><th>Margin $</th><th>Lev</th><th>Entry</th><th>Exit</th><th>PnL</th><th>Reason</th></tr>'+cmp_hist_rows(s1_hist)+'</table>'
 compare_history_html+='<h2>STRATEGY 2 — CLOSED TRADES</h2><table><tr><th>Closed</th><th>Token</th><th>Side</th><th>Position $</th><th>Margin $</th><th>Lev</th><th>Entry</th><th>Exit</th><th>PnL</th><th>Reason</th></tr>'+cmp_hist_rows(s2_hist)+'</table>'
 compare_history_html+='<h2>STRATEGY 3 — LOCAL12 V10 — CLOSED TRADES</h2><table><tr><th>Closed</th><th>Token</th><th>Side</th><th>Position $</th><th>Margin $</th><th>Lev</th><th>Entry</th><th>Exit</th><th>PnL</th><th>Reason</th></tr>'+cmp_hist_rows(s3_hist)+'</table>'
 page='''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>PANDORA LIVE</title><style>body{font-family:system-ui;background:#080b10;color:#e8edf5;margin:0;padding:18px;max-width:1800px}h1{margin:0;font-size:30px}h2{margin-top:34px;border-bottom:1px solid #202938;padding-bottom:8px}.muted{color:#8b98aa}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}.grid b{background:#111722;padding:16px;border-radius:12px;box-shadow:0 0 0 1px #182235 inset}table{width:100%%;border-collapse:collapse;background:#0e141e;margin-bottom:22px;display:table}td,th{padding:9px;border-bottom:1px solid #202938;text-align:left;font-size:13px;white-space:nowrap}th{color:#91a2b8;position:sticky;top:0;background:#0e141e}.posv{color:#49d17d;font-weight:700}.negv{color:#ff6262;font-weight:700}.warnv{color:#f6c453;font-weight:700}a{color:#8bc4ff}.s1hero{background:#0b111a;border:2px solid #2b6fff;padding:18px;border-radius:16px;margin:18px 0 24px;box-shadow:0 0 28px rgba(43,111,255,.12)}.s1hero h2{margin-top:0;border:0}.progress{height:12px;background:#17202d;border-radius:999px;overflow:hidden;margin:8px 0 12px}.progress span{display:block;height:100%%;background:linear-gradient(90deg,#49d17d,#7fe3a6)}.primary{background:#0b111b;border:2px solid #315f9c;padding:18px;border-radius:16px;margin:18px 0 28px;box-shadow:0 0 0 1px #16263c inset}.primary h2{margin-top:0;border-bottom-color:#315f9c}.benchmark{background:#0d1d14;border:1px solid #255e3a;padding:18px;border-radius:14px;margin:18px 0}.benchnum{font-size:30px;font-weight:800;margin:6px 0}.scroll{overflow-x:auto;width:100%%}button{background:#182235;color:#e8edf5;border:1px solid #33425b;border-radius:8px;padding:8px 12px;margin-right:8px}@media(max-width:700px){body{padding:10px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}td,th{font-size:11px;padding:7px}h1{font-size:24px}}</style></head><body><p id="refreshStatus" class="muted">Connecting live updates…</p><main id="dashboardContent" data-poll="__MARKET_POLL__"><h1>PANDORA LIVE · FULL MONITOR</h1><div class="muted">Paper engine · automatic updates every 5s · last market poll %s</div>__S1_PRIMARY__%s__S1_BENCHMARK__<h2>ALL OPEN POSITIONS · ALL STRATEGIES</h2><div class="scroll"><table><tr><th>Strategy</th><th>Token</th><th>Side</th><th>Margin $</th><th>Position $</th><th>Lev</th><th>Entry</th><th>Mark</th><th>ROE</th><th>Open P&L</th><th>Opened</th></tr>__ALL_OPEN__</table></div><h2>News — статистика</h2>__NEWS_PERFORMANCE__<h2>NEWS / GENERAL OPEN POSITIONS</h2><button onclick="closePos(null)">Close Everything</button><button onclick="location.reload()">Refresh</button><p id="actionResult"></p><table><tr><th>Token</th><th>Side</th><th>Margin $</th><th>Position $</th><th>Leverage</th><th>Entry</th><th>Mark</th><th>ROI%%</th><th>P&L</th><th>Trigger</th><th>Action</th></tr>%s</table><h2>Pump/Dump PAPER positions</h2>%s<table><tr><th>Token</th><th>Side</th><th>Margin $</th><th>Position $</th><th>Leverage</th><th>Entry</th><th>Mark</th><th>ROI%%</th><th>P&L</th><th>Score</th></tr>%s</table><h2>Price to Value Liquidation</h2>%s<table><tr><th>Token</th><th>Side</th><th>Margin $</th><th>Position $</th><th>Leverage</th><th>Entry</th><th>Mark</th><th>ROI%%</th><th>P&L</th><th>Score</th></tr>%s</table><h3>Whale liquidation candidates</h3><table><tr><th>Token</th><th>Trade side</th><th>Whale size</th><th>Distance</th><th>Score</th><th>Victim</th><th>Liq price</th></tr>%s</table><h2>LOCAL H1 / M15 — HYPE + NEAR</h2>%s%s<table><tr><th>Token</th><th>Side</th><th>Margin $</th><th>Position $</th><th>Leverage</th><th>Entry</th><th>Mark</th><th>ROI%%</th><th>P&L</th><th>MAE / MFE ROE</th></tr>%s</table><p><a href="/local-v10/history">OPEN LOCAL v10 CLOSED TRADE HISTORY — LIVE DATABASE</a></p><h2>LOCAL · INIT / NEAR / GRASS / HYPE / BTC / ETH / SOL · $500</h2>%s%s<table><tr><th>Token</th><th>Side</th><th>Leverage</th><th>Phase</th><th>Entry kind</th><th>Entry</th><th>Mark</th><th>ROE</th><th>Target Position $</th><th>Required Margin $</th><th>Actual Margin $</th><th>Actual Position $</th><th>Exposure fill</th><th>Open P&L</th><th>Trades / WR</th></tr>%s</table><h2>LOCAL v10 — Closed trades only</h2><table><tr><th>Closed</th><th>Token</th><th>Side</th><th>PnL</th><th>Reason</th></tr>%s</table>__COMPARISON_STRATEGIES____COMPARE_HISTORY__<h2>News Scanner Health</h2>%s%s<table><tr><th>Source</th><th>Freshness</th><th>Latest post age (s)</th><th>Ingest lag (s)</th><th>Realtime verified</th></tr>%s</table><h2>Sources</h2><table><tr><th>Source</th><th>Status</th><th>Checked</th><th>Error</th></tr>%s</table><h2>Latest news</h2><table><tr><th>Time</th><th>Source</th><th>Token</th><th>Raw signal</th><th>Headline</th></tr>%s</table><p>Errors: %s · Last error: %s</p><p><a href="/api/dashboard">JSON dashboard</a> · <a href="/features">Features</a> · <a href="/trades">Trades</a> · <a href="/news">News</a></p></main><script>let closing=false,refreshing=false,refreshTimer=null;async function refreshDashboard(){clearTimeout(refreshTimer);if(refreshing||closing||document.visibilityState!=="visible"){if(document.visibilityState==="visible")refreshTimer=setTimeout(refreshDashboard,5000);return;}refreshing=true;const indicator=document.getElementById("refreshStatus");const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),10000);try{const response=await fetch("/?refresh="+Date.now(),{cache:"no-store",credentials:"same-origin",signal:controller.signal});if(!response.ok)throw new Error("HTTP "+response.status);const doc=new DOMParser().parseFromString(await response.text(),"text/html");const incoming=doc.getElementById("dashboardContent");if(!incoming)throw new Error("Invalid dashboard response");if(closing)return;const current=document.getElementById("dashboardContent");const top=window.scrollY;current.replaceWith(document.importNode(incoming,true));window.scrollTo(0,top);const marketAt=Date.parse(incoming.dataset.poll);const age=Number.isFinite(marketAt)?Math.max(0,(Date.now()-marketAt)/1000):null;indicator.textContent="Updated "+new Date().toLocaleTimeString()+(age===null?" · market freshness unavailable":" · market age "+age.toFixed(1)+"s")+(age!==null&&age>20?" · MARKET DATA STALE":"");indicator.style.color=age!==null&&age<=20?"#49d17d":"#f6c453"}catch(error){indicator.textContent="Update failed; retrying automatically · "+String(error);indicator.style.color="#ff6262"}finally{clearTimeout(timeout);refreshing=false;if(document.visibilityState==="visible")refreshTimer=setTimeout(refreshDashboard,5000)}}document.addEventListener("visibilitychange",()=>{clearTimeout(refreshTimer);if(document.visibilityState==="visible")refreshDashboard()});refreshTimer=setTimeout(refreshDashboard,5000);async function closePos(sym){if(closing||!confirm(sym?"Close "+sym+"?":"Close ALL positions?"))return;closing=true;const status=document.getElementById("actionResult");status.textContent="Processing close request...";try{const r=await fetch("/api/positions/close",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify(sym?{symbol:sym}:{all:true})});const result=await r.json();status.textContent=r.ok?"Close confirmed: "+JSON.stringify(result):(r.status===401?"Controls locked: open the control-access link once, then retry.":"Close failed ("+r.status+"): "+JSON.stringify(result));if(r.ok){location.reload();return}}catch(e){status.textContent="Close request failed: "+String(e)}finally{closing=false}}</script></body></html>'''%(esc(data["last_poll"]),cards,pos,pump_cards,pump_pos,whale_cards,whale_pos_html,whale_candidates_html,hype_cards,hype_note,hype_pos_html,exp_cards,exp_note,exp_rows_html,trs,news_health_cards,news_health_note,news_health_rows,src,news,data["errors"],esc(data["last_error"]))
 page=page.replace("__S1_PRIMARY__",s1_primary_html)
 page=page.replace("__S1_BENCHMARK__",bench_html)
 page=page.replace("__ALL_OPEN__",all_open_html)
 page=page.replace("__ALL_CLOSED__",all_closed_html)
 page=page.replace("__COMPARISON_STRATEGIES__",comparison_html)
 page=page.replace("__COMPARE_HISTORY__",compare_history_html)
 page=page.replace("__NEWS_PERFORMANCE__",strategy_cards_html(data.get("strategy_performance"),"news",(data.get("strategy_open_pnl") or {}).get("news",0),"News",data.get("capital_contributed"))+'<p class="muted">Win rate = прибыльные / все закрытые сделки. Последние 8 часов — по времени закрытия; открытый PnL отдельно. Суммы в USDT, с учётом настроенных комиссий.</p>')
 # Explicit visible Local v10 closed-trade section, anchored for direct navigation.
 page=page.replace('<h2>LOCAL v10 — Closed trades only</h2>','<h2 id="local-v10-history">LOCAL v10 — CLOSED TRADES · %s records · REALIZED $%.4f</h2>'%(len(data.get("local_v10_closed_trades",[])),float((data.get("local_experiment_stats") or {}).get("realized_pnl",0) or 0)))
 return page.replace("__MARKET_POLL__",esc(data.get("last_poll") or ""))


@account_mutation
def manual_close(symbol=None,reason_override=None):
 with LOCK:
  books=[("pump_dump",copy.deepcopy(S.get("pump_positions",{}))),
         ("local_12token_h1_m15",copy.deepcopy(S.get("local_v12_positions",{}))),
         ("local_legacy_exit_only",copy.deepcopy(S.get("local_swing_positions",{})))]
 targets=[(strategy,sym,pos) for strategy,book in books for sym,pos in book.items() if symbol is None or sym==symbol]
 if not targets and symbol:return {"ok":False,"results":[{"symbol":symbol,"ok":False,"error":"position_not_found"}]}
 results=[]
 for strategy,sym,pos in targets:
  with LOCK:
   price=S.get("_prices",{}).get(sym)
   fresh=S.get("_last_poll_epoch") and 0<=time.time()-S["_last_poll_epoch"]<=10 and S["engine_active"]
  if not fresh or not price:
   results.append({"symbol":sym,"ok":False,"error":"fresh_market_price_and_active_engine_required"});continue
  reason=reason_override or ("manual_close_all" if symbol is None else "manual_close")
  if strategy=="pump_dump":result=pump_close(sym,price,reason)
  elif strategy=="local_12token_h1_m15":result=local_experiment_close(sym,price,reason)
  else:result=local_swing_close(sym,price,reason)
  if result is None:results.append({"symbol":sym,"ok":False,"error":"close_not_committed"});continue
  results.append({"symbol":sym,"strategy":strategy,"ok":True,"price":price,"pnl":result.get("pnl")})
 return {"ok":all(x["ok"] for x in results) if results else True,"results":results}


class Handler(BaseHTTPRequestHandler):
 def log_message(self,fmt,*args):
  # The dashboard access link carries a credential. Never emit its query.
  return
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
  if path=="/local-v10/history":
   try:
    rows=local_v10_history(200)
    pnl=sum(float(x.get("pnl") or 0) for x in rows)
    esc_html=lambda x:html.escape(str(x))
    tr="".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%.4f</td><td>%s</td></tr>"%(esc_html(x["closed"]),esc_html(x["symbol"]),"LONG" if int(x["side"])>0 else "SHORT",float(x["pnl"]),esc_html(x["reason"])) for x in rows)
    body=('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta http-equiv="refresh" content="15"><title>PANDORA Local v10 history</title><style>body{background:#080b10;color:#e8edf5;font:15px system-ui;padding:16px}a{color:#8bc4ff}table{width:100%;border-collapse:collapse}td,th{border-bottom:1px solid #333;padding:9px;text-align:left}</style></head><body><h1>LOCAL v10 — CLOSED TRADES</h1><p>%s closed trades shown · realized PnL $%.4f · auto-refresh 15s</p><p><a href="/">Back to PANDORA monitor</a></p><table><tr><th>Closed</th><th>Token</th><th>Side</th><th>PnL USD</th><th>Reason</th></tr>%s</table></body></html>'%(len(rows),pnl,tr)).encode("utf-8")
    self.send_response(200)
   except Exception as exc:
    body=("Local v10 history query error: "+type(exc).__name__).encode("utf-8")
    self.send_response(503)
   self.send_header("Content-Type","text/html; charset=utf-8");self.send_header("Cache-Control","no-store")
   self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body);return
  if path=="/api/research/strategy1-week/start":
   try:
    args=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
    start_date=args.get("start",[None])[0]
    days=min(14,max(1,int(args.get("days",["7"])[0])))
    body=json.dumps(start_s1_week_backtest(start_date,days),ensure_ascii=False,default=str).encode()
    self.send_response(202)
   except Exception as exc:
    body=json.dumps({"ok":False,"error":type(exc).__name__+":"+str(exc)[:160]}).encode();self.send_response(500)
   self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Cache-Control","no-store")
   self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body);return
  if path=="/api/research/strategy1-week/status":
   body=json.dumps(s1_week_backtest_status(),ensure_ascii=False,default=str).encode()
   self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8")
   self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(body)))
   self.end_headers();self.wfile.write(body);return
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
   try:
    with LOCK:cached_html=S.get("_dashboard_html_cache")
    if cached_html:
     body=cached_html.encode("utf-8")
    else:
     # No S1/S2 legacy fallback. Build the single Strategy 1 page on demand.
     body=html_dashboard(dashboard()).encode("utf-8")
    ctype="text/html; charset=utf-8"
   except Exception as exc:
    import traceback
    traceback.print_exc()
    with LOCK:
     s1book=copy.deepcopy(S.get("local_s1_positions",{}))
     s1equity=float(S.get("local_s1_equity",500.0) or 500.0)
     prices=dict(S.get("_prices",{}))
    open_pnl=0.0;rows=[]
    for sym in LOCAL_EXPERIMENT_SYMBOLS:
     pos=s1book.get(sym) or {}
     side=int(pos.get("side",0) or 0)
     entry=float(pos.get("entry",0) or 0)
     mark=float(prices.get(sym) or pos.get("last_price") or entry)
     notional=float(pos.get("notional",0) or 0)
     pnl=(side*(mark/entry-1)*notional) if side and entry and mark else 0.0
     open_pnl+=pnl
     rows.append("<tr><td>%s</td><td>%s</td><td>$%.2f</td><td>$%.2f</td><td>$%+.2f</td></tr>"%(html.escape(sym),"LONG" if side==1 else ("SHORT" if side==-1 else "FLAT"),entry,mark,pnl))
    total=s1equity-500.0+open_pnl+377.36
    fallback='''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta http-equiv="refresh" content="5"><title>PANDORA — Total PNL</title>
<style>body{margin:0;padding:18px;background:#090f1a;color:#eff5ff;font-family:system-ui}h1{font-size:28px}.hero{border:1px solid #3e8d7b;background:#12382f;border-radius:20px;padding:24px}.value{font-size:clamp(39px,8vw,78px);font-weight:800;color:#70e1ae}.sub{color:#b3c6d4}table{width:100%%;border-collapse:collapse;background:#131e30}td,th{border-bottom:1px solid #2d3d55;padding:12px;text-align:left}a{color:#a3d3ff}</style></head><body>
<h1>PANDORA</h1><div class="hero"><b>Total PNL · Сценарий</b><div class="value">$%+.2f (%+.2f%%%%)</div><div class="sub">PAPER + исторический расчётный потенциал; не подтверждённая исполненная прибыль</div></div>
<h2>Позиции Strategy 1</h2><table><tr><th>Токен</th><th>Направление</th><th>Вход</th><th>Цена</th><th>Open PNL</th></tr>%s</table>
<p class="sub">Детальная панель временно недоступна. <a href="/api/dashboard">Проверить данные</a></p></body></html>'''%(total,100*total/500.0,"".join(rows))
    body=fallback.encode("utf-8");ctype="text/html; charset=utf-8"
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
 social={k:v for k,v in sources.items() if k in ("XMonitor","XCriticalMonitor","XFilteredStream","XListMonitor","TruthMonitor","TruthStream","TruthDirect:realDonaldTrump","TruthSocialPublic","PiQDirect")}
 unavailable=[k for k,v in social.items() if not v.get("ok") and k not in ("XFilteredStream","XListMonitor","TruthStream","TruthSocialPublic")]
 return {"healthy":healthy,"risk_ready":ready,"news_sources_total":len(sources),"news_sources_failed":sum((not v.get("ok",False)) and not k.startswith(("XFree:","XIndex:")) and k!="XIndexMonitor" and k not in SEARCH_INDEX_FEEDS for k,v in sources.items()),"social_sources_failed":unavailable,"guest_x_realtime_verified":False,"news_24h_guaranteed":False,"engine_active":S["engine_active"],
         "market_age_seconds":age,"checkpoint_age_seconds":checkpoint_age,
         "engine_error":S["engine_error"],"last_market_error":S["last_market_error"],
         "news_max_age_seconds":NEWS_MAX_AGE_SECONDS,"market_structure_filter_active":False,
         "mode":S["mode"],"version":os.getenv("RENDER_GIT_COMMIT","risk-state-v2")}

class HyperliquidBudgetProxy(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  if self.path!="/info":self.send_error(404);return
  try:
   size=int(self.headers.get("Content-Length","0"))
   if not 0<size<=65536:raise ValueError("invalid_request_size")
   payload=json.loads(self.rfile.read(size))
   if not isinstance(payload,dict) or not isinstance(payload.get("type"),str):raise ValueError("invalid_info_request")
   body=get(API,payload);status=200;retry=None
  except RestDeferred:
   status=503;body=b'{"error":"shared_rest_budget_deferred"}';retry=max(1,int(HL_REST_BUDGET.status()["cooldown_seconds"]))
  except urllib.error.HTTPError as exc:
   status=exc.code;body=b'{"error":"upstream_info_request_failed"}';retry=max(1,int(HL_REST_BUDGET.status()["cooldown_seconds"])) if status==429 else None
  except (ValueError,TypeError):status=400;body=b'{"error":"invalid_request"}';retry=None
  except Exception:status=502;body=b'{"error":"upstream_unavailable"}';retry=None
  self.send_response(status);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(body)))
  if retry:self.send_header("Retry-After",str(retry))
  self.end_headers()
  try:self.wfile.write(body)
  except (BrokenPipeError,ConnectionResetError):pass

if __name__=="__main__":
 budget_proxy=ThreadingHTTPServer(("127.0.0.1",8421),HyperliquidBudgetProxy)
 threading.Thread(target=budget_proxy.serve_forever,daemon=True,name="shared-hl-rest-budget").start()
 if WHALE_NEW_ENTRIES_ENABLED:
  try:subprocess.Popen([os.sys.executable,"hyperdata_runner.py"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  except Exception as e:S["sources"]["HyperData"]={"ok":False,"error":str(e)[:120]}
 else:
  S["sources"]["HyperData"]={"ok":True,"disabled":True,"mode":"disabled_with_whale_entries","last_check":now(),"error":None}
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
  ("engine_coordinator",engine_coordinator),
  ("market",market),
  ("market_metadata",market_metadata),
  ("market_history_bootstrap",market_history_bootstrap),
  ("market_trades",market_trade_stream),
  ("breadth_history",market_regime_history),
  ("telemetry",telemetry),
  ("local_strategy_comparison",comparison_strategies_loop),
  ("dashboard_history",dashboard_history_loop),
  ("dashboard_cache",dashboard_cache_loop),
  ("diagnostics",operations_diagnostics)
 ]
 # Trading ingestion is intentionally minimal: FirstSquawk on X + PiQ Direct.
 # Unused X/RSS/Truth sources stay out of the live path so their transport failures
 # cannot create false scanner alarms or add unnecessary request load.
 # Source scanners are monitoring infrastructure and must stay alive even when
 # news-triggered entries are disabled. Trade eligibility remains gated inside
 # ingest/entry logic by NEWS_NEW_ENTRIES_ENABLED.
 if not S1_ONLY_MODE:
  worker_specs.extend([("x_critical_4s",x_critical_realtime),("piq_direct",piq_direct_realtime)])
 if NEWS_NEW_ENTRIES_ENABLED and not S1_ONLY_MODE:
  # Trading news path remains intentionally minimal: FirstSquawk + PiQ Direct.
  # Their dedicated workers are always running above; recovery only processes durable queued events.
  worker_specs.append(("news_recovery",recover_news_processing))
 if os.getenv("ENABLE_PUBLIC_X_HTML","0")=="1":
  for handle in WATCH:worker_specs.append(("public-x:"+handle,lambda h=handle:public_social_reader("x",h)))
 def s1_historical_autostart():
  while not SHUTDOWN.is_set():
   with LOCK:active=bool(S.get("engine_active"))
   if not active:
    SHUTDOWN.wait(1);continue
   try:
    # Canonical historical ledger = latest seven fully completed UTC days.
    end_day=datetime.datetime.now(datetime.timezone.utc).date()
    start_day=(end_day-datetime.timedelta(days=7)).isoformat()
    start_s1_week_backtest(start_day,7)
    while not SHUTDOWN.is_set():
     st=s1_week_backtest_status()
     if st.get("status")=="done":
      persist_s1_research_result(st.get("result"))
      print("S1_RESEARCH_DURABLE persisted",flush=True)
      return
     if st.get("status")=="error":
      return
     SHUTDOWN.wait(2)
   except Exception as exc:
    with LOCK:S["last_error"]="s1_historical_autostart: "+type(exc).__name__+":"+str(exc)[:120]
   return
 workers=[threading.Thread(target=supervised_worker,args=(label,fn),daemon=True,name=label) for label,fn in worker_specs]
 # Operator action is intentionally one-shot; normal completion is not a health failure.
 workers.append(threading.Thread(target=operator_one_shot_actions,daemon=True,name="operator_actions"))
 workers.append(threading.Thread(target=authorized_cleanup_worker,daemon=True,name="authorized_cleanup"))
 workers.append(threading.Thread(target=post_lease_historical_restore,daemon=True,name="historical_restore"))
 workers.append(threading.Thread(target=s1_historical_autostart,daemon=True,name="s1_historical_backtest"))
 for worker in workers:worker.start()
 try:server.serve_forever()
 finally:
  SHUTDOWN.set();server.server_close()
  for worker in workers:worker.join(timeout=0.5)
  try:STORE.release()
  except Exception:pass
