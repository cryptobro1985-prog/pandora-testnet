"""PANDORA PAPER: H1 direction and event-driven executed-flow Caterpillar."""
import copy,datetime,functools,hashlib,html,json,math,os,re,signal,threading,time
import urllib.request,urllib.parse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import psycopg
from psycopg.rows import dict_row
from accounting import paper_pnl
from engine_store import EngineStore,LeaseLost
from market_data import RollingMarketData
from bybit_market_stream import run_bybit_stream
from h1_structure import analyze as analyze_hype_h1,pending_extreme as local_pending_extreme,update_path as hype_update_path,POLICY as HYPE_SWING_POLICY
from local_order_flow import POLICY as LOCAL4_FLOW_POLICY,entry_candidate as local4_entry_candidate,initial_entry_candidate as local4_initial_entry_candidate,pressure_exit as local4_pressure_exit,update_watch as local4_update_watch,reentry_ready as local4_reentry_ready
from strategy11_engine import LegacyStrategy11

LOCAL_EXPERIMENT_SYMBOLS=('INIT','NEAR','BTC','SOL','ETH','LIT','HYPE','ZEC','TAO','GRASS','BIRB','BEAM')
LOCAL_EXPERIMENT_STARTING_EQUITY=500.0
LOCAL_EXPERIMENT_MARGIN_FRACTION=.20
LOCAL_EXPERIMENT_MAX_POSITIONS=None
DISCOVERY_MAX_SELECTED=8
DISCOVERY_SCAN_SECONDS=300
S1_ONLY_MODE=True
FEE=.00045
LOCK=threading.RLock();ACCOUNT_LOCK=threading.RLock();SHUTDOWN=threading.Event();TRADE_WAKE=threading.Event()
START=time.time()
S={'mode':'PAPER_ONLY','orders_enabled':False,'engine_active':False,'engine_error':None,
 'sources':{},'_prices':{},'_price_received_epoch':{},'_timeline':{},'_hist':{},'_last_poll_epoch':0,
 'last_poll':None,'last_checkpoint':None,'last_market_error':None,'market_count':0,
 'local_v12_positions':{},'local_experiment_watch':{},'local_h1_direction':{},'_local4_analysis':{},
 'local_experiment_equity':500.,'local_experiment_realized_pnl':0.,'local_experiment_trades':0}
MARKET_OBS=RollingMarketData(max_symbols=64,max_trade_lag_seconds=60,freshness_seconds=60,max_seen_per_symbol=65536)
MARKET_AUX_OBS=RollingMarketData(max_symbols=64)
_LOCAL_CANDLE_CACHE={};_LOCAL_CANDLE_CACHE_LOCK=threading.RLock();_LOCAL_CANDLE_CHECKPOINTED={}
STRATEGY1_HISTORY_TABLES={'strategy1':'local_v12_trade_history','legacy_s1':'local_s1_trade_history',
 'legacy_s2':'local_s2_trade_history','legacy_s3':'local_s3_trade_history','legacy_h1':'hype_swing_trade_history','legacy_shared':'trade_history'}

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()

def publication_epoch(value):
 try:return datetime.datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp()
 except (ValueError,TypeError):return None

def pg():return psycopg.connect(os.environ['DATABASE_URL'],autocommit=True,row_factory=dict_row,connect_timeout=5)
STORE=EngineStore(pg)
S11=None

def journal(kind,event_id,payload):
 with pg() as db:db.execute('insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,%s,%s,%s::jsonb)',(now(),event_id,kind,json.dumps(payload,default=str)))

def log_learning_decision(ident,strategy,symbol,side,action,reason,entry_price=None,score=None,leverage=1,features=None,ts=None):
 # Supplementary decision journal. The authoritative OPEN/CLOSE is atomic with the ledger.
 try:journal('strategy1_decision',ident,dict(symbol=symbol,side=side,action=action,reason=reason,features=features or {}));return True
 except Exception:return False

def apply_local4_user_reset():
 marker='reset_2026_10_31_ab_strategy12_clean'
 with pg() as db:
  with db.transaction():
   done=db.execute("select 1 from audit_journal where event_id=%s limit 1",(marker,)).fetchone()
   if done:return False
   # User-requested full PAPER reset: no historical trades survive into the new statistics.
   db.execute("truncate table local_v12_positions,local_v12_watchlist,local_v12_signal_journal,local_v12_trade_history restart identity")
   db.execute("truncate table local_v12_trade_history_archive_20261031 restart identity")
   db.execute("delete from audit_journal where kind like 'strategy1_%' or kind like 'local_experiment_%'")
   # Force fresh H1/bootstrap state; no stale scanner or local survives this session.
   db.execute("delete from local_h1_direction")
   db.execute("delete from local_candle_checkpoints")
   # Remove stale published dashboard state; the live engine republishes immediately after boot.
   db.execute("delete from local_v12_live_state")
   stamp=now()
   db.execute("update local_v12_account_state set equity=500,realized_pnl=0,started_at=%s,updated_at=%s where id=1",(stamp,stamp))
   db.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,%s,'strategy1_user_reset',%s::jsonb)",
    (stamp,marker,json.dumps({"starting_equity":500,"history_deleted":True,"scanner_state_cleared":True,"h1_anchors_rebuild":True,"full_flow_warmup_seconds":300,"automatic_negative_close_forbidden":True})))
 return True

SCHEMA=(
 "CREATE TABLE IF NOT EXISTS local_v12_account_state(id integer PRIMARY KEY,equity double precision NOT NULL,realized_pnl double precision NOT NULL,started_at text NOT NULL,updated_at text NOT NULL)",
 "CREATE TABLE IF NOT EXISTS local_v12_positions(symbol text PRIMARY KEY,side integer NOT NULL,entry double precision NOT NULL,notional double precision NOT NULL,margin double precision NOT NULL,leverage double precision NOT NULL,opened text NOT NULL,opened_epoch double precision NOT NULL,signal_candle_time bigint,features jsonb NOT NULL DEFAULT '{}'::jsonb)",
 "CREATE TABLE IF NOT EXISTS local_v12_trade_history(id bigserial PRIMARY KEY,opened text,closed text,symbol text,side integer,entry double precision,exit double precision,pnl double precision,reason text,margin double precision,notional double precision,leverage double precision,features jsonb NOT NULL DEFAULT '{}'::jsonb)",
 "CREATE TABLE IF NOT EXISTS local_v12_watchlist(symbol text PRIMARY KEY,side integer NOT NULL,origin_signal_candle bigint,exit_price double precision,exit_at text NOT NULL,expires_epoch double precision NOT NULL DEFAULT 0,reentries integer NOT NULL DEFAULT 0,context jsonb NOT NULL DEFAULT '{}'::jsonb)",
 "CREATE TABLE IF NOT EXISTS local_h1_direction(symbol text PRIMARY KEY,analysis jsonb NOT NULL)",
 "CREATE TABLE IF NOT EXISTS local_v12_signal_journal(id text PRIMARY KEY,ts text NOT NULL,candle_time bigint,action text NOT NULL,side integer,price double precision,features jsonb NOT NULL DEFAULT '{}'::jsonb)",
 "CREATE TABLE IF NOT EXISTS audit_journal(id bigserial PRIMARY KEY,recorded_at text NOT NULL,event_id text,kind text NOT NULL,payload jsonb NOT NULL)",
 "CREATE TABLE IF NOT EXISTS local_candle_checkpoints(symbol text NOT NULL,interval text NOT NULL,candles jsonb NOT NULL,saved_at timestamptz NOT NULL DEFAULT clock_timestamp(),PRIMARY KEY(symbol,interval))",
 "CREATE TABLE IF NOT EXISTS local_v12_live_state(id integer PRIMARY KEY,ts text NOT NULL,commit text,prices jsonb NOT NULL DEFAULT '{}'::jsonb,positions jsonb NOT NULL DEFAULT '{}'::jsonb,unrealized_pnl double precision NOT NULL DEFAULT 0,total_equity double precision NOT NULL DEFAULT 0,price_age_seconds double precision,source text)",
 "CREATE INDEX IF NOT EXISTS local_experiment_trade_closed_idx ON local_v12_trade_history(closed DESC)",
 "CREATE INDEX IF NOT EXISTS audit_journal_kind_time_idx ON audit_journal(kind,recorded_at)")

def restore_state():
 with pg() as db:
  account=db.execute('select * from local_v12_account_state where id=1').fetchone()
  positions=db.execute('select * from local_v12_positions').fetchall()
  watches=db.execute('select * from local_v12_watchlist').fetchall()
  anchors=db.execute('select * from local_h1_direction').fetchall()
  count=db.execute('select count(*) n from local_v12_trade_history').fetchone()['n']
 with LOCK:
  S['local_experiment_equity']=float(account['equity']);S['local_experiment_realized_pnl']=float(account['realized_pnl'])
  S['local_experiment_started_at']=account['started_at'];S['local_experiment_trades']=int(count)
  S['local_v12_positions']={r['symbol']:{**dict(r),'t':float(r['opened_epoch'])} for r in positions}
  S['local_experiment_watch']={r['symbol']:dict(r) for r in watches}
  S['local_h1_direction']={r['symbol']:r['analysis'] for r in anchors}
  S['_local4_analysis']=copy.deepcopy(S['local_h1_direction'])

def pinit():
 with pg() as db:
  with db.transaction():
   for query in SCHEMA:db.execute(query)
   db.execute('insert into local_v12_account_state(id,equity,realized_pnl,started_at,updated_at) values(1,500,0,%s,%s) on conflict(id) do nothing',(now(),now()))
 EngineStore(pg).migrate()
 apply_local4_user_reset()
 restore_state()
 global S11
 S11=LegacyStrategy11(pg,STORE,MARKET_OBS,current_entry_price,
  lambda: copy.deepcopy(S.get("_prices",{})),paper_pnl,FEE,now)
 S11.ensure_schema("reset_2026_10_31_ab_strategy11_clean")
 with pg() as db:
  seeds=db.execute("select candles from local_candle_checkpoints where interval='1h'").fetchall()
  prior_discovery=db.execute("select payload from audit_journal where kind='strategy1_discovery_scan' order by id desc limit 1").fetchone()
 if prior_discovery:
  with LOCK:S["bybit_discovery"]=copy.deepcopy(prior_discovery["payload"])
 for row in seeds:
  rows=row['candles'] or []
  if rows and all(r.get('venue')=='bybit' for r in rows):accept_local_candles(rows,history=True)
 with LOCK:S['sources']['PersistentPostgres']={'ok':True,'last_check':now()}

def accept_local_candles(data,history=False):
 rows=data if isinstance(data,list) else [data]
 stamp=time.monotonic();wall=int(time.time()*1000)
 with _LOCAL_CANDLE_CACHE_LOCK:
  for row in rows:
   if not isinstance(row,dict) or row.get('i')!='1h':continue
   symbol=row.get('s')
   if symbol not in set(strategy1_runtime_symbols()):continue
   try:
    t,T=int(row['t']),int(row['T']);o,h,l,c,v=[float(row[k]) for k in ('o','h','l','c','v')]
    if not all(math.isfinite(x) for x in (o,h,l,c,v)) or min(o,h,l,c)<=0 or v<0:continue
    if not 3599000<=T-t<=3600000 or not l<=min(o,c)<=max(o,c)<=h or t>wall+1000:continue
   except (KeyError,ValueError,TypeError):continue
   key=(symbol,'1h',120);old=_LOCAL_CANDLE_CACHE.get(key)
   merged={int(r['t']):r for r in old[1]} if old else {}
   if not history or t not in merged or T<wall-1000:merged[t]=dict(row)
   _LOCAL_CANDLE_CACHE[key]=(stamp,[merged[k] for k in sorted(merged)][-125:],wall)
 TRADE_WAKE.set()

def checkpoint_local_candles():
 pending=[];wall=int(time.time()*1000)
 with _LOCAL_CANDLE_CACHE_LOCK:
  for key,item in _LOCAL_CANDLE_CACHE.items():
   closed=[r['t'] for r in item[1] if r['T']<=wall-1000]
   if len(closed)<6:continue
   token=max(closed)
   if _LOCAL_CANDLE_CHECKPOINTED.get(key)!=token:pending.append((key,token,copy.deepcopy(item[1])))
 if not pending:return
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   for key,token,rows in pending:
    db.execute('insert into local_candle_checkpoints(symbol,interval,candles,saved_at) values(%s,%s,%s::jsonb,clock_timestamp()) on conflict(symbol,interval) do update set candles=excluded.candles,saved_at=excluded.saved_at',(key[0],key[1],json.dumps(rows)))
 for key,token,rows in pending:_LOCAL_CANDLE_CHECKPOINTED[key]=token

def _local_h1_candles(symbol):
 with _LOCAL_CANDLE_CACHE_LOCK:item=_LOCAL_CANDLE_CACHE.get((symbol,'1h',120))
 if not item:raise RuntimeError('closed_h1_history_unavailable:'+symbol)
 return copy.deepcopy(item[1]),int(time.time()*1000)


def account_mutation(fn):
 @functools.wraps(fn)
 def run(*args,**kwargs):
  # Serialize account writes without blocking price/health/source snapshots.
  with ACCOUNT_LOCK:return fn(*args,**kwargs)
 return run

def strategy1_runtime_symbols():
 with LOCK:hot=tuple((S.get("bybit_discovery") or {}).get("selected_symbols") or ())
 return tuple(dict.fromkeys(tuple(LOCAL_EXPERIMENT_SYMBOLS)+hot))

def strategy1_runtime_h1_verified(symbol,analysis=None,now_epoch=None):
 # Persisted H1 anchors are valid for display and managing an already-open position,
 # but a NEW entry/re-entry must be backed by an H1 scan performed by THIS process.
 # This prevents deploy/lease takeover from reopening a stale regime before current
 # closed H1 candles have been re-read.
 with LOCK:meta=copy.deepcopy(S.get("_local_h1_runtime_verified",{}).get(symbol))
 if not meta:return False
 try:
  now_epoch=float(time.time() if now_epoch is None else now_epoch)
  verified_at=float(meta.get("verified_at") or 0)
  last_closed=int(meta.get("last_candle_time") or 0)
  side=int(meta.get("entry_side") or 0)
  signal=int(meta.get("signal_candle_time") or 0)
  pivot=int(meta.get("pivot_candle_time") or 0)
 except (TypeError,ValueError,OverflowError):
  return False
 age=now_epoch-verified_at
 if age<0:return False
 # H1 candles are UTC-aligned. After the first second of a new hour, the
 # immediately preceding H1 candle must have been present in the verified scan.
 expected_latest=int(((now_epoch*1000.0-1000.0)//3_600_000)*3_600_000-3_600_000)
 if expected_latest>0 and last_closed<expected_latest:return False
 if analysis is not None:
  try:
   if int(analysis.get("entry_side") or 0)!=side:return False
   if int(analysis.get("signal_candle_time") or 0)!=signal:return False
   if int(analysis.get("pivot_candle_time") or 0)!=pivot:return False
  except (TypeError,ValueError,OverflowError):
   return False
 return side in (-1,1) and signal>0 and pivot>0

def strategy1_confirmed_h1(a):
 # Confirmed H1 LOCAL_HIGH -> SHORT or LOCAL_LOW -> LONG; no other trade filter.
 if not isinstance(a,dict):return False
 try:
  side=int(a.get("entry_side") or 0)
  price=float(a.get("pivot_price") or 0)
  signal=int(a.get("signal_candle_time") or 0)
 except (TypeError,ValueError,OverflowError):return False
 expected="LOCAL_HIGH" if side==-1 else "LOCAL_LOW" if side==1 else None
 return bool(expected and a.get("ready") and a.get("anchor_confirmed") and
  a.get("h1_direction_anchor") and not a.get("entry_blocked") and
  a.get("pivot_type")==expected and math.isfinite(price) and price>0 and signal>0)

def strategy1_trade_symbols():
 with LOCK:
  analyses=copy.deepcopy(S.get("_local4_analysis",{}));durable=copy.deepcopy(S.get("local_h1_direction",{}))
 return tuple(sym for sym in strategy1_runtime_symbols()
  if strategy1_confirmed_h1(analyses.get(sym)) or strategy1_confirmed_h1(durable.get(sym)))

def bybit_volatility_discovery_loop():
 while not SHUTDOWN.is_set():
  try:
   req=urllib.request.Request("https://api.bybit.com/v5/market/tickers?category=linear",
    headers={"User-Agent":"pandora-paper/1.0","Accept":"application/json"})
   with urllib.request.urlopen(req,timeout=12) as response:payload=json.load(response)
   if int(payload.get("retCode",-1))!=0:raise RuntimeError("bybit_tickers_failed")
   with LOCK:instruments=set((S.get("_bybit_instruments") or {}).keys())
   rows=[]
   for x in (payload.get("result") or {}).get("list") or []:
    pair=str(x.get("symbol") or "")
    if not pair.endswith("USDT"):continue
    symbol=pair[:-4]
    if symbol in LOCAL_EXPERIMENT_SYMBOLS:continue
    if instruments and symbol not in instruments:continue
    try:
     last=float(x.get("lastPrice") or 0);chg=float(x.get("price24hPcnt") or 0)*100.0
     high=float(x.get("highPrice24h") or 0);low=float(x.get("lowPrice24h") or 0)
     turn=float(x.get("turnover24h") or 0)
    except (TypeError,ValueError,OverflowError):continue
    if not all(math.isfinite(v) for v in (last,chg,high,low,turn)) or last<=0 or low<=0 or turn<=0:continue
    rng=(high/low-1.0)*100.0 if high>0 else 0.0
    rows.append({"symbol":symbol,"pair":pair,"change_24h_pct":round(chg,3),
      "range_24h_pct":round(rng,3),"turnover_24h":round(turn,2),"last":last})
   rows.sort(key=lambda r:(abs(r["change_24h_pct"]),r["turnover_24h"]),reverse=True)
   with LOCK:prior=copy.deepcopy(S.get("bybit_discovery") or {})
   frozen=list(prior.get("selected_symbols") or [])
   if frozen:
    by_symbol={r["symbol"]:r for r in rows}
    selected=[by_symbol[x] for x in frozen if x in by_symbol]
    selected_symbols=frozen
   else:
    selected=rows[:DISCOVERY_MAX_SELECTED]
    selected_symbols=[r["symbol"] for r in selected]
   snapshot={"at":now(),"basis":"Bybit linear USDT · absolute 24h move","selected_symbols":selected_symbols,
    "selected":selected,"top_movers":rows[:20],"selection_frozen":True}
   with LOCK:S["bybit_discovery"]=snapshot
   journal("strategy1_discovery_scan",None,snapshot)
   delay=DISCOVERY_SCAN_SECONDS
  except Exception as exc:
   with LOCK:S["sources"]["BybitDiscovery"]={"ok":False,"last_check":now(),"error":type(exc).__name__+":"+str(exc)[:160]}
   delay=30
  else:
   with LOCK:S["sources"]["BybitDiscovery"]={"ok":True,"last_check":now(),"selected":len(selected),"error":None}
  SHUTDOWN.wait(delay)

def bybit_instruments_loop():
 # Public contract constraints are independent of H1, quote and execution workers.
 while not SHUTDOWN.is_set():
  try:
   instruments={};cursor=""
   while True:
    query=urllib.parse.urlencode({"category":"linear","limit":1000,**({"cursor":cursor} if cursor else {})})
    req=urllib.request.Request("https://api.bybit.com/v5/market/instruments-info?"+query,
      headers={"User-Agent":"pandora-paper/1.0"})
    with urllib.request.urlopen(req,timeout=10) as response:payload=json.load(response)
    if int(payload.get("retCode",-1))!=0:raise RuntimeError("bybit_instruments_failed")
    result=payload.get("result") or {}
    for row in result.get("list") or []:
     pair=str(row.get("symbol") or "")
     if not pair.endswith("USDT") or row.get("status")!="Trading":continue
     lev=float((row.get("leverageFilter") or {}).get("maxLeverage") or 0)
     if math.isfinite(lev) and lev>=1:
      instruments[pair[:-4]]={"max_leverage":lev,"observed_at":time.time(),"status":row["status"]}
    next_cursor=result.get("nextPageCursor") or ""
    if not next_cursor:break
    if next_cursor==cursor:raise RuntimeError("bybit_instruments_cursor_stalled")
    cursor=next_cursor
   with LOCK:
    S["_bybit_instruments"]=instruments
    S["sources"]["BybitInstruments"]={"ok":True,"last_check":now(),"markets":len(instruments),"error":None}
   delay=3600
  except Exception as exc:
   with LOCK:S["sources"]["BybitInstruments"]={"ok":False,"last_check":now(),"error":type(exc).__name__+":"+str(exc)[:140]}
   delay=30
  SHUTDOWN.wait(delay)

def current_entry_price(symbol):
 with LOCK:
  if not S["engine_active"] or S.get("mode")!="PAPER_ONLY" or S.get("orders_enabled") or SHUTDOWN.is_set():return None
  if time.time()-S.get("_price_received_epoch",{}).get(symbol,0)>10:return None
  checkpoint=publication_epoch(S.get("last_checkpoint"))
  if checkpoint is None or time.time()-checkpoint>15:return None
  price=S.get("_prices",{}).get(symbol)
  return float(price) if price is not None and math.isfinite(float(price)) and float(price)>0 else None

def accept_market_prices(mids):
 valid={}
 for k,v in (mids or {}).items():
  try:
   px=float(v)
   if re.match(r"^[A-Z0-9]{1,15}$",k) and math.isfinite(px) and px>0:valid[k]=px
  except (ValueError,TypeError):continue
 if not valid:raise ValueError("empty market response")
 stamp=time.time()
 with LOCK:
  S["last_poll"]=now();S["_last_poll_epoch"]=stamp;merged=dict(S.get("_prices",{}));merged.update(valid);S["market_count"]=len(merged);S["_prices"]=merged;S["last_market_error"]=None
  for sym,px in valid.items():
   S.setdefault("_price_received_epoch",{})[sym]=stamp
   track=S.setdefault("_timeline",{}).setdefault(sym,[])
   if not track or stamp-float(track[-1][0])>=0.5:
    track.append((stamp,px))
    if len(track)>1800:del track[:-1800]
   hist=S.setdefault("_hist",{}).setdefault(sym,[])
   if not hist or float(hist[-1])!=px:
    hist.append(px)
    if len(hist)>120:del hist[:-120]
 TRADE_WAKE.set()
 return valid

def local_h1_direction(rows,now_ms,symbol):
 analysis=analyze_hype_h1(rows,now_ms,symbol)
 if not analysis.get("ready") or not analysis.get("anchor_confirmed"):
  # Fresh H1 cache may lag during deploy/lease handoff. Keep the latest
  # confirmed directional anchor usable instead of blanking the symbol.
  fallback=_local_persisted_anchor(symbol)
  if fallback and fallback.get("policy")==HYPE_SWING_POLICY and int(fallback.get("entry_side") or 0) in (-1,1):
   recovered={**fallback,"ready":True,"stale_source_reason":analysis.get("reason"),
     "anchor_recovered_from":"latest_valid_strategy1_observation",
     **local_pending_extreme(rows,now_ms,int(fallback.get("entry_side") or 0),fallback.get("pivot_price"))}
   try:
    with pg() as db:
     with db.transaction():
      STORE.fence(db)
      db.execute("insert into local_h1_direction(symbol,analysis) values(%s,%s::jsonb) on conflict(symbol) do update set analysis=excluded.analysis",
       (symbol,json.dumps(recovered)))
    with LOCK:S.setdefault("local_h1_direction",{})[symbol]=copy.deepcopy(recovered)
   except Exception:
    pass
   return recovered
  return analysis
 # Universal monotonicity guard: a fresh reconstruction can never roll the
 # strategy back behind a newer confirmed anchor already proven by durable state.
 trusted=_local_persisted_anchor(symbol)
 if trusted and int(trusted.get("entry_side") or 0) in (-1,1):
  trusted_t=int(trusted.get("signal_candle_time") or 0)
  fresh_t=int(analysis.get("signal_candle_time") or 0)
  if trusted_t>fresh_t and trusted.get("policy")==HYPE_SWING_POLICY:
   analysis={**trusted,"ready":True,"last_candle_time":analysis.get("last_candle_time"),
    **local_pending_extreme(rows,now_ms,int(trusted.get("entry_side") or 0),trusted.get("pivot_price")),
    "anchor_guard":"newest_confirmed_anchor_wins"}
 with LOCK:prior=copy.deepcopy(S.get("local_h1_direction",{}).get(symbol))
 if prior:
  prior_t=int(prior.get("signal_candle_time") or 0);new_t=int(analysis.get("signal_candle_time") or 0)
  prior_side=int(prior.get("entry_side") or 0);new_side=int(analysis.get("entry_side") or 0)
  if prior_t>new_t and prior.get("policy")==HYPE_SWING_POLICY:
   # A shorter restart cache must never roll a newer persisted H1 anchor back.
   analysis={**prior,"ready":True,"last_candle_time":analysis.get("last_candle_time"),
     **local_pending_extreme(rows,now_ms,prior_side)}
  elif prior_side in (-1,1) and new_side in (-1,1) and new_side!=prior_side:
   # Only a strictly newer closed-H1 structure changes direction.
   # Current flow controls execution, independently of H1 confirmation.
   if new_t<=prior_t:
    analysis={**prior,"ready":True,"last_candle_time":analysis.get("last_candle_time"),
      **local_pending_extreme(rows,now_ms,prior_side),
      "anchor_guard":"blocked_non_new_opposite_pivot"}
   else:
    analysis["anchor_guard"]="newer_opposite_closed_h1_structure"
 if analysis.get("entry_side") not in (-1,1):
  # Migration/restart recovery: if fresh reconstruction has no immediately
  # confirmable swing, restore the newest previously observed confirmed H1 anchor.
  # This keeps every analyzed symbol directionally usable until a newer confirmed
  # opposite pivot supersedes it; pending extremes remain diagnostic-only.
  fallback=_local_persisted_anchor(symbol)
  if fallback and fallback.get("policy")==HYPE_SWING_POLICY and int(fallback.get("entry_side") or 0) in (-1,1):
   analysis={**fallback,"ready":True,
     "last_candle_time":analysis.get("last_candle_time"),
     **local_pending_extreme(rows,now_ms,int(fallback.get("entry_side") or 0),fallback.get("pivot_price")),
     "anchor_recovered_from":"latest_valid_strategy1_observation"}
  else:
   return analysis
 # Process-local proof that current CLOSED H1 candles were actually scanned.
 # This marker is written only AFTER all structural + flow guards select the
 # final active anchor, so the 500ms executor cannot outrun H1 reconciliation.
 if analysis.get("ready") and analysis.get("anchor_confirmed") and int(analysis.get("entry_side") or 0) in (-1,1):
  with LOCK:
   S.setdefault("_local_h1_runtime_verified",{})[symbol]={
    "verified_at":time.time(),"observed_at_ms":int(now_ms),
    "last_candle_time":int(analysis.get("last_candle_time") or 0),
    "entry_side":int(analysis.get("entry_side") or 0),
    "signal_candle_time":int(analysis.get("signal_candle_time") or 0),
    "pivot_candle_time":int(analysis.get("pivot_candle_time") or 0),
    "pivot_type":analysis.get("pivot_type"),"pivot_price":analysis.get("pivot_price")}
 changed=(not prior or prior.get("policy")!=analysis.get("policy")
  or analysis.get("signal_candle_time")!=prior.get("signal_candle_time")
  or prior.get("pivot_type")!=analysis.get("pivot_type") or prior.get("pivot_price")!=analysis.get("pivot_price"))
 stamp=time.time()
 with LOCK:last=float(S.setdefault("_local_h1_persist_epoch",{}).get(symbol,0) or 0)
 if changed or stamp-last>=30:
  with pg() as db:
   with db.transaction():
    STORE.fence(db)
    db.execute("insert into local_h1_direction(symbol,analysis) values(%s,%s::jsonb) on conflict(symbol) do update set analysis=excluded.analysis",
      (symbol,json.dumps(analysis)))
  with LOCK:
   S.setdefault("local_h1_direction",{})[symbol]=copy.deepcopy(analysis)
   S["_local_h1_persist_epoch"][symbol]=stamp
 return analysis

def _local_persisted_anchor(symbol):
 # Universal H1 anchor resolver. Never select by write/arrival time: deployments,
 # watches or positions can contain an older H1 anchor than the newest confirmed
 # observation. Active direction is the confirmed candidate with the greatest
 # H1 signal time (pivot time is the tie-breaker).
 candidates=[]
 def add_candidate(source,origin):
  if not source:return
  features=copy.deepcopy(source.get("features") or source.get("context") or source.get("analysis") or source)
  side=int(source.get("side") or features.get("entry_side") or 0)
  if side not in (-1,1):return
  pivot_price=features.get("pivot_price")
  if pivot_price is None:return
  signal=int(features.get("signal_candle_time") or features.get("origin_h1_signal_candle")
   or source.get("signal_candle_time") or source.get("origin_signal_candle") or source.get("candle_time") or 0)
  pivot=int(features.get("pivot_candle_time") or signal or 0)
  if signal<=0:return
  candidates.append({"ready":True,"persisted":True,"anchor_confirmed":True,"h1_direction_anchor":True,
   "pivot_type":features.get("pivot_type") or ("LOCAL_HIGH" if side<0 else "LOCAL_LOW"),
   "pivot_price":pivot_price,"entry_side":side,"signal_candle_time":signal,"pivot_candle_time":pivot,
   "policy":features.get("policy"),"entry_blocked":False,"pending_pivot_type":None,"pending_pivot_price":None,
   "entry_block_reason":None,"reason":"persisted_confirmed_h1_local","anchor_source":origin})

 with LOCK:
  add_candidate(copy.deepcopy(S.get("local_h1_direction",{}).get(symbol)),"memory_canonical")
  add_candidate(copy.deepcopy(S.get("local_v12_positions",{}).get(symbol)),"open_position")
  add_candidate(copy.deepcopy(S.get("local_experiment_watch",{}).get(symbol)),"reentry_watch")
 try:
  with pg() as db:
   durable=db.execute("select analysis from local_h1_direction where symbol=%s",(symbol,)).fetchone()
   if durable:add_candidate(durable,"durable_canonical")
   # Sort by the actual H1 signal time, NOT journal write time.
   rows=db.execute("""select side,candle_time,features from local_v12_signal_journal
     where features->>'symbol'=%s and action in ('OBSERVE','OPEN','REENTRY')
     order by coalesce(nullif(features->>'signal_candle_time','')::bigint,candle_time) desc,
              coalesce(nullif(features->>'pivot_candle_time','')::bigint,0) desc, ts desc
     limit 12""",(symbol,)).fetchall()
   for row in rows:add_candidate(row,"signal_journal")
   # Executed trades are another durable proof of the H1 anchor used at entry.
   trades=db.execute("""select side,features from local_v12_trade_history
     where symbol=%s order by coalesce(nullif(features->>'signal_candle_time','')::bigint,0) desc, closed desc
     limit 6""",(symbol,)).fetchall()
   for row in trades:add_candidate(row,"trade_history")
 except Exception:
  pass
 if not candidates:return None
 candidates.sort(key=lambda x:(int(x.get("signal_candle_time") or 0),int(x.get("pivot_candle_time") or 0)),reverse=True)
 best=copy.deepcopy(candidates[0])
 best["anchor_candidates_checked"]=len(candidates)
 return best

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
def _local_experiment_watch_observe(symbol,watch,mark,execution_context,flow,stamp):
 updated=local4_update_watch(watch,mark,execution_context,flow,stamp)
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
def local_experiment_open(symbol,side,analysis,entry_kind="ORDER_FLOW",execution_context=None,watch=None):
 def reject(reason):
  payload={"symbol":symbol,"reason":reason,"at":now(),"entry_kind":entry_kind,
    "signal_candle_time":(analysis or {}).get("signal_candle_time")}
  with LOCK:
   previous=S.setdefault("strategy1_executor_rejections",{}).get(symbol) or {}
   S["strategy1_executor_rejections"][symbol]=payload
  if previous.get("reason")!=reason or previous.get("signal_candle_time")!=payload["signal_candle_time"]:
   try:journal("strategy1_entry_rejected",None,payload)
   except Exception:pass
  return False
 if symbol not in set(strategy1_trade_symbols()) or int(side or 0) not in (-1,1):return reject("ENTRY_STATE_REVALIDATION_FAILED")
 if not strategy1_confirmed_h1(analysis):return reject("H1_NOT_CONFIRMED")
 # Fail closed for NEW risk until this runtime has revalidated the current H1 book.
 # Hydrated/persisted anchors may manage existing risk but may not create fresh risk.
 if not strategy1_runtime_h1_verified(symbol,analysis):return reject("CURRENT_CLOSED_H1_NOT_VERIFIED")
 if S.get("mode")!="PAPER_ONLY" or S.get("orders_enabled") or not analysis.get("ready"):return reject("ENTRY_STATE_REVALIDATION_FAILED")
 if not analysis.get("h1_direction_anchor") or int(analysis.get("entry_side") or 0)!=int(side):return reject("ENTRY_STATE_REVALIDATION_FAILED")
 if analysis.get("entry_blocked"):return reject("ENTRY_STATE_REVALIDATION_FAILED")
 # Recheck at allocation time: scanning many markets and database writes take time.
 # Revalidate the H1 side plus fresh executed-flow executed control before adding risk.
 stamp=time.time()
 flow=MARKET_OBS.flow_context(symbol,stamp)
 selection=(local4_entry_candidate(symbol,analysis,execution_context,flow,stamp) if entry_kind=="REENTRY"
            else local4_initial_entry_candidate(symbol,analysis,execution_context,flow,stamp))
 if not selection["eligible"]:return reject(selection["reason"])
 with LOCK:current_anchor=copy.deepcopy(S.get("local_h1_direction",{}).get(symbol))
 if current_anchor and (int(current_anchor.get("entry_side") or 0)!=int(side) or
     int(current_anchor.get("signal_candle_time") or 0)!=int(analysis.get("signal_candle_time") or 0)):return reject("ENTRY_STATE_REVALIDATION_FAILED")
 price=current_entry_price(symbol)
 if price is None:return reject("CURRENT_SYMBOL_MARK_OR_CHECKPOINT_UNAVAILABLE")
 if entry_kind=="REENTRY":
  if not watch or int(watch.get("side") or 0)!=int(side):return reject("ENTRY_STATE_REVALIDATION_FAILED")
  if int(analysis.get("entry_side") or 0)==-int(side):return reject("ENTRY_STATE_REVALIDATION_FAILED")
  with LOCK:live_watch=copy.deepcopy(S.get("local_experiment_watch",{}).get(symbol))
  if not live_watch or live_watch.get("exit_at")!=watch.get("exit_at"):return reject("ENTRY_STATE_REVALIDATION_FAILED")
  if not local4_reentry_ready(side,execution_context,price,live_watch,flow,stamp):return reject("WAIT_REENTRY_RESUMPTION")
 with LOCK:instrument=copy.deepcopy(S.get("_bybit_instruments",{}).get(symbol))
 if not instrument or time.time()-float(instrument.get("observed_at",0))>86400:return reject("BYBIT_CONTRACT_CONSTRAINTS_UNAVAILABLE")
 leverage=min(25.0,float(instrument["max_leverage"]))
 with LOCK:allocation_blocked=not S.get("engine_active") or symbol in S.get("local_v12_positions",{})
 if allocation_blocked:return reject("ENGINE_STANDBY_OR_POSITION_ALREADY_OPEN")
 # No arbitrary cap on sequential entries; one active position per symbol remains.
 with LOCK:
  held_symbols=tuple(S.get("local_v12_positions",{}))
  received=dict(S.get("_price_received_epoch",{}))
 if any(not 0<=time.time()-received.get(held,0)<=10 for held in held_symbols):
  # Do not block a new PAPER entry because an unrelated open symbol missed a
  # single mark update. Margin accounting can use the position's last mark;
  # only the symbol being opened must have a fresh current_entry_price above.
  pass
 equity,used,free=_local_experiment_margin_state()
 if equity<=0 or free<0.01:return reject("INSUFFICIENT_FREE_MARGIN")
 target_notional=equity*LOCAL_EXPERIMENT_MARGIN_FRACTION*leverage
 max_margin_per_position=equity*LOCAL_EXPERIMENT_MARGIN_FRACTION
 desired_margin=max_margin_per_position
 # Each new position receives 20% of CURRENT mark-to-market equity at 25x.
 # Five full positions can consume the initial $500. Further positions become
 # possible only when realized/unrealized profits create additional free equity.
 # Entry must reserve its own modeled entry/exit fees as well as margin.
 margin=min(desired_margin,free/(1.0+2.0*FEE*leverage))
 if margin<0.01:return reject("INSUFFICIENT_FREE_MARGIN")
 notional=margin*leverage
 exposure_fill_ratio=(notional/target_notional) if target_notional>0 else 0.0
 price=float(price);opened=now();epoch=time.time()
 reentries=(int(watch.get("reentries") or 0)+1) if entry_kind=="REENTRY" and watch else 0
 origin_signal=int(analysis.get("signal_candle_time") or 0)
 claim_token=int((execution_context or {}).get("candle_time") or origin_signal)
 features={**analysis,"symbol":symbol,"strategy_name":"Caterpillar 1.0","experiment":"Caterpillar 1.0",
  "policy":HYPE_SWING_POLICY,"caterpillar_policy":LOCAL4_FLOW_POLICY,"entry_kind":entry_kind,
  "candidate_selection":selection,
  "origin_h1_signal_candle":origin_signal,"swing_reentries":reentries,
  "reference_margin_fraction":LOCAL_EXPERIMENT_MARGIN_FRACTION,"reference_leverage":25.0,
  "target_notional":target_notional,"desired_margin":desired_margin,"max_margin_per_position":max_margin_per_position,
  "actual_margin":margin,"free_margin_before":free,"mark_to_market_equity_at_entry":equity,
  "exposure_fill_ratio":exposure_fill_ratio,"leverage":leverage,"leverage_source":"bybit_instruments_info",
  "mfe_price_move":0.0,"mae_price_move":0.0,"mfe_roe_pct":0.0,"mae_roe_pct":0.0,
  "entry_mark":price,"profit_lock_armed":False,
  "pressure_state":{"best":int(side)*price,"noise":float((((watch or {}).get("context") or {}).get("resumption_state") or {}).get("noise") or 0.),
    "barrier":(-float((((watch or {}).get("context") or {}).get("resumption_state") or {}).get("candidate",{}).get("retest_best")) if (((watch or {}).get("context") or {}).get("resumption_state") or {}).get("candidate",{}).get("retest_best") is not None else None),"phase":"HOLDING"},
  "profit_lock_mode":"m1_executed_flow_weakening",
  
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
   if not claim:return reject("SIGNAL_ALREADY_EXECUTED")
   row=db.execute("""insert into local_v12_positions(symbol,side,entry,notional,margin,leverage,opened,opened_epoch,signal_candle_time,features)
     values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict(symbol) do nothing returning symbol""",
     (symbol,int(side),price,notional,margin,leverage,opened,epoch,origin_signal,json.dumps(features,default=str))).fetchone()
   if not row:raise psycopg.Rollback()
   if entry_kind=="REENTRY":db.execute("delete from local_v12_watchlist where symbol=%s",(symbol,))
   db.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'local_experiment_trade_opened',%s::jsonb)",
    (now(),json.dumps({"strategy":"local_12token_h1_execution_context","symbol":symbol,"side":int(side),"entry_kind":entry_kind,
      "entry":price,"reason":selection["reason"],"signal_candle_time":origin_signal,
      "margin":margin,"notional":notional,"target_notional":target_notional,
      "exposure_fill_ratio":exposure_fill_ratio,"leverage":leverage,"equity":equity,"free_margin_before":free},default=str)))
 if not row:return reject("POSITION_WRITE_CONFLICT")
 with LOCK:
  S.setdefault("local_v12_positions",{})[symbol]=pos
  if entry_kind=="REENTRY":S.setdefault("local_experiment_watch",{}).pop(symbol,None)
 log_learning_decision("LOCAL12:%s:%s:%s:%s"%(symbol,entry_kind,claim_token,int(side)),
   "local_12token_h1_execution_context",symbol,side,"OPEN" if entry_kind!="REENTRY" else "REENTRY",
   "confirmed_local_entry",price,None,leverage,features,opened)
 return True

@account_mutation
def local_experiment_close(symbol,price,reason,analysis=None,watch_context=None):
 with LOCK:pos=copy.deepcopy(S.get("local_v12_positions",{}).get(symbol))
 if not pos:return None
 price=float(price);pnl=paper_pnl(pos["notional"],pos["entry"],price,pos["side"],FEE)
 if reason!="operator_paper_close" and pnl<0:
  try:journal("strategy1_negative_close_blocked",None,{"symbol":symbol,"reason":reason,"pnl":pnl,"entry":pos["entry"],"mark":price,"side":pos["side"]})
  except Exception:pass
  return {"symbol":symbol,"pnl":pnl,"reason":reason,"blocked":True,"block_reason":"NEGATIVE_NET_PNL"}
 features=copy.deepcopy(pos.get("features") or {})
 if analysis:features["exit_analysis"]=analysis
 if watch_context:features["executed_flow_exit_context"]=watch_context
 features["actual_exit_reason"]=reason;features["actual_exit_mark"]=price
 watch=None
 if reason in ("m1_m3_m5_dominance_mfe_exit","m1_mfe_preservation_exit","m1_counterflow_exit","m1_m3_m5_mfe_preservation_exit","m1_m3_m5_risk_exit","m1_m3_confirmed_counterflow_exit"):
  watch={"symbol":symbol,"side":int(pos["side"]),
   "origin_signal_candle":int(features.get("origin_h1_signal_candle") or pos.get("signal_candle_time") or 0),
   "exit_price":price,"exit_at":now(),"expires_epoch":0.0,
   "reentries":int(features.get("swing_reentries",0) or 0),"context":{**copy.deepcopy(watch_context or {}),"exit_pressure_state":copy.deepcopy(features.get("pressure_state") or {})}}
  # Preserve the exchange timestamp of the opposite executed-flow event so
  # Caterpillar re-entry can only happen on a later M1/M3/M5 resumption.
  opposite_flow_exit=True
  flow_at_exit=(watch_context or {}).get("flow_context") or {}
  try:
   opposite_epoch=float(flow_at_exit["volume_window_end_epoch"])-float(flow_at_exit["latest_trade_age_seconds"])
   if not math.isfinite(opposite_epoch):opposite_epoch=None
  except (KeyError,TypeError,ValueError,OverflowError):opposite_epoch=None
  confirmed_opposite=bool(opposite_flow_exit and opposite_epoch is not None)
  watch["context"].update(phase="WAIT_RESUMPTION" if confirmed_opposite else "WAIT_PULLBACK",
    counter_pressure_seen=confirmed_opposite,caterpillar_policy=LOCAL4_FLOW_POLICY)
  if confirmed_opposite:watch["context"]["last_opposite_trade_epoch"]=opposite_epoch
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
     (now(),json.dumps({"strategy":"local_12token_h1_execution_context","symbol":symbol,"side":pos["side"],"entry":pos["entry"],
       "exit":price,"pnl":pnl,"reason":reason,"equity":float(acct["equity"]),"watch_armed":bool(watch),
       "leverage":pos["leverage"],"exposure_fill_ratio":features.get("exposure_fill_ratio")},default=str)))
 with LOCK:
  S.setdefault("local_v12_positions",{}).pop(symbol,None)
  if watch:S.setdefault("local_experiment_watch",{})[symbol]=watch
  S["local_experiment_equity"]=float(acct["equity"])
  S["local_experiment_realized_pnl"]=float(acct["realized_pnl"])
  S["local_experiment_trades"]=int(S.get("local_experiment_trades",0) or 0)+1
 log_learning_decision("LOCAL12:CLOSE:%s:%s"%(symbol,pos.get("opened")),
   "local_12token_h1_execution_context",symbol,pos["side"],"CLOSED",reason,pos["entry"],None,
   pos["leverage"],features,pos.get("opened"))
 return {"symbol":symbol,"pnl":pnl,"reason":reason,"equity":float(acct["equity"])}

@account_mutation
def local_experiment_mark_positions(prices):
 with LOCK:
  received=dict(S.get("_price_received_epoch",{}))
  prices={symbol:price for symbol,price in prices.items() if 0<=time.time()-received.get(symbol,0)<=10}
 with LOCK:positions=copy.deepcopy(S.get("local_v12_positions",{}))
 for symbol,pos in positions.items():
  mark=prices.get(symbol)
  if not mark:continue
  updated,liq=hype_update_path(pos,float(mark))
  f=updated.setdefault("features",{})
  # Strategy 1 MFE protection: preserve trend profits; exits are confirmed by executed-flow control transfer.
  entry=float(updated.get("entry") or 0);side=int(updated.get("side") or 0);markf=float(mark)
  move=side*(markf/entry-1.0) if entry>0 and side in (-1,1) else 0.0
  mfe=max(float(f.get("mfe_price_move",0) or 0),move)
  f["mfe_price_move"]=mfe;f["mfe_roe_pct"]=mfe*float(updated.get("leverage") or 25.0)*100.0
  f.update(caterpillar_policy=LOCAL4_FLOW_POLICY,profit_lock_armed=False,
    profit_lock_mode="m1_executed_flow_weakening",profit_lock_floor_move=None,
    current_price_move=move,mfe_giveback_move=max(0.0,mfe-move))
  with LOCK:
   live=S.get("local_v12_positions",{}).get(symbol)
   if live and live.get("opened")==pos.get("opened"):S["local_v12_positions"][symbol]=updated
  with LOCK:anchor=copy.deepcopy(S.get('_local4_analysis',{}).get(symbol) or {})
  if strategy1_runtime_h1_verified(symbol,anchor) and int(anchor.get('entry_side') or 0)==-int(pos['side']) and int(anchor.get('signal_candle_time') or 0)>int(pos.get('signal_candle_time') or 0):
   local_experiment_close(symbol,float(mark),'opposite_confirmed_h1_local',anchor)
   continue
  flow=MARKET_OBS.flow_context(symbol,time.time())
  reason=local4_pressure_exit(updated,None,float(mark),flow)
  with LOCK:
   if S.get("local_v12_positions",{}).get(symbol,{}).get("opened")==pos.get("opened"):
    S["local_v12_positions"][symbol]=updated
  if reason:
   local_experiment_close(symbol,float(mark),reason,watch_context={"flow_context":flow,"observed_at":now()})
   continue
  stamp=time.time()
  with LOCK:last=float(S.setdefault("_local_experiment_path_persist_epoch",{}).get(symbol,0) or 0)
  if stamp-last<30:continue
  with pg() as db:
   with db.transaction():
    STORE.fence(db)
    db.execute("update local_v12_positions set features=%s::jsonb where symbol=%s and opened=%s",
      (json.dumps(updated["features"]),symbol,pos["opened"]))
  with LOCK:S["_local_experiment_path_persist_epoch"][symbol]=stamp

def _local_entry_resumption_context(symbol,side,analysis,flow):
 # Exact operator rule: do not chase an already-running move. First observe
 # opposite M1 executed-flow, then enter on the first flip back to the H1 side.
 if int(side or 0) not in (-1,1) or not isinstance(flow,dict) or not flow.get("trade_data_fresh"):
  return None
 try:
  coverage=float(flow.get("trade_coverage_seconds") or 0)
  raw180=float(flow.get("flow_imbalance_180s"))
  raw300=float(flow.get("flow_imbalance_300s"))
  price300=float(flow.get("price_return_300s"))
 except (TypeError,ValueError,OverflowError):
  return None
 if coverage<300 or not all(math.isfinite(x) for x in (raw180,raw300,price300)):
  with LOCK:S.setdefault("_local_entry_flow_state",{}).pop(symbol,None)
  return None
 try:
  value=float(flow.get("flow_imbalance"))
  value180=float(flow.get("flow_imbalance_180s"))
  value300=float(flow.get("flow_imbalance_300s"))
 except (TypeError,ValueError,OverflowError):return None
 if not all(math.isfinite(x) for x in (value,value180,value300)):return None
 aligned_values=(float(side)*value,float(side)*value180,float(side)*value300)
 votes=[1 if x>0 else -1 if x<0 else 0 for x in aligned_values]
 vote_sum=sum(votes)
 sign=1 if vote_sum>0 else -1 if vote_sum<0 else 0
 signal=int((analysis or {}).get("signal_candle_time") or 0)
 with LOCK:
  states=S.setdefault("_local_entry_flow_state",{})
  state=copy.deepcopy(states.get(symbol) or {})
  if int(state.get("side") or 0)!=int(side) or int(state.get("signal_candle_time") or 0)!=signal:
   state={"side":int(side),"signal_candle_time":signal,"counter_seen":False,"last_sign":0}
  prior=int(state.get("last_sign") or 0)
  if sign<0:state["counter_seen"]=True
  ready=bool(state.get("counter_seen") and sign>0 and prior<=0)
  state["last_sign"]=sign
  state["last_flow_imbalance"]=value
  state["last_flow_imbalance_180s"]=value180
  state["last_flow_imbalance_300s"]=value300
  state["last_dominance_vote"]=sign
  state["updated_at"]=time.time()
  states[symbol]=state
 if not ready:return None
 try:event_epoch=float(flow.get("volume_window_end_epoch"))-float(flow.get("latest_trade_age_seconds"))
 except (TypeError,ValueError,OverflowError):event_epoch=time.time()
 return {"resumption_observed":True,"flow_imbalance":value,"flow_imbalance_180s":value180,
   "flow_imbalance_300s":value300,"dominance_vote":sign,"flow_event_epoch":event_epoch}

@account_mutation
def local4_fast_entries(prices):
 # H1 sets direction. Execution happens only on live M1 control transitions:
 # counter-flow -> H1-side resumption. M3/M5 are telemetry, never gates.
 for symbol in strategy1_trade_symbols():
  with LOCK:
   if symbol in S.get("local_v12_positions",{}):continue
   analysis=copy.deepcopy(S.get("_local4_analysis",{}).get(symbol))
   watch=copy.deepcopy(S.get("local_experiment_watch",{}).get(symbol))
  mark=prices.get(symbol)
  if not analysis or not mark:continue
  if not strategy1_runtime_h1_verified(symbol,analysis):continue
  side=int(analysis.get("entry_side") or 0)
  if watch and int(watch.get("side") or 0)==-side:
   _local_experiment_watch_clear(symbol,"opposite_h1_pivot_invalidated_watch");watch=None
  flow=MARKET_OBS.flow_context(symbol,time.time())
  if watch:
   watch=_local_experiment_watch_observe(symbol,watch,float(mark),None,flow,time.time())
   if local4_reentry_ready(side,None,mark,watch,flow,time.time()):
    local_experiment_open(symbol,side,analysis,"REENTRY",{"resumption_observed":True},watch)
  else:
   transition=_local_entry_resumption_context(symbol,side,analysis,flow)
   if transition and local4_initial_entry_candidate(symbol,analysis,transition,flow,time.time())["eligible"]:
    local_experiment_open(symbol,side,analysis,"ORDER_FLOW",transition)

def strategy1_entry_diagnostic_snapshot(prices):
 # Read-only decision audit: one structured record per candidate every 30 seconds.
 # This does NOT create orders, alter trading gates or introduce strategies.
 rows=[]
 for symbol in strategy1_runtime_symbols():
  with LOCK:
   analysis=copy.deepcopy(S.get("_local4_analysis",{}).get(symbol))
   position=copy.deepcopy(S.get("local_v12_positions",{}).get(symbol))
   watch=copy.deepcopy(S.get("local_experiment_watch",{}).get(symbol))
  record={"symbol":symbol,"h1_ready":strategy1_confirmed_h1(analysis),
          "position_open":bool(position),"watch_active":bool(watch),
          "entry_side":(analysis or {}).get("entry_side"),
          "executor_rejection":copy.deepcopy(S.get("strategy1_executor_rejections",{}).get(symbol))}
  try:
   if position:
    record["reason"]="POSITION_ALREADY_OPEN"
   elif not record["h1_ready"]:
    record["reason"]="H1_NOT_CONFIRMED_OR_BLOCKED"
   elif not prices.get(symbol):
    record["reason"]="MARK_UNAVAILABLE"
   elif not strategy1_runtime_h1_verified(symbol,analysis):
    record["reason"]="H1_RUNTIME_VERIFICATION_NOT_READY"
   elif not S.get("engine_active"):
    record["reason"]="ENGINE_STANDBY"
   elif symbol not in S.get("_bybit_instruments",{}):
    record["reason"]="BYBIT_CONTRACT_CONSTRAINTS_UNAVAILABLE"
   else:
    flow=MARKET_OBS.flow_context(symbol,time.time())
    record.update({"trade_data_fresh":bool(flow.get("trade_data_fresh")),
      "latest_trade_age_seconds":flow.get("latest_trade_age_seconds"),
      "coverage_seconds":flow.get("trade_coverage_seconds"),
      "flow_stream":flow.get("flow_imbalance"),
      "pressure_phase":flow.get("pressure_phase")})
    if watch:
     ctx=watch.get("context") or {}
     record["watch_phase"]=ctx.get("phase")
     record["counter_pressure_seen"]=bool(ctx.get("counter_pressure_seen"))
     record["reason"]="REENTRY_READY" if local4_reentry_ready(
       int(analysis.get("entry_side") or 0),None,prices[symbol],watch,flow,time.time()
       ) else "WAIT_REENTRY_COUNTERFLOW_OR_RESUMPTION"
    else:
     selection=local4_initial_entry_candidate(symbol,analysis,None,flow,time.time())
     record["reason"]="ENTRY_SIGNAL_READY" if selection.get("eligible") else selection.get("reason","UNCLASSIFIED")
  except Exception as exc:
   record["reason"]="DIAGNOSTIC_ERROR"
   record["error"]=type(exc).__name__+":"+str(exc)[:140]
  rows.append(record)
 summary={}
 for row in rows:
  reason=row["reason"];summary[reason]=summary.get(reason,0)+1
 with LOCK:stream_state={k:copy.deepcopy(v) for k,v in S.get("sources",{}).items() if k.startswith("MarketTradeStream:")}
 snapshot={"at":now(),"symbols":len(rows),"reason_counts":summary,"tokens":rows,"trade_streams":stream_state}
 with LOCK:S["strategy1_entry_diagnostics"]=snapshot
 try:journal("strategy1_entry_diagnostics",None,snapshot)
 except Exception as exc:
  with LOCK:S["strategy1_entry_diagnostics_error"]=type(exc).__name__+":"+str(exc)[:140]
 return snapshot

def local_experiment_risk_loop():
 # Protect observed peaks even while H1/execution context history fetches or scans are slow.
 # Use only fresh streamed/cached marks; never spend additional REST budget.
 last_entry_diagnostics=0.0
 while not SHUTDOWN.is_set():
  try:
   with LOCK:
    active=bool(S.get("engine_active")) and S.get("mode")=="PAPER_ONLY" and not S.get("orders_enabled")
    age=time.time()-float(S.get("_last_poll_epoch",0) or 0)
    prices=dict(S.get("_prices",{}))
   if active and 0<=age<=8 and prices:
    local_experiment_mark_positions(prices)
    local4_fast_entries(prices)
    if S11 is not None:S11.cycle(strategy1_runtime_symbols(),prices)

    with LOCK:S["sources"]["LocalRisk"]={"ok":True,"ready":True,"last_check":now(),"mode":"H1_STREAM_fast_paper_execution","symbols":list(strategy1_trade_symbols()),"error":None}
   if time.time()-last_entry_diagnostics>=30:
    last_entry_diagnostics=time.time()
    strategy1_entry_diagnostic_snapshot(prices)
  except LeaseLost as exc:
   with LOCK:
    S["engine_active"]=False;S["engine_error"]=str(exc)
  except Exception as exc:
   with LOCK:S["sources"]["LocalRisk"]={"ok":False,"last_check":now(),"error":type(exc).__name__+":"+str(exc)[:160]}
  TRADE_WAKE.wait(1)
  TRADE_WAKE.clear()

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

def strategy1_live_state_loop():
 # Process-independent Strategy 1 mark-to-market snapshot for the monitor.
 # The lease owner publishes one compact row per second from the live allMids cache.
 while not SHUTDOWN.is_set():
  try:
   with LOCK:
    active=bool(S.get("engine_active"))
    prices=copy.deepcopy(S.get("_prices",{}))
    price_epoch=float(S.get("_last_poll_epoch",0) or 0)
    positions=copy.deepcopy(S.get("local_v12_positions",{}))
    realized_equity=float(S.get("local_experiment_equity",LOCAL_EXPERIMENT_STARTING_EQUITY) or LOCAL_EXPERIMENT_STARTING_EQUITY)
   if active and prices and price_epoch>0:
    pos_state={};unreal=0.0
    for symbol,pos in positions.items():
     mark=float(prices.get(symbol,pos.get("entry",0)) or pos.get("entry",0) or 0)
     pnl=paper_pnl(float(pos.get("notional",0) or 0),float(pos.get("entry",0) or 0),mark,int(pos.get("side",0) or 0),FEE) if mark>0 else 0.0
     unreal+=pnl
     pos_state[symbol]={"side":int(pos.get("side",0) or 0),"entry":float(pos.get("entry",0) or 0),
      "mark":mark,"margin":float(pos.get("margin",0) or 0),"notional":float(pos.get("notional",0) or 0),
      "leverage":float(pos.get("leverage",25) or 25),"opened":pos.get("opened"),"unrealized_pnl":pnl,
      "features":copy.deepcopy(pos.get("features") or {})}
    age=max(0.0,time.time()-price_epoch)
    payload_prices={s:float(prices[s]) for s in LOCAL_EXPERIMENT_SYMBOLS if s in prices}
    with pg() as db:
     with db.transaction():
      STORE.fence(db)
      db.execute("""insert into local_v12_live_state(id,ts,commit,prices,positions,unrealized_pnl,total_equity,price_age_seconds,source)
       values(1,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,'bybit_v5_public_linear')
       on conflict(id) do update set ts=excluded.ts,commit=excluded.commit,prices=excluded.prices,
       positions=excluded.positions,unrealized_pnl=excluded.unrealized_pnl,total_equity=excluded.total_equity,
       price_age_seconds=excluded.price_age_seconds,source=excluded.source""",
       (now(),os.getenv("RENDER_GIT_COMMIT"),json.dumps(payload_prices),json.dumps(pos_state,default=str),
        unreal,realized_equity+unreal,age))
    with LOCK:S["last_checkpoint"]=now()
    with LOCK:S["strategy1_live_state"]={"ts":now(),"price_age_seconds":age,"prices":payload_prices,
      "unrealized_pnl":unreal,"total_equity":realized_equity+unreal,"positions":pos_state}
  except Exception as exc:
   with LOCK:S["sources"]["Strategy1LiveState"]={"ok":False,"last_check":now(),
     "error":type(exc).__name__+":"+str(exc)[:160]}
  else:
   with LOCK:S["sources"]["Strategy1LiveState"]={"ok":True,"last_check":now(),
     "mode":"durable_1s_bybit_marks","interval_seconds":1}
  SHUTDOWN.wait(1)

def bybit_local_history(symbol,interval="1h",limit=120):
 """Read-only Bybit V5 kline bootstrap converted to the legacy candle shape."""
 bybit_interval="60" if interval=="1h" else None
 if not bybit_interval:raise ValueError("unsupported_bybit_interval:"+str(interval))
 url="https://api.bybit.com/v5/market/kline?"+urllib.parse.urlencode({
  "category":"linear","symbol":str(symbol)+"USDT","interval":bybit_interval,"limit":int(limit)})
 req=urllib.request.Request(url,headers={"User-Agent":"PANDORA-paper/1.0","Accept":"application/json"})
 with urllib.request.urlopen(req,timeout=12) as resp:payload=json.load(resp)
 if int(payload.get("retCode",0) or 0)!=0:raise RuntimeError("bybit_kline_retCode_"+str(payload.get("retCode")))
 raw=(payload.get("result") or {}).get("list") or []
 rows=[]
 for x in reversed(raw):
  try:
   start=int(x[0]);rows.append({"s":str(symbol),"i":interval,"t":start,"T":start+int({"1h":3600000}[interval]),
    "o":str(x[1]),"h":str(x[2]),"l":str(x[3]),"c":str(x[4]),"v":str(x[5]),"n":0,"venue":"bybit"})
  except (IndexError,TypeError,ValueError):continue
 return rows

def strategy1_token_totals():
 # All-time ledger aggregates; display namespaces separately, never sum mirrored books.
 result=[]
 with pg() as db:
  for account,table in STRATEGY1_HISTORY_TABLES.items():
   if not _historical_table_exists(db,table):continue
   for row in db.execute(f"""select symbol,count(*) as closed_trades,
      coalesce(sum(pnl),0) as realized_pnl,sum(case when pnl>0 then 1 else 0 end) as wins
      from {table} group by symbol order by symbol""").fetchall():
    result.append({"account":account,**dict(row)})
 return result

def strategy1_history_page(account="strategy1",before_id=None,limit=100,symbol=None):
 if account not in STRATEGY1_HISTORY_TABLES:raise ValueError("unknown_account")
 limit=max(1,min(500,int(limit)));params=[];conditions=[]
 if before_id is not None:
  conditions.append("id < %s");params.append(int(before_id))
 if symbol:
  conditions.append("symbol = %s");params.append(str(symbol).upper())
 where=" where "+" and ".join(conditions) if conditions else ""
 params.append(limit+1)
 with pg() as db:
  if not _historical_table_exists(db,STRATEGY1_HISTORY_TABLES[account]):return {'account':account,'trades':[],'next_before_id':None,'symbol':symbol}
  rows=[dict(r) for r in db.execute(f"select * from {STRATEGY1_HISTORY_TABLES[account]}{where} order by id desc limit %s",tuple(params)).fetchall()]
 more=len(rows)>limit;rows=rows[:limit]
 return {"account":account,"trades":rows,"next_before_id":rows[-1]["id"] if rows and more else None,
  "basis":"all_recorded_rows_without_pnl_exclusions","symbol":symbol}

def strategy1_event_page(before_id=None,limit=100):
 limit=max(1,min(500,int(limit)));params=[]
 before=" and id < %s" if before_id is not None else ""
 if before_id is not None:params.append(int(before_id))
 params.append(limit+1)
 with pg() as db:
  rows=[dict(r) for r in db.execute("""select id,recorded_at,kind,payload from audit_journal
   where kind in ('local_experiment_trade_opened','local_experiment_trade_closed')"""+before+
   " order by id desc limit %s",tuple(params)).fetchall()]
 more=len(rows)>limit;rows=rows[:limit]
 return {"events":rows,"next_before_id":rows[-1]["id"] if rows and more else None}

def local_v10_history(limit=100):
 # Actual immutable account ledger, including all historical outcomes.
 with pg() as db:
  return [dict(x) for x in db.execute("""select id,opened,closed,symbol,side,entry,exit,pnl,
    reason,margin,notional,leverage,features from local_v12_trade_history
    order by closed desc,id desc limit %s""",(int(limit),)).fetchall()]

def local_v10_today_pnl():
 with pg() as db:
  return float(db.execute("""select coalesce(sum(pnl),0) as pnl from local_v12_trade_history
    where closed::timestamptz >= date_trunc('day',now())""").fetchone()["pnl"])

def engine_coordinator():
 while not SHUTDOWN.is_set():
  S['_coordinator_heartbeat']=time.time()
  try:
   owned=STORE.claim()
   if owned and not S['engine_active']:
    with ACCOUNT_LOCK:restore_state()
   with LOCK:S['engine_active']=owned;S['engine_error']=None if owned else 'standby: another engine owns the lease'
  except Exception as error:
   with LOCK:S['engine_active']=False;S['engine_error']=type(error).__name__+':'+str(error)[:160]
  SHUTDOWN.wait(5)
 with LOCK:S['engine_active']=False
 try:STORE.release()
 except Exception:pass

def market_history_bootstrap():
 while not SHUTDOWN.is_set():
  if not S['engine_active']:SHUTDOWN.wait(.5);continue
  for symbol in strategy1_runtime_symbols():
   if SHUTDOWN.is_set():return
   try:
    rows=bybit_local_history(symbol)
    accept_local_candles(rows,history=True)
    checkpoint_local_candles()
    with LOCK:S['sources']['H1History:'+symbol]={'ok':True,'last_check':now(),'rows':len(rows)}
   except Exception as error:
    with LOCK:S['sources']['H1History:'+symbol]={'ok':False,'last_check':now(),'error':type(error).__name__+':'+str(error)[:160]}
  SHUTDOWN.wait(30)

def local_experiment_loop():
 while not SHUTDOWN.is_set():
  if not S['engine_active']:SHUTDOWN.wait(.5);continue
  for symbol in strategy1_runtime_symbols():
   try:
    rows,stamp=_local_h1_candles(symbol);analysis=local_h1_direction(rows,stamp,symbol)
    with LOCK:S.setdefault('_local4_analysis',{})[symbol]=analysis
    if S11 is not None:S11.scan_h1(symbol,rows,stamp)
   except Exception as error:
    with LOCK:S['sources']['H1Scan:'+symbol]={'ok':False,'last_check':now(),'error':type(error).__name__+':'+str(error)[:140]}
  TRADE_WAKE.set();SHUTDOWN.wait(1)

def _stream_group(trades):
 count=2 if trades else max(1,min(8,int(os.getenv('BYBIT_AUX_WS_SHARDS','2'))))
 def symbols():return set(strategy1_runtime_symbols())
 def worker(index):
  key=('MarketTradeStream:' if trades else 'MarketQuotes:')+str(index)
  def report(state):
   with LOCK:S['sources'][key]={'last_check':now(),**state}
  def quote(prices):accept_market_prices(prices);TRADE_WAKE.set()
  stable_shard=lambda symbol:int(hashlib.sha1(str(symbol).encode()).hexdigest()[:8],16)%count
  run_bybit_stream(MARKET_OBS if trades else MARKET_AUX_OBS,SHUTDOWN,symbols,report,
   symbol_filter=None if trades else (lambda symbol:stable_shard(symbol)==index),
   candle_filter=lambda symbol:stable_shard(symbol)==index,
   subscribe_trades=trades,on_trade_mids=quote if trades else None,
   on_mids=None if trades else quote,on_candles=None if trades else accept_local_candles,
   candle_symbols=() if trades else symbols,worker_name=('trade-' if trades else 'quotes-')+str(index))
 threads=[threading.Thread(target=worker,args=(i,),daemon=True) for i in range(count)]
 for thread in threads:thread.start()
 SHUTDOWN.wait()
 for thread in threads:thread.join(3)

def market_trade_stream():_stream_group(True)
def market_aux_stream():_stream_group(False)

def health_state():
 stamp=time.time();tokens={}
 with LOCK:
  active=S['engine_active'];checkpoint=publication_epoch(S.get('last_checkpoint'))
  anchors=copy.deepcopy(S.get('_local4_analysis',{}));received=dict(S['_price_received_epoch'])
  instruments=copy.deepcopy(S.get('_bybit_instruments',{}))
 for symbol in LOCAL_EXPERIMENT_SYMBOLS:
  instrument=instruments.get(symbol) or {}
  tokens[symbol]={'h1':strategy1_runtime_h1_verified(symbol,anchors.get(symbol),stamp),
   'executed_flow':bool(MARKET_OBS.flow_context(symbol,stamp).get('trade_data_fresh')),
   'mark':0<=stamp-received.get(symbol,0)<=10,
   'contract':bool(instrument and 0<=stamp-float(instrument.get('observed_at',0))<=86400)}
 checkpoint_age=stamp-checkpoint if checkpoint else None
 healthy=not SHUTDOWN.is_set() and stamp-S.get('_coordinator_heartbeat',stamp)<45
 return {'healthy':healthy,'risk_ready':bool(healthy and active and checkpoint_age is not None and 0<=checkpoint_age<15 and all(all(r.values()) for r in tokens.values())),
  'engine_active':active,'engine_error':S.get('engine_error'),'mode':'PAPER_ONLY','version':os.getenv('RENDER_GIT_COMMIT','local-unpublished'),
  'token_readiness':tokens,'checkpoint_age_seconds':checkpoint_age,
  'market_age_seconds':stamp-S['_last_poll_epoch'] if S['_last_poll_epoch'] else None}

def _historical_table_exists(db,name):
 return db.execute('select to_regclass(%s) as name',(name,)).fetchone()['name'] is not None

def dashboard_history_loop():
 while not SHUTDOWN.is_set():
  try:
   value={'trades':local_v10_history(300),'token_totals':strategy1_token_totals(),
    'events':strategy1_event_page(limit=50),'at':now(),'error':None}
   with LOCK:S['_dashboard_history']=value
  except Exception as error:
   with LOCK:S.setdefault('_dashboard_history',{})['error']=type(error).__name__+':'+str(error)[:160]
  SHUTDOWN.wait(5)

def build_dashboard_snapshot(history=None):
 with LOCK:state=copy.deepcopy(S)
 history=history if history is not None else state.get('_dashboard_history',{})
 positions=[];unreal=0.;all_marks=True
 for symbol,pos in state['local_v12_positions'].items():
  stamp=state['_price_received_epoch'].get(symbol,0)
  mark=state['_prices'].get(symbol) if 0<=time.time()-stamp<=10 else None
  pnl=paper_pnl(pos['notional'],pos['entry'],mark,pos['side'],FEE) if mark is not None else None
  all_marks=all_marks and mark is not None
  if pnl is not None:unreal+=pnl
  positions.append({'symbol':symbol,'side':'LONG' if pos['side']>0 else 'SHORT','opened':pos['opened'],'entry':pos['entry'],
   'mark':mark,'unrealized_pnl':pnl,'margin_usd':pos['margin'],'notional_usd':pos['notional'],'leverage':pos['leverage'],'features':pos.get('features') or {}})
 details={}
 for symbol in strategy1_runtime_symbols():
  flow=MARKET_OBS.flow_context(symbol)
  anchor=state.get('_local4_analysis',{}).get(symbol) or state['local_h1_direction'].get(symbol) or {}
  details[symbol]={'h1_local':anchor,'flow_context':flow,'last_action':(state.get('strategy1_executor_rejections',{}).get(symbol) or {}).get('reason')}
 primary={'starting_equity':500.,'realized_equity':state['local_experiment_equity'],
  'realized_pnl':state['local_experiment_realized_pnl'],'unrealized_pnl':unreal if all_marks else None,
  'total_equity':state['local_experiment_equity']+unreal if all_marks else None,
  'open_positions':positions,'closed_trades':history.get('trades',[]),'token_totals':history.get('token_totals'),
  'events':history.get('events',{}),'watch':state['local_experiment_watch'],'h1_durable':state['local_h1_direction'],
  'engine':{'details':details,'symbols':list(strategy1_runtime_symbols())}}
 legacy=S11.snapshot() if S11 is not None else {}
 return {'strategy1_primary':primary,'strategy11_legacy':legacy,
  'local_experiment_symbols':list(strategy1_runtime_symbols()),'base_symbols':list(LOCAL_EXPERIMENT_SYMBOLS),
  'discovery':state.get('bybit_discovery',{}),
  'health':health_state(),'sources':state['sources'],'strategy1_entry_diagnostics':state.get('strategy1_entry_diagnostics',{}),
  'history_error':history.get('error'),'history_updated_at':history.get('at'),'positions':[],'snapshot_at':now()}

def dashboard():return build_dashboard_snapshot()
def html_dashboard(data):
 from strategy1_monitor import render
 return render(data)
def html_strategy1_only(data):return html_dashboard(data)

class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def send(self,code,result,content_type='application/json; charset=utf-8'):
  body=result.encode('utf-8') if isinstance(result,str) else json.dumps(result,ensure_ascii=False,default=str).encode('utf-8')
  self.send_response(code);self.send_header('Content-Type',content_type);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers()
  try:self.wfile.write(body)
  except (BrokenPipeError,ConnectionResetError):pass
 def do_GET(self):
  parsed=urllib.parse.urlsplit(self.path);args=urllib.parse.parse_qs(parsed.query);path=parsed.path
  try:
   if path in ('/health','/health/risk'):
    result=health_state();self.send(200 if result['healthy' if path=='/health' else 'risk_ready'] else 503,result)
   elif path=='/':self.send(200,html_dashboard(dashboard()),'text/html; charset=utf-8')
   elif path in ('/api/dashboard','/status'):self.send(200,dashboard())
   elif path in ('/api/strategy1/history','/strategy1/history'):
    result=strategy1_history_page(args.get('account',['strategy1'])[0],args.get('before',[None])[0],int(args.get('limit',['100'])[0]),args.get('symbol',[None])[0])
    if path=='/strategy1/history':
     from strategy1_monitor import render_history
     self.send(200,render_history(result),'text/html; charset=utf-8')
    else:self.send(200,result)
   elif path=='/api/strategy1/events':self.send(200,strategy1_event_page(args.get('before',[None])[0],int(args.get('limit',['100'])[0])))
   else:self.send(404,{'error':'not_found'})
  except (ValueError,TypeError):self.send(400,{'error':'invalid_request'})
  except Exception:self.send(503,{'error':'temporarily_unavailable','history_preserved':True})
 def do_POST(self):
  if self.path!='/api/positions/close':self.send(404,{'error':'not_found'});return
  secret=os.getenv('PANDORA_CONTROL_TOKEN','')
  if not secret or self.headers.get('Authorization')!='Bearer '+secret:self.send(401,{'error':'control_access_required'});return
  try:
   size=int(self.headers.get('Content-Length','0'))
   if not 0<size<=4096:raise ValueError('invalid_length')
   request=json.loads(self.rfile.read(size));symbols=list(S['local_v12_positions']) if request.get('all') else [request.get('symbol')]
   results=[]
   for symbol in symbols:
    price=current_entry_price(symbol)
    if price is None:results.append({'symbol':symbol,'error':'fresh_mark_unavailable'});continue
    results.append(local_experiment_close(symbol,price,'operator_paper_close'))
   self.send(200,{'results':results})
  except (ValueError,TypeError):self.send(400,{'error':'invalid_request'})
  except Exception:self.send(503,{'error':'close_not_confirmed'})

def main():
 pinit();server=ThreadingHTTPServer(('0.0.0.0',int(os.getenv('PORT','10000'))),Handler)
 def stop(signum,frame):SHUTDOWN.set();threading.Thread(target=server.shutdown,daemon=True).start()
 signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
 def supervise(label,callback):
  while not SHUTDOWN.is_set():
   try:callback()
   except Exception as error:
    with LOCK:S['sources'][label]={'ok':False,'last_check':now(),'error':type(error).__name__+':'+str(error)[:160]}
   SHUTDOWN.wait(1)
 jobs=[('lease',engine_coordinator),('contracts',bybit_instruments_loop),('discovery',bybit_volatility_discovery_loop),('trades',market_trade_stream),('quotes',market_aux_stream),
  ('h1_history',market_history_bootstrap),('h1_scan',local_experiment_loop),('execution',local_experiment_risk_loop),
  ('checkpoint',strategy1_live_state_loop),('history',dashboard_history_loop)]
 workers=[threading.Thread(target=supervise,args=job,daemon=True,name=job[0]) for job in jobs]
 for worker in workers:worker.start()
 try:server.serve_forever()
 finally:
  SHUTDOWN.set();server.server_close()
  for worker in workers:worker.join(3)
  try:STORE.release()
  except Exception:pass

if __name__=='__main__':main()
