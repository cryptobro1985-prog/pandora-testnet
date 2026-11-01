"""PANDORA PAPER: Pandora Win — H1 locals + rotating Bybit pump scanner + executed-flow control."""
import sys
from zoneinfo import ZoneInfo
from pandora_api import API_VERSION, openapi, json_safe
from pandora_decisions import entry_status, startup_snapshot
from pandora_bootstrap import HistoryBootstrap
from pandora_runtime import PandoraRuntime
from pandora_scanner import ticker_worker
from pandora_locals import live_locals, execution_anchor
from pandora_win_core import mark_metrics
from pandora_risk import RiskPolicy, plan_entry, position_guard, position_risk
from local_order_flow import flow_profile
import copy,datetime,functools,hashlib,html,json,math,os,re,signal,threading,time
import urllib.request,urllib.parse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import psycopg
from psycopg.rows import dict_row
from accounting import paper_pnl
from engine_store import EngineStore,LeaseLost
from market_data import RollingMarketData
from bybit_market_stream import run_bybit_stream
from h1_structure import analyze as analyze_pandora_h1,pending_extreme as local_pending_extreme,update_path as update_position_path,POLICY as PANDORA_LOCAL_POLICY
from local_order_flow import POLICY as PANDORA_FLOW_POLICY,entry_candidate as pandora_flow_entry_candidate,initial_entry_candidate as pandora_flow_initial_entry_candidate,pressure_exit as pandora_flow_pressure_exit,update_watch as pandora_flow_update_watch,reentry_ready as pandora_flow_reentry_ready

PANDORA_STARTING_EQUITY=500.0
PANDORA_MARGIN_FRACTION=.20
PANDORA_WIN_NAME="Pandora Win"
DISCOVERY_MAX_SELECTED=5
DISCOVERY_SCAN_SECONDS=1
FEE=.00045
LOCK=threading.RLock();ACCOUNT_LOCK=threading.RLock();SHUTDOWN=threading.Event();TRADE_WAKE=threading.Event()
START=time.time()
S={'mode':'PAPER_ONLY','orders_enabled':False,'engine_active':False,'engine_error':None,
 'sources':{},'_prices':{},'_price_received_epoch':{},'_timeline':{},'_hist':{},'_last_poll_epoch':0,
 'last_poll':None,'last_checkpoint':None,'last_market_error':None,'market_count':0,
 'pandora_win_positions':{},'pandora_watch':{},'pandora_win_h1_direction':{},'_pandora_analysis':{},
 'pandora_equity':500.,'pandora_realized_pnl':0.,'pandora_trades':0}
MARKET_OBS=RollingMarketData(max_symbols=256,max_trade_lag_seconds=15,freshness_seconds=15,max_seen_per_symbol=65536)
MARKET_AUX_OBS=RollingMarketData(max_symbols=64)
_LOCAL_CANDLE_CACHE={};_LOCAL_CANDLE_CACHE_LOCK=threading.RLock();_LOCAL_CANDLE_CHECKPOINTED={}

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()

def publication_epoch(value):
 try:return datetime.datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp()
 except (ValueError,TypeError):return None

def pg():return psycopg.connect(os.environ['DATABASE_URL'],autocommit=True,row_factory=dict_row,connect_timeout=5)
STORE=EngineStore(pg)
WIN=None
HISTORY_BOOTSTRAP=None

def journal(kind,event_id,payload):
 with pg() as db:db.execute('insert into pandora_win_audit_journal(recorded_at,event_id,kind,payload) values(%s,%s,%s,%s::jsonb)',(now(),event_id,kind,json.dumps(payload,default=str)))

def log_learning_decision(ident,strategy,symbol,side,action,reason,entry_price=None,score=None,leverage=1,features=None,ts=None):
 # Supplementary decision journal. The authoritative OPEN/CLOSE is atomic with the ledger.
 try:journal('pandora_decision',ident,dict(symbol=symbol,side=side,action=action,reason=reason,features=features or {}));return True
 except Exception:return False


SCHEMA=(
 "CREATE TABLE IF NOT EXISTS pandora_win_account_state(id integer PRIMARY KEY,equity double precision NOT NULL,realized_pnl double precision NOT NULL,started_at text NOT NULL,updated_at text NOT NULL)",
 "CREATE TABLE IF NOT EXISTS pandora_win_positions(symbol text PRIMARY KEY,side integer NOT NULL,entry double precision NOT NULL,notional double precision NOT NULL,margin double precision NOT NULL,leverage double precision NOT NULL,opened text NOT NULL,opened_epoch double precision NOT NULL,signal_candle_time bigint,features jsonb NOT NULL DEFAULT '{}'::jsonb)",
 "CREATE TABLE IF NOT EXISTS pandora_win_trade_history(id bigserial PRIMARY KEY,opened text,closed text,symbol text,side integer,entry double precision,exit double precision,pnl double precision,reason text,margin double precision,notional double precision,leverage double precision,features jsonb NOT NULL DEFAULT '{}'::jsonb)",
 "CREATE TABLE IF NOT EXISTS pandora_win_watchlist(symbol text PRIMARY KEY,side integer NOT NULL,origin_signal_candle bigint,exit_price double precision,exit_at text NOT NULL,expires_epoch double precision NOT NULL DEFAULT 0,reentries integer NOT NULL DEFAULT 0,context jsonb NOT NULL DEFAULT '{}'::jsonb)",
 "CREATE TABLE IF NOT EXISTS pandora_win_h1_direction(symbol text PRIMARY KEY,analysis jsonb NOT NULL)",
 "CREATE TABLE IF NOT EXISTS pandora_win_signal_journal(id text PRIMARY KEY,ts text NOT NULL,candle_time bigint,action text NOT NULL,side integer,price double precision,features jsonb NOT NULL DEFAULT '{}'::jsonb)",
 "CREATE TABLE IF NOT EXISTS pandora_win_audit_journal(id bigserial PRIMARY KEY,recorded_at text NOT NULL,event_id text,kind text NOT NULL,payload jsonb NOT NULL)",
 "CREATE TABLE IF NOT EXISTS pandora_win_candle_checkpoints(symbol text NOT NULL,interval text NOT NULL,candles jsonb NOT NULL,saved_at timestamptz NOT NULL DEFAULT clock_timestamp(),PRIMARY KEY(symbol,interval))",
 "CREATE TABLE IF NOT EXISTS pandora_win_live_state(id integer PRIMARY KEY,ts text NOT NULL,commit text,prices jsonb NOT NULL DEFAULT '{}'::jsonb,positions jsonb NOT NULL DEFAULT '{}'::jsonb,unrealized_pnl double precision NOT NULL DEFAULT 0,total_equity double precision NOT NULL DEFAULT 0,price_age_seconds double precision,source text)",
 "CREATE INDEX IF NOT EXISTS pandora_win_trade_closed_idx ON pandora_win_trade_history(closed DESC)",
 "CREATE INDEX IF NOT EXISTS pandora_win_audit_kind_time_idx ON pandora_win_audit_journal(kind,recorded_at)")

def restore_state():
 with pg() as db:
  account=db.execute('select * from pandora_win_account_state where id=1').fetchone()
  positions=db.execute('select * from pandora_win_positions').fetchall()
  watches=db.execute('select * from pandora_win_watchlist').fetchall()
  anchors=db.execute('select * from pandora_win_h1_direction').fetchall()
  count=db.execute('select count(*) n from pandora_win_trade_history').fetchone()['n']
 with LOCK:
  S['pandora_equity']=float(account['equity']);S['pandora_realized_pnl']=float(account['realized_pnl'])
  S['pandora_started_at']=account['started_at'];S['pandora_trades']=int(count)
  S['pandora_win_positions']={r['symbol']:{**dict(r),'t':float(r['opened_epoch'])} for r in positions}
  S['pandora_watch']={r['symbol']:dict(r) for r in watches}
  S['pandora_win_h1_direction']={r['symbol']:r['analysis'] for r in anchors}
  S['_pandora_analysis']=copy.deepcopy(S['pandora_win_h1_direction'])

def pinit():
 with pg() as db:
  with db.transaction():
   for query in SCHEMA:db.execute(query)
   db.execute('insert into pandora_win_account_state(id,equity,realized_pnl,started_at,updated_at) values(1,500,0,%s,%s) on conflict(id) do nothing',(now(),now()))
 EngineStore(pg).migrate()
 restore_state()
 global WIN
 WIN=PandoraRuntime(sys.modules[__name__])
 with pg() as db:
  seeds=db.execute("select candles from pandora_win_candle_checkpoints where interval in ('1h','15m')").fetchall()

 for row in seeds:
  rows=row['candles'] or []
  if rows and all(r.get('venue')=='bybit' for r in rows):accept_local_candles([{**r,'_live_ingestion':False} for r in rows],history=True)
 with LOCK:S['sources']['PersistentPostgres']={'ok':True,'last_check':now()}

def accept_local_candles(data,history=False):
 rows=data if isinstance(data,list) else [data]
 stamp=time.monotonic();wall=int(time.time()*1000)
 with _LOCAL_CANDLE_CACHE_LOCK:
  for row in rows:
   if not isinstance(row,dict) or row.get('i') not in ('1h','15m'):continue
   symbol=row.get('s')
   if symbol not in set(pandora_runtime_symbols()):continue
   try:
    t,T=int(row['t']),int(row['T']);o,h,l,c,v=[float(row[k]) for k in ('o','h','l','c','v')]
    if not all(math.isfinite(x) for x in (o,h,l,c,v)) or min(o,h,l,c)<=0 or v<0:continue
    expected=3600000 if row.get('i')=='1h' else 900000
    if not expected-1000<=T-t<=expected or not l<=min(o,c)<=max(o,c)<=h or t>wall+1000:continue
   except (KeyError,ValueError,TypeError):continue
   row={**row,'observed_at_ms':wall if row.get('_live_ingestion',True) else 0}
   key=(symbol,row.get('i'),120 if row.get('i')=='1h' else 48);old=_LOCAL_CANDLE_CACHE.get(key)
   merged={int(r['t']):r for r in old[1]} if old else {}
   previous_row=merged.get(t) or {}
   row['low_observed_at_ms']=previous_row.get('low_observed_at_ms',wall) if previous_row and float(previous_row['l'])<=l else wall
   row['high_observed_at_ms']=previous_row.get('high_observed_at_ms',wall) if previous_row and float(previous_row['h'])>=h else wall
   if not history or t not in merged or T<wall-1000:
    merged[t]=dict(row)
   else:
    # REST reconciliation for the still-open H1 candle. A late/reconnected WS
    # subscriber can miss an earlier intrabar extreme; never let an older cached
    # high/low hide the authoritative Bybit candle extreme.
    prev=dict(merged[t]);fresh=dict(row)
    try:
     fresh['h']=str(max(float(prev['h']),float(fresh['h'])))
     fresh['l']=str(min(float(prev['l']),float(fresh['l'])))
     fresh['o']=prev.get('o',fresh.get('o'))
     fresh['v']=str(max(float(prev.get('v') or 0),float(fresh.get('v') or 0)))
    except (KeyError,TypeError,ValueError):
     pass
    merged[t]=fresh
   _LOCAL_CANDLE_CACHE[key]=(stamp,[merged[k] for k in sorted(merged)][-125:],wall)
 TRADE_WAKE.set()

def checkpoint_local_candles():
 pending=[];wall=int(time.time()*1000)
 with _LOCAL_CANDLE_CACHE_LOCK:
  for key,item in _LOCAL_CANDLE_CACHE.items():
   closed=[r['t'] for r in item[1] if r['T']<=wall-1000]
   if len(closed)<6:continue
   token=max(closed)
   if _LOCAL_CANDLE_CHECKPOINTED.get(key)!=token or wall-int(_LOCAL_CANDLE_CHECKPOINTED.get(('saved',key),0))>=5000:pending.append((key,token,copy.deepcopy(item[1])))
 if not pending:return
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   for key,token,rows in pending:
    db.execute('insert into pandora_win_candle_checkpoints(symbol,interval,candles,saved_at) values(%s,%s,%s::jsonb,clock_timestamp()) on conflict(symbol,interval) do update set candles=excluded.candles,saved_at=excluded.saved_at',(key[0],key[1],json.dumps(rows)))
 for key,token,rows in pending:
  _LOCAL_CANDLE_CHECKPOINTED[key]=token
  _LOCAL_CANDLE_CHECKPOINTED[('saved',key)]=wall

def _pandora_h1_candles(symbol):
 with _LOCAL_CANDLE_CACHE_LOCK:item=_LOCAL_CANDLE_CACHE.get((symbol,'1h',120))
 if not item:raise RuntimeError('closed_h1_history_unavailable:'+symbol)
 return copy.deepcopy(item[1]),int(time.time()*1000)

def _local_m15_candles(symbol):
 with _LOCAL_CANDLE_CACHE_LOCK:item=_LOCAL_CANDLE_CACHE.get((symbol,'15m',48))
 if not item:raise RuntimeError('m15_history_unavailable:'+symbol)
 return copy.deepcopy(item[1]),int(time.time()*1000)


def account_mutation(fn):
 @functools.wraps(fn)
 def run(*args,**kwargs):
  # Serialize account writes without blocking price/health/source snapshots.
  with ACCOUNT_LOCK:return fn(*args,**kwargs)
 return run

def pandora_runtime_symbols():
 with LOCK:
  hot=tuple((S.get("bybit_discovery") or {}).get("selected_symbols") or ())
  held=tuple(S.get("pandora_win_positions",{}));watched=tuple(S.get("pandora_watch",{}))
 with LOCK:pool=tuple((S.get('bybit_discovery') or {}).get('candidate_symbols') or ())
 return tuple(dict.fromkeys(hot+held+watched+pool))

def pandora_runtime_h1_verified(symbol,analysis=None,now_epoch=None):
 # Persisted H1 anchors are valid for display and managing an already-open position,
 # but a NEW entry/re-entry must be backed by an H1 scan performed by THIS process.
 # This prevents deploy/lease takeover from reopening a stale regime before current
 # closed H1 candles have been re-read.
 with LOCK:meta=copy.deepcopy(S.get("_pandora_h1_runtime_verified",{}).get(symbol))
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

def pandora_confirmed_h1(a):
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

def pandora_trade_symbols():
 # Discovery selects new markets; retain positions and watches through rotation.
 # H1 verification is a separate allocation gate, never a subscription gate.
 with LOCK:
  hot=tuple((S.get("bybit_discovery") or {}).get("selected_symbols") or ())
  held=tuple(S.get("pandora_win_positions",{}));watched=tuple(S.get("pandora_watch",{}))
 return tuple(dict.fromkeys(hot+held+watched))

def bybit_volatility_discovery_loop():
 scanner=WIN.scanner
 def universe():
  with LOCK:return tuple(S.get('_bybit_instruments',{}))
 def report(index,value):
  with LOCK:S['sources']['ScannerTicker:'+str(index)]={**value,'at':now()}
 shards=max(1,min(8,int(os.getenv('PANDORA_SCANNER_SHARDS','4'))))
 workers=[threading.Thread(target=ticker_worker,args=(scanner,SHUTDOWN,universe,lambda value,i=i:report(i,value),i,shards),daemon=True) for i in range(shards)]
 for worker in workers:worker.start()
 last_bootstrap=0
 try:
  while not SHUTDOWN.is_set():
   # REST bootstraps/reconciles only a missing or wholly stale market stream.
   with scanner.lock:
    fresh=any(0<=time.time()-r.get('price_received',0)<=scanner.freshness for r in scanner.markets.values())
   if not fresh and time.time()-last_bootstrap>=30:
    last_bootstrap=time.time()
    try:
     request=urllib.request.Request('https://api.bybit.com/v5/market/tickers?category=linear',headers={'User-Agent':'pandora-win/2.0'})
     with urllib.request.urlopen(request,timeout=12) as response:payload=json.load(response)
     if int(payload.get('retCode',-1))!=0:raise RuntimeError('scanner_bootstrap_rejected')
     for row in (payload.get('result') or {}).get('list',[]):scanner.ingest(row,int(time.time()*1000))
    except Exception as error:
     with LOCK:S['sources']['ScannerBootstrap']={'ok':False,'error':str(error)[:160],'at':now()}
   with LOCK:
    instruments=copy.deepcopy(S.get('_bybit_instruments',{}));held=tuple(S.get('pandora_win_positions',{}))
   snapshot=scanner.rank(instruments,MARKET_OBS.flow_context,held)
   WIN.scanner_snapshot(snapshot)
   with LOCK:S['sources']['BybitDiscovery']={'ok':bool(snapshot['selected_symbols']),'at':now(),'selected':len(snapshot['selected_symbols']),'mode':'LIVE_STREAM'}
   TRADE_WAKE.set();SHUTDOWN.wait(1)
 finally:
  for worker in workers:worker.join(3)

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
     if not pair.endswith("USDT") or row.get("status")!="Trading" or row.get("contractType")!="LinearPerpetual" or row.get("settleCoin")!="USDT":continue
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

def fresh_mark_price(symbol,now_epoch=None):
 stamp=time.time() if now_epoch is None else float(now_epoch)
 with LOCK:
  age=stamp-float(S.get('_price_received_epoch',{}).get(symbol,0))
  price=S.get('_prices',{}).get(symbol)
 try:price=float(price)
 except (ValueError,TypeError,OverflowError):return None
 return price if 0<=age<=10 and math.isfinite(price) and price>0 else None

def current_entry_price(symbol):
 with LOCK:
  if not S["engine_active"] or S.get("mode")!="PAPER_ONLY" or S.get("orders_enabled") or SHUTDOWN.is_set():return None
  checkpoint=publication_epoch(S.get("last_checkpoint"))
 if checkpoint is None or not 0<=time.time()-checkpoint<=15:return None
 return fresh_mark_price(symbol)

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

def pandora_win_h1_direction(rows,now_ms,symbol):
 analysis=analyze_pandora_h1(rows,now_ms,symbol)
 try:m15_rows,_=_local_m15_candles(symbol)
 except RuntimeError:m15_rows=[]
 detailed=live_locals(rows,m15_rows,now_ms,symbol)
 analysis=execution_anchor(detailed,MARKET_OBS.flow_context(symbol,now_ms/1000))
 if not analysis.get("ready") or not analysis.get("anchor_confirmed"):
  # Fresh H1 cache may lag during deploy/lease handoff. Keep the latest
  # confirmed directional anchor usable instead of blanking the symbol.
  fallback=_local_persisted_anchor(symbol)
  if fallback and fallback.get("policy")==PANDORA_LOCAL_POLICY and int(fallback.get("entry_side") or 0) in (-1,1):
   recovered={**fallback,"ready":False,"stale_source_reason":analysis.get("reason"),
     "anchor_recovered_from":"latest_valid_pandora_observation",
     **local_pending_extreme(rows,now_ms,int(fallback.get("entry_side") or 0),fallback.get("pivot_price"))}
   recovered.update(entry_blocked=True,entry_block_reason="current_h1_history_not_verified")
   try:
    with pg() as db:
     with db.transaction():
      STORE.fence(db)
      db.execute("insert into pandora_win_h1_direction(symbol,analysis) values(%s,%s::jsonb) on conflict(symbol) do update set analysis=excluded.analysis",
       (symbol,json.dumps(recovered)))
    with LOCK:S.setdefault("pandora_win_h1_direction",{})[symbol]=copy.deepcopy(recovered)
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
  if trusted_t>fresh_t and trusted.get("policy")==PANDORA_LOCAL_POLICY:
   analysis={**trusted,"ready":True,"last_candle_time":analysis.get("last_candle_time"),
    **local_pending_extreme(rows,now_ms,int(trusted.get("entry_side") or 0),trusted.get("pivot_price")),
    "anchor_guard":"newest_confirmed_anchor_wins"}
 if analysis.get("live_structural_flip"):
  analysis["signal_candle_time"]=analysis.get("pivot_candle_time") or analysis.get("signal_candle_time")
 with LOCK:prior=copy.deepcopy(S.get("pandora_win_h1_direction",{}).get(symbol))
 if prior:
  prior_t=int(prior.get("signal_candle_time") or 0);new_t=int(analysis.get("signal_candle_time") or 0)
  prior_side=int(prior.get("entry_side") or 0);new_side=int(analysis.get("entry_side") or 0)
  if prior_t>new_t and prior.get("policy")==PANDORA_LOCAL_POLICY:
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
  if fallback and fallback.get("policy")==PANDORA_LOCAL_POLICY and int(fallback.get("entry_side") or 0) in (-1,1):
   analysis={**fallback,"ready":True,
     "last_candle_time":analysis.get("last_candle_time"),
     **local_pending_extreme(rows,now_ms,int(fallback.get("entry_side") or 0),fallback.get("pivot_price")),
     "anchor_recovered_from":"latest_valid_pandora_observation"}
  else:
   return analysis
 for key in ('confirmed_local','forming_local','forming_locals','live_structure_fresh'):
  if key in detailed:analysis[key]=copy.deepcopy(detailed[key])
 if detailed.get('entry_blocked') and not (analysis.get('confirmation_source')=='observed_H1_extreme_closed_M15_and_executed_control' and analysis.get('pivot_candle_time')==(detailed.get('forming_local') or {}).get('pivot_candle_time') and analysis.get('pivot_price')==(detailed.get('forming_local') or {}).get('pivot_price') and (detailed.get('forming_local') or {}).get('m15_confirmation')):
  analysis['entry_blocked']=True;analysis['entry_block_reason']=detailed.get('entry_block_reason')
 # Process-local proof that current CLOSED H1 candles were actually scanned.
 # This marker is written only AFTER all structural + flow guards select the
 # final active anchor, so the 500ms executor cannot outrun H1 reconciliation.
 if analysis.get("ready") and analysis.get("anchor_confirmed") and int(analysis.get("entry_side") or 0) in (-1,1):
  with LOCK:
   S.setdefault("_pandora_h1_runtime_verified",{})[symbol]={
    "verified_at":time.time(),"observed_at_ms":int(now_ms),
    "last_candle_time":int(analysis.get("last_candle_time") or 0),
    "entry_side":int(analysis.get("entry_side") or 0),
    "signal_candle_time":int(analysis.get("signal_candle_time") or 0),
    "pivot_candle_time":int(analysis.get("pivot_candle_time") or 0),
    "pivot_type":analysis.get("pivot_type"),"pivot_price":analysis.get("pivot_price")}
 def local_fingerprint(value):
  value=value or {}
  return tuple((x.get('pivot_type'),x.get('pivot_price'),x.get('pivot_candle_time'),x.get('m15_confirmation')) for x in value.get('forming_locals',[]))
 anchor_changed=(not prior or any((prior or {}).get(k)!=analysis.get(k) for k in ('policy','signal_candle_time','pivot_type','pivot_price')))
 forming_changed=local_fingerprint(prior)!=local_fingerprint(analysis)
 changed=anchor_changed or forming_changed
 stamp=time.time()
 with LOCK:last=float(S.setdefault("_pandora_h1_persist_epoch",{}).get(symbol,0) or 0)
 if changed or stamp-last>=30:
  with pg() as db:
   with db.transaction():
    STORE.fence(db)
    db.execute("insert into pandora_win_h1_direction(symbol,analysis) values(%s,%s::jsonb) on conflict(symbol) do update set analysis=excluded.analysis",
      (symbol,json.dumps(analysis)))
  if WIN is not None and changed:
   with pg() as db:
    with db.transaction():
     STORE.fence(db)
     if anchor_changed and analysis.get('anchor_confirmed'):
      WIN.event(db,str(analysis.get('pivot_type'))+'_CONFIRMED',symbol,'closed_structure_confirmation',analysis)
     for forming in analysis.get('forming_locals',[]) if forming_changed else []:
      WIN.event(db,forming['pivot_type']+'_FORMING',symbol,'observed_online_extreme',forming)
  with LOCK:
   S.setdefault("pandora_win_h1_direction",{})[symbol]=copy.deepcopy(analysis)
   S["_pandora_h1_persist_epoch"][symbol]=stamp
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
  add_candidate(copy.deepcopy(S.get("pandora_win_h1_direction",{}).get(symbol)),"memory_canonical")
  add_candidate(copy.deepcopy(S.get("pandora_win_positions",{}).get(symbol)),"open_position")
  add_candidate(copy.deepcopy(S.get("pandora_watch",{}).get(symbol)),"reentry_watch")
 try:
  with pg() as db:
   durable=db.execute("select analysis from pandora_win_h1_direction where symbol=%s",(symbol,)).fetchone()
   if durable:add_candidate(durable,"durable_canonical")
   # Sort by the actual H1 signal time, NOT journal write time.
   rows=db.execute("""select side,candle_time,features from pandora_win_signal_journal
     where features->>'symbol'=%s and action in ('OBSERVE','OPEN','REENTRY')
     order by coalesce(nullif(features->>'signal_candle_time','')::bigint,candle_time) desc,
              coalesce(nullif(features->>'pivot_candle_time','')::bigint,0) desc, ts desc
     limit 12""",(symbol,)).fetchall()
   for row in rows:add_candidate(row,"signal_journal")
   # Executed trades are another durable proof of the H1 anchor used at entry.
   trades=db.execute("""select side,features from pandora_win_trade_history
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

def _pandora_margin_state():
 with LOCK:
  realized_equity=float(S.get('pandora_equity',500))
  positions=copy.deepcopy(S.get('pandora_win_positions',{}))
 used=sum(max(0.,float(p.get('margin',0))) for p in positions.values())
 unrealized=0.;missing=[]
 for symbol,pos in positions.items():
  mark=fresh_mark_price(symbol)
  if mark is None:missing.append(symbol);continue
  unrealized+=paper_pnl(pos['notional'],pos['entry'],mark,pos['side'],FEE)
 complete=not missing
 with LOCK:S['margin_valuation']={'complete':complete,'missing_marks':missing,'at':now()}
 # Unknown portfolio equity may not finance a new trade. Canonical realized
 # balance is never clamped; a gap/insolvency remains visible in the ledger.
 if not complete:return 0.,used,0.
 equity=realized_equity+unrealized
 return equity,used,max(0.,equity-used)

def risk_day():
 return datetime.datetime.now(ZoneInfo(os.getenv('PANDORA_RISK_TIMEZONE','Europe/Samara'))).date().isoformat()

def risk_snapshot(policy=None):
 policy=policy or RiskPolicy.from_env()
 equity,used,free=_pandora_margin_state()
 with LOCK:
  positions=copy.deepcopy(S.get('pandora_win_positions',{}))
  complete=bool(S.get('margin_valuation',{}).get('complete'))
 modeled=sum(position_risk(p,fee=FEE,slippage=policy.slippage) for p in positions.values())
 allowed=complete and equity>0 and free>0
 reason=None if allowed else 'PORTFOLIO_MARKS_STALE' if not complete else 'ACCOUNT_INSOLVENT' if equity<=0 else 'INSUFFICIENT_FREE_MARGIN'
 # PnL, past losses and historical daily-halt rows never pause new trading.
 # Admission is determined only by available data, collateral and order rules.
 state={'equity':equity,'free_margin':free,'used_margin':used,'portfolio_risk':modeled,
  'allowed':allowed,'reason':reason,'pnl_based_halts':False,'daily_pause_enabled':False,
  'min_entry_margin_fraction':policy.min_margin_fraction,'min_leverage':policy.min_leverage,
  'max_leverage':policy.max_leverage,'modeled_risk_is_guarantee':False,'fixed_sl_tp':False,'mfe_percentage_exit':False}
 with LOCK:S['risk_circuit']=state
 return state

def _pandora_watch_clear(symbol,reason):
 with LOCK:watch=copy.deepcopy(S.get("pandora_watch",{}).get(symbol))
 if not watch:return False
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   db.execute("delete from pandora_win_watchlist where symbol=%s",(symbol,))
   db.execute("insert into pandora_win_audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'pandora_watch_cleared',%s::jsonb)",
     (now(),json.dumps({"symbol":symbol,"reason":reason,"watch":watch},default=str)))
 with LOCK:S.setdefault("pandora_watch",{}).pop(symbol,None)
 return True

@account_mutation
def _pandora_watch_observe(symbol,watch,mark,execution_context,flow,stamp):
 updated=pandora_flow_update_watch(watch,mark,execution_context,flow,stamp)
 before=(watch or {}).get("context") or {};context=updated.get("context") or {}
 changed=before.get("phase")!=context.get("phase")
 with LOCK:last=float(S.setdefault("_pandora_watch_persist_epoch",{}).get(symbol,0) or 0)
 if changed or stamp-last>=1:
  with pg() as db:
   with db.transaction():
    STORE.fence(db)
    db.execute("update pandora_win_watchlist set context=%s::jsonb where symbol=%s and exit_at=%s",
      (json.dumps(context,default=str),symbol,watch.get("exit_at")))
    if changed:
     db.execute("insert into pandora_win_audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'pandora_flow_phase',%s::jsonb)",
       (now(),json.dumps({"symbol":symbol,"side":watch.get("side"),"phase":context.get("phase"),"context":context},default=str)))
  with LOCK:S["_pandora_watch_persist_epoch"][symbol]=stamp
 with LOCK:
  live=S.get("pandora_watch",{}).get(symbol)
  if live and live.get("exit_at")==watch.get("exit_at"):S["pandora_watch"][symbol]=copy.deepcopy(updated)
 return updated

@account_mutation
def pandora_open(symbol,side,analysis,entry_kind="ORDER_FLOW",execution_context=None,watch=None):
 def reject(reason):
  payload={"symbol":symbol,"reason":reason,"at":now(),"entry_kind":entry_kind,
    "signal_candle_time":(analysis or {}).get("signal_candle_time")}
  with LOCK:
   previous=S.setdefault("pandora_executor_rejections",{}).get(symbol) or {}
   S["pandora_executor_rejections"][symbol]=payload
  if previous.get("reason")!=reason or previous.get("signal_candle_time")!=payload["signal_candle_time"]:
   try:journal("pandora_entry_rejected",None,payload)
   except Exception:pass
  return False
 if symbol not in set(pandora_trade_symbols()) or int(side or 0) not in (-1,1):return reject("ENTRY_STATE_REVALIDATION_FAILED")
 if not pandora_confirmed_h1(analysis):return reject("H1_NOT_CONFIRMED")
 # Fail closed for NEW risk until this runtime has revalidated the current H1 book.
 # Hydrated/persisted anchors may manage existing risk but may not create fresh risk.
 if not pandora_runtime_h1_verified(symbol,analysis):return reject("CURRENT_CLOSED_H1_NOT_VERIFIED")
 if S.get("mode")!="PAPER_ONLY" or S.get("orders_enabled") or not analysis.get("ready"):return reject("ENTRY_STATE_REVALIDATION_FAILED")
 if not analysis.get("h1_direction_anchor") or int(analysis.get("entry_side") or 0)!=int(side):return reject("ENTRY_STATE_REVALIDATION_FAILED")
 if analysis.get("entry_blocked"):return reject("ENTRY_STATE_REVALIDATION_FAILED")
 if WIN is not None and symbol not in set((S.get('bybit_discovery') or {}).get('selected_symbols') or []):return reject('TOKEN_NOT_SELECTED')
 if (S.get('bybit_discovery') or {}).get('selection_frozen'):return reject('SCANNER_OBSERVATIONS_UNAVAILABLE')
 if analysis.get('live_structure_fresh') is False:return reject('LOCAL_OBSERVATIONS_STALE')
 # Recheck at allocation time: scanning many markets and database writes take time.
 # Revalidate the H1 side plus fresh executed-flow executed control before adding risk.
 stamp=time.time()
 flow=MARKET_OBS.flow_context(symbol,stamp)
 selection=(pandora_flow_entry_candidate(symbol,analysis,execution_context,flow,stamp) if entry_kind=="REENTRY"
            else pandora_flow_initial_entry_candidate(symbol,analysis,execution_context,flow,stamp))
 if not selection["eligible"]:return reject(selection["reason"])
 with LOCK:current_anchor=copy.deepcopy(S.get("pandora_win_h1_direction",{}).get(symbol))
 if current_anchor and (int(current_anchor.get("entry_side") or 0)!=int(side) or
     int(current_anchor.get("signal_candle_time") or 0)!=int(analysis.get("signal_candle_time") or 0)):return reject("ENTRY_STATE_REVALIDATION_FAILED")
 price=current_entry_price(symbol)
 if price is None:return reject("CURRENT_SYMBOL_MARK_OR_CHECKPOINT_UNAVAILABLE")
 if entry_kind=="REENTRY":
  if not watch or int(watch.get("side") or 0)!=int(side):return reject("ENTRY_STATE_REVALIDATION_FAILED")
  if int(analysis.get("entry_side") or 0)==-int(side):return reject("ENTRY_STATE_REVALIDATION_FAILED")
  with LOCK:live_watch=copy.deepcopy(S.get("pandora_watch",{}).get(symbol))
  if not live_watch or live_watch.get("exit_at")!=watch.get("exit_at"):return reject("ENTRY_STATE_REVALIDATION_FAILED")
  if not pandora_flow_reentry_ready(side,execution_context,price,live_watch,flow,stamp):return reject("WAIT_REENTRY_RESUMPTION")
 with LOCK:instrument=copy.deepcopy(S.get("_bybit_instruments",{}).get(symbol))
 if not instrument or time.time()-float(instrument.get("observed_at",0))>86400:return reject("BYBIT_CONTRACT_CONSTRAINTS_UNAVAILABLE")
 leverage=min(50.0,float(instrument["max_leverage"]))
 with LOCK:allocation_blocked=not S.get("engine_active") or symbol in S.get("pandora_win_positions",{})
 if allocation_blocked:return reject("ENGINE_STANDBY_OR_POSITION_ALREADY_OPEN")
 # Risk budget, not maximum nominal leverage, governs exposure.
 policy=RiskPolicy.from_env()
 risk=risk_snapshot(policy)
 if not risk['allowed']:return reject(risk['reason'])
 equity=risk['equity'];free=risk['free_margin']
 plan=plan_entry(equity,free,float(instrument['max_leverage']),float(price),int(side),analysis,flow,risk['portfolio_risk'],policy)
 if not plan.allowed:return reject(plan.reason)
 leverage=plan.leverage;margin=plan.margin;notional=plan.notional
 desired_margin=equity*(policy.min_margin_fraction+(policy.max_entry_margin_fraction-policy.min_margin_fraction)*plan.signal_strength)
 max_margin_per_position=equity*policy.max_entry_margin_fraction;target_notional=desired_margin*leverage
 exposure_fill_ratio=notional/target_notional if target_notional else 0.
 # Recheck the actual tape after planning. A historical BUY majority must
 # never admit LONG if current buying has stopped while allocation ran.
 latest_flow=MARKET_OBS.flow_context(symbol,time.time())
 latest_selection=(pandora_flow_entry_candidate(symbol,analysis,execution_context,latest_flow,time.time()) if entry_kind=='REENTRY'
                   else pandora_flow_initial_entry_candidate(symbol,analysis,execution_context,latest_flow,time.time()))
 if not latest_selection.get('eligible'):return reject('EXECUTED_CONTROL_CHANGED_DURING_ALLOCATION')
 with LOCK:latest_anchor=copy.deepcopy(S.get('_pandora_analysis',{}).get(symbol) or {})
 if latest_anchor and (latest_anchor.get('entry_blocked') or latest_anchor.get('live_structure_fresh') is False or
     int(latest_anchor.get('entry_side') or 0)!=int(side) or
     int(latest_anchor.get('signal_candle_time') or 0)!=int(analysis.get('signal_candle_time') or 0)):
  return reject('LOCAL_CHANGED_DURING_ALLOCATION')
 flow=latest_flow;selection=latest_selection
 price=float(price);opened=now();epoch=time.time()
 reentries=(int(watch.get("reentries") or 0)+1) if entry_kind=="REENTRY" and watch else 0
 origin_signal=int(analysis.get("signal_candle_time") or 0)
 claim_token=int((execution_context or {}).get("candle_time") or origin_signal)
 features={**analysis,"symbol":symbol,"strategy_name":PANDORA_WIN_NAME,"experiment":PANDORA_WIN_NAME,
  "policy":PANDORA_LOCAL_POLICY,"flow_policy":PANDORA_FLOW_POLICY,"entry_kind":entry_kind,
  "candidate_selection":selection,
  "origin_h1_signal_candle":origin_signal,"swing_reentries":reentries,
  "reference_margin_fraction":plan.chosen_margin_fraction,"minimum_margin_fraction":policy.min_margin_fraction,"reference_leverage":policy.max_leverage,"risk_plan":plan.to_dict(),
  "target_notional":target_notional,"desired_margin":desired_margin,"max_margin_per_position":max_margin_per_position,
  "actual_margin":margin,"free_margin_before":free,"mark_to_market_equity_at_entry":equity,
  "exposure_fill_ratio":exposure_fill_ratio,"leverage":leverage,"leverage_source":"bybit_instruments_info",
  "mfe_price_move":0.0,"mae_price_move":0.0,"mfe_roe_pct":0.0,"mae_roe_pct":0.0,
  "entry_mark":price,
  "pressure_state":{"best":int(side)*price,"noise":float((((watch or {}).get("context") or {}).get("resumption_state") or {}).get("noise") or 0.),
    "barrier":(-float((((watch or {}).get("context") or {}).get("resumption_state") or {}).get("candidate",{}).get("retest_best")) if (((watch or {}).get("context") or {}).get("resumption_state") or {}).get("candidate",{}).get("retest_best") is not None else None),"phase":"HOLDING"},

  "reentry_watch":copy.deepcopy(watch) if entry_kind=="REENTRY" else None,
  "estimated_round_trip_cost_move":2*FEE+0.0004,"execution_cost_budget_only":True}
 fast=(flow.get('windows') or {}).get('15',{})
 features['pyramid_level']=0
 features['pyramid_state']={'phase':'WAIT_NEW_IMPULSE','last_impulse_price':price,
  'last_add_event':flow.get('decision_event_epoch') or flow.get('latest_trade_epoch') or 0,
  'baseline_velocity':fast.get('volume_velocity',0),
  'baseline_side_volume':fast.get('buy_volume' if side>0 else 'sell_volume',0)}
 pos={"symbol":symbol,"side":int(side),"entry":price,"notional":notional,"margin":margin,"leverage":leverage,
   "opened":opened,"t":epoch,"signal_candle_time":origin_signal,"features":features}
 claim_id=("LOCAL_EXP:REENTRY:OPEN:%s:%s:%s:%s"%(symbol,claim_token,int(side),reentries)
   if entry_kind=="REENTRY" else "LOCAL_EXP:OPEN:%s:%s:%s"%(symbol,origin_signal,int(side)))
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   claim=db.execute("""insert into pandora_win_signal_journal(id,ts,candle_time,action,side,price,features)
     values(%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict(id) do nothing returning id""",
     (claim_id,opened,claim_token,"REENTRY" if entry_kind=="REENTRY" else "OPEN",int(side),price,json.dumps(features,default=str))).fetchone()
   if not claim:return reject("SIGNAL_ALREADY_EXECUTED")
   row=db.execute("""insert into pandora_win_positions(symbol,side,entry,notional,margin,leverage,opened,opened_epoch,signal_candle_time,features)
     values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict(symbol) do nothing returning symbol""",
     (symbol,int(side),price,notional,margin,leverage,opened,epoch,origin_signal,json.dumps(features,default=str))).fetchone()
   if not row:raise psycopg.Rollback()
   if entry_kind=="REENTRY":db.execute("delete from pandora_win_watchlist where symbol=%s",(symbol,))
   db.execute("insert into pandora_win_audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'pandora_trade_opened',%s::jsonb)",
    (now(),json.dumps({"strategy":PANDORA_WIN_NAME,"symbol":symbol,"side":int(side),"entry_kind":entry_kind,
      "entry":price,"reason":selection["reason"],"signal_candle_time":origin_signal,
      "margin":margin,"notional":notional,"target_notional":target_notional,
      "exposure_fill_ratio":exposure_fill_ratio,"leverage":leverage,"equity":equity,"free_margin_before":free},default=str)))
   if WIN is not None:WIN.semantic_open(db,symbol,pos)
 if not row:return reject("POSITION_WRITE_CONFLICT")
 with LOCK:
  S.setdefault("pandora_win_positions",{})[symbol]=pos
  if entry_kind=="REENTRY":S.setdefault("pandora_watch",{}).pop(symbol,None)
 log_learning_decision("PANDORA_WIN:%s:%s:%s:%s"%(symbol,entry_kind,claim_token,int(side)),
   PANDORA_WIN_NAME,symbol,side,"OPEN" if entry_kind!="REENTRY" else "REENTRY",
   "confirmed_local_entry",price,None,leverage,features,opened)
 if WIN is not None:WIN.reload_token(symbol)
 return True

@account_mutation
def pandora_close(symbol,price,reason,analysis=None,watch_context=None):
 with LOCK:pos=copy.deepcopy(S.get("pandora_win_positions",{}).get(symbol))
 if not pos:return None
 price=float(price)
 pos=mark_metrics(pos,price,MARKET_OBS.flow_context(symbol),analysis or S.get('_pandora_analysis',{}).get(symbol,{}) or {},FEE)
 pnl=paper_pnl(pos["notional"],pos["entry"],price,pos["side"],FEE)
 features=copy.deepcopy(pos.get("features") or {})
 if analysis:features["exit_analysis"]=analysis
 if watch_context:features["executed_flow_exit_context"]=watch_context
 features["actual_exit_reason"]=reason;features["actual_exit_mark"]=price
 watch=None
 if reason == "confirmed_counter_move_exit":
  watch={"symbol":symbol,"side":int(pos["side"]),
   "origin_signal_candle":int(features.get("origin_h1_signal_candle") or pos.get("signal_candle_time") or 0),
   "exit_price":price,"exit_at":now(),"expires_epoch":0.0,
   "reentries":int(features.get("swing_reentries",0) or 0),"context":{**copy.deepcopy(watch_context or {}),"exit_pressure_state":copy.deepcopy(features.get("pressure_state") or {})}}
  # Preserve the exchange timestamp of the opposite executed-flow event so
  # Re-entry must follow a later executed-flow resumption.
  opposite_flow_exit=True
  flow_at_exit=(watch_context or {}).get("flow_context") or {}
  try:
   opposite_epoch=flow_at_exit.get("decision_event_epoch") or flow_at_exit.get("latest_trade_epoch")
   if opposite_epoch is None:
    opposite_epoch=float(flow_at_exit["volume_window_end_epoch"])-float(flow_at_exit["latest_trade_age_seconds"])
   opposite_epoch=float(opposite_epoch)
   if not math.isfinite(opposite_epoch):opposite_epoch=None
  except (KeyError,TypeError,ValueError,OverflowError):opposite_epoch=None
  confirmed_opposite=bool(opposite_flow_exit and opposite_epoch is not None)
  watch["context"].update(phase="WAIT_RESUMPTION" if confirmed_opposite else "WAIT_PULLBACK",
    counter_pressure_seen=confirmed_opposite,flow_policy=PANDORA_FLOW_POLICY)
  if confirmed_opposite:watch["context"]["last_opposite_trade_epoch"]=opposite_epoch
 with pg() as db:
  with db.transaction():
   STORE.fence(db)
   row=db.execute("delete from pandora_win_positions where symbol=%s and opened=%s returning symbol",
     (symbol,pos["opened"])).fetchone()
   if not row:return None
   acct=db.execute("""update pandora_win_account_state
     set equity=equity+%s,realized_pnl=realized_pnl+%s,updated_at=%s where id=1 returning equity,realized_pnl""",
     (pnl,pnl,now())).fetchone()
   db.execute("""insert into pandora_win_trade_history(opened,closed,symbol,side,entry,exit,pnl,reason,margin,notional,leverage,features)
     values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
     (pos["opened"],now(),symbol,pos["side"],pos["entry"],price,pnl,reason,pos["margin"],pos["notional"],
      pos["leverage"],json.dumps(features,default=str)))
   if watch:
    db.execute("""insert into pandora_win_watchlist(symbol,side,origin_signal_candle,exit_price,exit_at,expires_epoch,reentries,context)
      values(%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
      on conflict(symbol) do update set side=excluded.side,origin_signal_candle=excluded.origin_signal_candle,
      exit_price=excluded.exit_price,exit_at=excluded.exit_at,expires_epoch=excluded.expires_epoch,
      reentries=excluded.reentries,context=excluded.context""",
      (symbol,watch["side"],watch["origin_signal_candle"],watch["exit_price"],watch["exit_at"],0.0,
       watch["reentries"],json.dumps(watch["context"],default=str)))
   db.execute("insert into pandora_win_audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'pandora_trade_closed',%s::jsonb)",
     (now(),json.dumps({"strategy":PANDORA_WIN_NAME,"symbol":symbol,"side":pos["side"],"entry":pos["entry"],
       "exit":price,"pnl":pnl,"reason":reason,"equity":float(acct["equity"]),"watch_armed":bool(watch),
       "leverage":pos["leverage"],"exposure_fill_ratio":features.get("exposure_fill_ratio")},default=str)))
   if WIN is not None:WIN.semantic_close(db,symbol,pos,reason,price,pnl,watch)
 with LOCK:
  S.setdefault("pandora_win_positions",{}).pop(symbol,None)
  if watch:S.setdefault("pandora_watch",{})[symbol]=watch
  S["pandora_equity"]=float(acct["equity"])
  S["pandora_realized_pnl"]=float(acct["realized_pnl"])
  S["pandora_trades"]=int(S.get("pandora_trades",0) or 0)+1
 log_learning_decision("PANDORA_WIN:CLOSE:%s:%s"%(symbol,pos.get("opened")),
   PANDORA_WIN_NAME,symbol,pos["side"],"CLOSED",reason,pos["entry"],None,
   pos["leverage"],features,pos.get("opened"))
 if WIN is not None:WIN.reload_token(symbol)
 return {"symbol":symbol,"pnl":pnl,"reason":reason,"equity":float(acct["equity"])}

@account_mutation
def pandora_mark_positions(prices):
 with LOCK:
  received=dict(S.get("_price_received_epoch",{}))
  prices={symbol:price for symbol,price in prices.items() if 0<=time.time()-received.get(symbol,0)<=10}
 with LOCK:positions=copy.deepcopy(S.get("pandora_win_positions",{}))
 for symbol,pos in positions.items():
  mark=prices.get(symbol)
  if not mark:continue
  flow=MARKET_OBS.flow_context(symbol,time.time())
  anchor=copy.deepcopy(S.get('_pandora_analysis',{}).get(symbol) or {})
  updated=mark_metrics(pos,float(mark),flow,anchor,FEE)
  updated,liq=update_position_path(updated,float(mark))
  # No percentage SL/TP or MFE giveback exit: planned reference prices
  # describe stress geometry only. The PAPER maintenance outcome is still
  # modeled honestly when collateral is exhausted.
  guard=position_guard(updated,float(mark),FEE)
  with LOCK:
   if S.get('pandora_win_positions',{}).get(symbol,{}).get('opened')==pos.get('opened'):
    S['pandora_win_positions'][symbol]=updated
  if guard:
   pandora_close(symbol,float(mark),guard,anchor);continue
  f=updated.setdefault("features",{})
  # Pandora Win MFE protection: preserve trend profits; exits are confirmed by executed-flow control transfer.
  entry=float(updated.get("entry") or 0);side=int(updated.get("side") or 0);markf=float(mark)
  move=side*(markf/entry-1.0) if entry>0 and side in (-1,1) else 0.0
  mfe=max(float(f.get("mfe_price_move",0) or 0),move)
  f["mfe_price_move"]=mfe;f["mfe_roe_pct"]=mfe*float(updated.get("leverage") or 25.0)*100.0
  f.update(flow_policy=PANDORA_FLOW_POLICY,
    current_price_move=move,mfe_giveback_move=max(0.0,mfe-move))
  with LOCK:
   live=S.get("pandora_win_positions",{}).get(symbol)
   if live and live.get("opened")==pos.get("opened"):S["pandora_win_positions"][symbol]=updated
  with LOCK:anchor=copy.deepcopy(S.get('_pandora_analysis',{}).get(symbol) or {})
  flow=MARKET_OBS.flow_context(symbol,time.time())
  opposite_local=bool(pandora_runtime_h1_verified(symbol,anchor)
   and int(anchor.get('entry_side') or 0)==-int(pos['side'])
   and int(anchor.get('signal_candle_time') or 0)>int(pos.get('signal_candle_time') or 0))
  reason=pandora_flow_pressure_exit(updated,None,float(mark),flow,opposite_local_confirmed=opposite_local)
  with LOCK:
   if S.get("pandora_win_positions",{}).get(symbol,{}).get("opened")==pos.get("opened"):
    S["pandora_win_positions"][symbol]=updated
  if reason:
   pandora_close(symbol,float(mark),reason,analysis=anchor if opposite_local else None,
    watch_context={"flow_context":flow,"observed_at":now()})
   continue
  stamp=time.time()
  with LOCK:last=float(S.setdefault("_pandora_path_persist_epoch",{}).get(symbol,0) or 0)
  if stamp-last<1:continue
  with pg() as db:
   with db.transaction():
    STORE.fence(db)
    db.execute("update pandora_win_positions set features=%s::jsonb where symbol=%s and opened=%s",
      (json.dumps(updated["features"]),symbol,pos["opened"]))
  with LOCK:S["_pandora_path_persist_epoch"][symbol]=stamp


@account_mutation
def pandora_flow_fast_entries(prices):
 # Pandora Win execution:
 # confirmed H1 local owns direction; current top-five pump supplies the universe.
 # Enter as soon as real Bybit executed flow strongly controls that H1 side.
 # Exit is handled by pandora_flow_pressure_exit on a strong opposite takeover; the
 # resulting watch re-enters only after control genuinely returns.
 for symbol in pandora_trade_symbols():
  with LOCK:
   if symbol in S.get("pandora_win_positions",{}):continue
   analysis=copy.deepcopy(S.get("_pandora_analysis",{}).get(symbol))
   watch=copy.deepcopy(S.get("pandora_watch",{}).get(symbol))
  mark=prices.get(symbol)
  if not analysis or not mark:continue
  if not pandora_runtime_h1_verified(symbol,analysis):continue
  side=int(analysis.get("entry_side") or 0)
  if watch and int(watch.get("side") or 0)==-side:
   _pandora_watch_clear(symbol,"opposite_h1_pivot_invalidated_watch");watch=None
  flow=MARKET_OBS.flow_context(symbol,time.time())
  if watch:
   watch=_pandora_watch_observe(symbol,watch,float(mark),None,flow,time.time())
   if pandora_flow_reentry_ready(side,None,mark,watch,flow,time.time()):
    pandora_open(symbol,side,analysis,"REENTRY",{"resumption_observed":True,"strategy":PANDORA_WIN_NAME},watch)
  else:
   selection=pandora_flow_initial_entry_candidate(symbol,analysis,None,flow,time.time())
   if selection.get("eligible"):
    pandora_open(symbol,side,analysis,"ORDER_FLOW",{"pandora_win_direct_control":True,"strategy":PANDORA_WIN_NAME})

def pandora_entry_diagnostic_snapshot(prices):
 # Read-only decision audit: one structured record per candidate every 30 seconds.
 # This does NOT create orders, alter trading gates or introduce strategies.
 rows=[]
 for symbol in pandora_runtime_symbols():
  with LOCK:
   analysis=copy.deepcopy(S.get("_pandora_analysis",{}).get(symbol))
   position=copy.deepcopy(S.get("pandora_win_positions",{}).get(symbol))
   watch=copy.deepcopy(S.get("pandora_watch",{}).get(symbol))
  record={"symbol":symbol,"h1_ready":pandora_confirmed_h1(analysis),
          "position_open":bool(position),"watch_active":bool(watch),
          "entry_side":(analysis or {}).get("entry_side"),
          "executor_rejection":copy.deepcopy(S.get("pandora_executor_rejections",{}).get(symbol))}
  try:
   if position:
    record["reason"]="POSITION_ALREADY_OPEN"
   elif not record["h1_ready"]:
    record["reason"]="H1_NOT_CONFIRMED_OR_BLOCKED"
   elif not prices.get(symbol):
    record["reason"]="MARK_UNAVAILABLE"
   elif not pandora_runtime_h1_verified(symbol,analysis):
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
     record["reason"]="REENTRY_READY" if pandora_flow_reentry_ready(
       int(analysis.get("entry_side") or 0),None,prices[symbol],watch,flow,time.time()
       ) else "WAIT_REENTRY_COUNTERFLOW_OR_RESUMPTION"
    else:
     selection=pandora_flow_initial_entry_candidate(symbol,analysis,None,flow,time.time())
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
 with LOCK:S["pandora_entry_diagnostics"]=snapshot
 try:journal("pandora_entry_diagnostics",None,snapshot)
 except Exception as exc:
  with LOCK:S["pandora_entry_diagnostics_error"]=type(exc).__name__+":"+str(exc)[:140]
 return snapshot

def pandora_risk_loop():
 # Protect observed peaks even while H1/execution context history fetches or scans are slow.
 # Use only fresh streamed/cached marks; never spend additional REST budget.
 last_entry_diagnostics=0.0
 while not SHUTDOWN.is_set():
  try:
   with LOCK:
    active=bool(S.get("engine_active")) and S.get("mode")=="PAPER_ONLY" and not S.get("orders_enabled")
    age=time.time()-float(S.get("_last_poll_epoch",0) or 0)
    prices=dict(S.get("_prices",{}))
   if active and prices:
    if WIN is not None:WIN.cycle(prices)
    else:
     pandora_mark_positions(prices)
     pandora_flow_fast_entries(prices)
    checkpoint_local_candles()

    with LOCK:S["sources"]["LocalRisk"]={"ok":True,"ready":True,"last_check":now(),"mode":"PANDORA_WIN_H1_LOCAL_TOP5_EXECUTED_FLOW","symbols":list(pandora_trade_symbols()),"error":None}
   if time.time()-last_entry_diagnostics>=30:
    last_entry_diagnostics=time.time()
    pandora_entry_diagnostic_snapshot(prices)
  except LeaseLost as exc:
   with LOCK:
    S["engine_active"]=False;S["engine_error"]=str(exc)
  except Exception as exc:
   with LOCK:S["_execution_ok"]=False
   with LOCK:S["sources"]["LocalRisk"]={"ok":False,"last_check":now(),"error":type(exc).__name__+":"+str(exc)[:160]}
  TRADE_WAKE.wait(1)
  TRADE_WAKE.clear()

def pandora_stats():
 try:
  with pg() as db:
   agg=db.execute("""select count(*) as trades,sum(case when pnl>0 then 1 else 0 end) as wins,
      coalesce(sum(pnl),0) as pnl,avg(pnl) as avg_pnl
      from pandora_win_trade_history""").fetchone()
   cutoff=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(hours=24)).isoformat()
   daily=db.execute("""select count(*) as trades,sum(case when pnl>0 then 1 else 0 end) as wins,
      coalesce(sum(pnl),0) as pnl from pandora_win_trade_history where closed >= %s""",(cutoff,)).fetchone()
   rows=db.execute("""select symbol,count(*) as trades,sum(case when pnl>0 then 1 else 0 end) as wins,
      coalesce(sum(pnl),0) as pnl,avg(pnl) as avg_pnl,
      avg(coalesce((features->>'exposure_fill_ratio')::double precision,1)) as avg_fill
      from pandora_win_trade_history group by symbol order by symbol""").fetchall()
  n=int(agg["trades"] or 0);w=int(agg["wins"] or 0)
  dn=int(daily["trades"] or 0);dw=int(daily["wins"] or 0)
  return {"rolling_24h":{"trades":dn,"wins":dw,"win_rate":round(dw/dn,4) if dn else None,"realized_pnl":float(daily["pnl"] or 0)},"trades":n,"wins":w,"win_rate":round(w/n,4) if n else None,"realized_pnl":float(agg["pnl"] or 0),
    "avg_pnl":float(agg["avg_pnl"]) if agg["avg_pnl"] is not None else None,
    "by_symbol":{r["symbol"]:{"trades":int(r["trades"] or 0),"wins":int(r["wins"] or 0),
      "win_rate":round(int(r["wins"] or 0)/int(r["trades"]),4) if int(r["trades"] or 0) else None,
      "pnl":float(r["pnl"] or 0),"avg_pnl":float(r["avg_pnl"]) if r["avg_pnl"] is not None else None,
      "avg_exposure_fill_ratio":float(r["avg_fill"]) if r["avg_fill"] is not None else None} for r in rows}}
 except Exception as exc:return {"error":type(exc).__name__+":"+str(exc)[:160]}

def pandora_live_state_loop():
 # Process-independent Pandora Win mark-to-market snapshot for the monitor.
 # The lease owner publishes one compact row per second from the live Bybit price cache.
 while not SHUTDOWN.is_set():
  try:
   with LOCK:
    active=bool(S.get("engine_active"))
    prices=copy.deepcopy(S.get("_prices",{}))
    price_epoch=float(S.get("_last_poll_epoch",0) or 0)
    positions=copy.deepcopy(S.get("pandora_win_positions",{}))
    realized_equity=float(S.get("pandora_equity",PANDORA_STARTING_EQUITY) or PANDORA_STARTING_EQUITY)
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
    payload_prices={s:float(prices[s]) for s in pandora_runtime_symbols() if s in prices}
    with pg() as db:
     with db.transaction():
      STORE.fence(db)
      db.execute("""insert into pandora_win_live_state(id,ts,commit,prices,positions,unrealized_pnl,total_equity,price_age_seconds,source)
       values(1,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,'bybit_v5_public_linear')
       on conflict(id) do update set ts=excluded.ts,commit=excluded.commit,prices=excluded.prices,
       positions=excluded.positions,unrealized_pnl=excluded.unrealized_pnl,total_equity=excluded.total_equity,
       price_age_seconds=excluded.price_age_seconds,source=excluded.source""",
       (now(),os.getenv("RENDER_GIT_COMMIT"),json.dumps(payload_prices),json.dumps(pos_state,default=str),
        unreal,realized_equity+unreal,age))
    with LOCK:S["last_checkpoint"]=now()
    with LOCK:S["pandora_live_state"]={"ts":now(),"price_age_seconds":age,"prices":payload_prices,
      "unrealized_pnl":unreal,"total_equity":realized_equity+unreal,"positions":pos_state}
  except Exception as exc:
   with LOCK:S["sources"]["PandoraLiveState"]={"ok":False,"last_check":now(),
     "error":type(exc).__name__+":"+str(exc)[:160]}
  else:
   with LOCK:S["sources"]["PandoraLiveState"]={"ok":True,"last_check":now(),
     "mode":"durable_1s_bybit_marks","interval_seconds":1}
  SHUTDOWN.wait(1)

def bybit_local_history(symbol,interval="1h",limit=120):
 """Read-only Bybit V5 kline bootstrap converted to the normalized candle shape."""
 bybit_interval={"1h":"60","15m":"15"}.get(interval)
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
   start=int(x[0]);rows.append({"s":str(symbol),"i":interval,"t":start,"T":start+int({"1h":3600000,"15m":900000}[interval]),
    "o":str(x[1]),"h":str(x[2]),"l":str(x[3]),"c":str(x[4]),"v":str(x[5]),"n":0,"venue":"bybit"})
  except (IndexError,TypeError,ValueError):continue
 return rows

def pandora_token_totals():
 with pg() as db:
  rows=db.execute("""select symbol,count(*) as closed_trades,
   coalesce(sum(pnl),0) as realized_pnl,sum(case when pnl>0 then 1 else 0 end) as wins
   from pandora_win_trade_history group by symbol order by symbol""").fetchall()
 return [{'account':'pandora_win',**dict(row)} for row in rows]

def pandora_history_page(account="pandora_win",before_id=None,limit=100,symbol=None):
 if account!="pandora_win":raise ValueError("unknown_account")
 limit=max(1,min(500,int(limit)));params=[];conditions=[]
 if before_id is not None:
  conditions.append("id < %s");params.append(int(before_id))
 if symbol:
  conditions.append("symbol = %s");params.append(str(symbol).upper())
 where=" where "+" and ".join(conditions) if conditions else ""
 params.append(limit+1)
 with pg() as db:
  rows=[dict(r) for r in db.execute(f"select * from pandora_win_trade_history{where} order by id desc limit %s",tuple(params)).fetchall()]
 more=len(rows)>limit;rows=rows[:limit]
 rows=[trade_monitor_snapshot(trade) for trade in rows]
 return {"account":account,"trades":rows,"next_before_id":rows[-1]["id"] if rows and more else None,
  "basis":"all_recorded_rows_without_pnl_exclusions","symbol":symbol}

def pandora_event_page(before_id=None,limit=100):
 limit=max(1,min(500,int(limit)));params=[]
 before=" and id < %s" if before_id is not None else ""
 if before_id is not None:params.append(int(before_id))
 params.append(limit+1)
 with pg() as db:
  rows=[dict(r) for r in db.execute("""select id,recorded_at,kind,payload from pandora_win_audit_journal
   where (kind in ('pandora_trade_opened','pandora_trade_closed') or left(kind,8)='pandora_')"""+before+
   " order by id desc limit %s",tuple(params)).fetchall()]
 more=len(rows)>limit;rows=rows[:limit]
 return {"events":rows,"next_before_id":rows[-1]["id"] if rows and more else None}

def trade_monitor_snapshot(row):
 trade=dict(row);features=trade.get('features') or {}
 margin=float(trade.get('margin') or 0)
 trade.update(entry_price=features.get('original_entry',features.get('entry_mark',trade.get('entry'))),
  entry_time=trade.get('opened'),average_entry=trade.get('entry'),
  entry_local={k:features.get(k) for k in ('pivot_type','pivot_price','pivot_candle_time','signal_candle_time','confirmation_source')},
  exit_local=features.get('exit_analysis') or features.get('local_state') or {},
  pnl_usdt=trade.get('pnl'),
  pnl_percent=float(trade['pnl'])/margin*100 if trade.get('pnl') is not None and margin>0 else None)
 return trade

def pandora_history(limit=100):
 # Actual immutable account ledger, including all historical outcomes.
 with pg() as db:
  rows=db.execute("""select id,opened,closed,symbol,side,entry,exit,pnl,
    reason,margin,notional,leverage,features from pandora_win_trade_history
    order by closed desc,id desc limit %s""",(int(limit),)).fetchall()
 return [trade_monitor_snapshot(row) for row in rows]

def pandora_today_pnl():
 with pg() as db:
  return float(db.execute("""select coalesce(sum(pnl),0) as pnl from pandora_win_trade_history
    where closed::timestamptz >= date_trunc('day',now())""").fetchone()["pnl"])

def engine_coordinator():
 while not SHUTDOWN.is_set():
  S['_coordinator_heartbeat']=time.time()
  try:
   owned=STORE.claim()
   if owned and not S['engine_active']:
    with ACCOUNT_LOCK:
     restore_state()
     if WIN is not None:WIN.refresh_after_lease()
   with LOCK:S['engine_active']=owned;S['engine_error']=None if owned else 'standby: another engine owns the lease'
  except Exception as error:
   with LOCK:S['engine_active']=False;S['engine_error']=type(error).__name__+':'+str(error)[:160]
  SHUTDOWN.wait(5)
 with LOCK:S['engine_active']=False
 try:STORE.release()
 except Exception:pass

def needs_local_history(symbol):
 try:
  h1_rows,stamp=_pandora_h1_candles(symbol);m15_rows,_=_local_m15_candles(symbol)
  if not analyze_pandora_h1(h1_rows,stamp,symbol).get('ready'):return True
  latest=max(int(row['t']) for row in h1_rows if int(row['T'])<=stamp-1000)
  expected=int((stamp-1000)//3600000*3600000-3600000)
  m15=sorted((row for row in m15_rows if int(row['T'])<=stamp-1000),key=lambda row:int(row['t']))
  if len(m15)<5:return True
  recent=m15[-5:]
  return (latest<expected or not 0<=stamp-int(recent[-1]['T'])<1020000 or
          any(abs(int(b['t'])-int(a['t'])-900000)>1000 for a,b in zip(recent,recent[1:])))
 except (RuntimeError,ValueError,TypeError,KeyError):return True

def market_history_bootstrap():
 global HISTORY_BOOTSTRAP
 def selected():
  with LOCK:return tuple((S.get('bybit_discovery') or {}).get('selected_symbols') or ()) if S.get('engine_active') else ()
 def retained():
  with LOCK:return tuple(dict.fromkeys(tuple(S.get('pandora_win_positions',{}))+tuple(S.get('pandora_watch',{})))) if S.get('engine_active') else ()
 def candidates():
  if not S.get('engine_active'):return ()
  with LOCK:pool=tuple((S.get('bybit_discovery') or {}).get('candidate_symbols') or ())
  return pool
 def accept(rows,history=True):
  if S.get('engine_active'):accept_local_candles(rows,history=history)
 def checkpoint():
  if S.get('engine_active'):checkpoint_local_candles()
 def report(symbol,value):
  with LOCK:S['sources']['H1History:'+symbol]={**value,'last_check':now()}
  TRADE_WAKE.set()
 HISTORY_BOOTSTRAP=HistoryBootstrap(SHUTDOWN,bybit_local_history,accept,checkpoint,report,
  needs_local_history,selected,retained,candidates)
 HISTORY_BOOTSTRAP.run()

def pandora_loop():
 while not SHUTDOWN.is_set():
  if not S['engine_active']:SHUTDOWN.wait(.5);continue
  for symbol in pandora_runtime_symbols():
   try:
    rows,stamp=_pandora_h1_candles(symbol);analysis=pandora_win_h1_direction(rows,stamp,symbol)
    with LOCK:S.setdefault('_pandora_analysis',{})[symbol]=analysis
   except Exception as error:
    with LOCK:S['sources']['H1Scan:'+symbol]={'ok':False,'last_check':now(),'error':type(error).__name__+':'+str(error)[:140]}
  TRADE_WAKE.set();SHUTDOWN.wait(1)

def _stream_group(trades):
 count=2 if trades else max(1,min(8,int(os.getenv('BYBIT_AUX_WS_SHARDS','2'))))
 def symbols():return set(pandora_runtime_symbols())
 def worker(index):
  key=('MarketTradeStream:' if trades else 'MarketQuotes:')+str(index)
  def report(state):
   with LOCK:S['sources'][key]={'last_check':now(),**state}
  def quote(prices):accept_market_prices(prices);TRADE_WAKE.set()
  stable_shard=lambda symbol:int(hashlib.sha1(str(symbol).encode()).hexdigest()[:8],16)%count
  run_bybit_stream(MARKET_OBS if trades else MARKET_AUX_OBS,SHUTDOWN,symbols,report,
   symbol_filter=lambda symbol:stable_shard(symbol)==index,
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
  anchors=copy.deepcopy(S.get('_pandora_analysis',{}));received=dict(S['_price_received_epoch'])
  instruments=copy.deepcopy(S.get('_bybit_instruments',{}))
 for symbol in pandora_trade_symbols():
  instrument=instruments.get(symbol) or {}
  tokens[symbol]={'h1':pandora_runtime_h1_verified(symbol,anchors.get(symbol),stamp),
   'executed_flow':bool(MARKET_OBS.flow_context(symbol,stamp).get('trade_data_fresh')),
   'evidence_ready':bool(MARKET_OBS.flow_context(symbol,stamp).get('evidence_ready')),
   'mark':0<=stamp-received.get(symbol,0)<=10,
   'contract':bool(instrument and 0<=stamp-float(instrument.get('observed_at',0))<=86400)}
 execution_age=stamp-float(S.get('_execution_heartbeat',0))
 execution_ok=bool(S.get('_execution_ok')) and 0<=execution_age<10
 checkpoint_age=stamp-checkpoint if checkpoint else None
 healthy=not SHUTDOWN.is_set() and stamp-S.get('_coordinator_heartbeat',stamp)<45
 return {'healthy':healthy,'risk_ready':bool(healthy and active and execution_ok and not (S.get('bybit_discovery') or {}).get('selection_frozen') and (S.get('risk_circuit') or {}).get('allowed',True) and checkpoint_age is not None and 0<=checkpoint_age<15 and bool(tokens) and all(all(r.values()) for r in tokens.values())),
  'execution_ok':execution_ok,'execution_running':bool(S.get('_execution_running')),'execution_age_seconds':execution_age,'execution_errors':copy.deepcopy(S.get('_execution_errors',{})),
  'engine_active':active,'engine_error':S.get('engine_error'),'mode':'PAPER_ONLY','version':os.getenv('RENDER_GIT_COMMIT','local-unpublished'),
  'token_readiness':tokens,'checkpoint_age_seconds':checkpoint_age,
  'market_age_seconds':stamp-S['_last_poll_epoch'] if S['_last_poll_epoch'] else None}


def dashboard_history_loop():
 while not SHUTDOWN.is_set():
  try:
   value={'trades':pandora_history(300),'token_totals':pandora_token_totals(),
    'events':pandora_event_page(limit=50),'at':now(),'error':None}
   with LOCK:S['_dashboard_history']=value
  except Exception as error:
   with LOCK:S.setdefault('_dashboard_history',{})['error']=type(error).__name__+':'+str(error)[:160]
  SHUTDOWN.wait(5)

def build_dashboard_snapshot(history=None):
 with LOCK:state=copy.deepcopy(S)
 history=history if history is not None else state.get('_dashboard_history',{})
 positions=[];unreal=0.;all_marks=True
 for symbol,pos in state['pandora_win_positions'].items():
  stamp=state['_price_received_epoch'].get(symbol,0)
  mark=state['_prices'].get(symbol) if 0<=time.time()-stamp<=10 else None
  pnl=paper_pnl(pos['notional'],pos['entry'],mark,pos['side'],FEE) if mark is not None else None
  all_marks=all_marks and mark is not None
  if pnl is not None:unreal+=pnl
  positions.append({'symbol':symbol,'side':'LONG' if pos['side']>0 else 'SHORT','opened':pos['opened'],'entry':pos['entry'],
   'entry_price':(pos.get('features') or {}).get('original_entry',(pos.get('features') or {}).get('entry_mark',pos['entry'])),
   'entry_time':pos['opened'],'average_entry':pos['entry'],
   'entry_local':{k:(pos.get('features') or {}).get(k) for k in ('pivot_type','pivot_price','pivot_candle_time','signal_candle_time','confirmation_source')},
   'current_local':state.get('_pandora_analysis',{}).get(symbol) or state.get('pandora_win_h1_direction',{}).get(symbol) or {},
   'pnl_usdt':pnl,'mark':mark,'unrealized_pnl':pnl,'margin_usd':pos['margin'],'notional_usd':pos['notional'],'leverage':pos['leverage'],'effective_leverage':pos['notional']/pos['margin'] if pos['margin'] else None,'pnl_percent':pnl/pos['margin']*100 if pnl is not None and pos['margin'] else None,'features':pos.get('features') or {}})
 details={}
 for symbol in pandora_runtime_symbols():
  flow=MARKET_OBS.flow_context(symbol)
  anchor=state.get('_pandora_analysis',{}).get(symbol) or state['pandora_win_h1_direction'].get(symbol) or {}
  details[symbol]={'h1_local':anchor,'flow_context':flow,'last_action':(state.get('pandora_executor_rejections',{}).get(symbol) or {}).get('reason')}
 primary={'starting_equity':500.,'realized_equity':state['pandora_equity'],
  'realized_pnl':state['pandora_realized_pnl'],'unrealized_pnl':unreal if all_marks else None,
  'total_equity':state['pandora_equity']+unreal if all_marks else None,
  'open_positions':positions,'closed_trades':history.get('trades',[]),'token_totals':history.get('token_totals'),
  'events':history.get('events',{}),'watch':state['pandora_watch'],'h1_durable':state['pandora_win_h1_direction'],
  'engine':{'details':details,'symbols':list(pandora_runtime_symbols())},
  'risk':state.get('risk_circuit',{}),'margin_valuation':state.get('margin_valuation',{}),
  'account':state.get('pandora_account',{}),'runtime':WIN.snapshot() if WIN is not None else {}}
 selected_rows=(state.get('bybit_discovery') or {}).get('selected') or []
 token_rows=[]
 for row in selected_rows:
  symbol=row['symbol'];detail=details.get(symbol,{})
  flow=detail.get('flow_context',{});local=detail.get('h1_local',{})
  position=next((p for p in positions if p['symbol']==symbol),{})
  features=position.get('features') or {}
  token=WIN.tokens.get(symbol,{}) if WIN is not None else {}
  token_rows.append({**row,'price':fresh_mark_price(symbol),
   'confirmed_local':local.get('confirmed_local') or local,'forming_local':local.get('forming_local'),
   'forming_locals':local.get('forming_locals',[]),'direction':local.get('entry_side'),
   'buy_volume':flow.get('buy_notional'),'sell_volume':flow.get('sell_notional'),
   'flow_imbalance':flow.get('flow_imbalance'),'flow_state':flow,'local_state':local,
   'state':token.get('state','SELECTED'),'position':position,'entry':features.get('original_entry',position.get('entry')),
   'average_entry':position.get('entry'),'margin':position.get('margin_usd'),'notional':position.get('notional_usd'),
   'leverage':position.get('leverage'),'pyramid_level':features.get('pyramid_level',0),
   'entry_price':position.get('entry_price'),'entry_time':position.get('entry_time'),'entry_local':position.get('entry_local'),
   'current_pnl_usd':position.get('unrealized_pnl'),'current_pnl_pct':position.get('pnl_percent'),
   'mfe':features.get('peak_mfe_usd'),'mae':features.get('mae_usd'),'mfe_giveback':features.get('mfe_giveback_usd'),
   'last_action':token.get('action'),'action_reason':token.get('reason')})
 checkpoint=publication_epoch(state.get('last_checkpoint'))
 checkpoint_ready=checkpoint is not None and 0<=time.time()-checkpoint<=15
 for token in token_rows:
  symbol=token['symbol'];rejection=state.get('pandora_executor_rejections',{}).get(symbol) or {}
  rejected_at=publication_epoch(rejection.get('at'))
  recent_reason=rejection.get('reason') if rejected_at and 0<=time.time()-rejected_at<5 else None
  token['decision']=entry_status(symbol,token['local_state'],token['flow_state'],token.get('position'),
   state.get('pandora_watch',{}).get(symbol),active=bool(state.get('engine_active')),
   scanner_ready=not (state.get('bybit_discovery') or {}).get('selection_frozen',False),
   instrument_ready=symbol in state.get('_bybit_instruments',{}),
   h1_verified=pandora_runtime_h1_verified(symbol,token['local_state']),
   mark=fresh_mark_price(symbol),checkpoint_ready=checkpoint_ready,rejection=recent_reason,stamp=time.time())
  if not token.get('position'):
   token['action_reason_code']=token['decision']['reason']
   token['action_reason']=token['decision']['message']
   token['last_action']=token['decision']['action']
 primary['tokens']=token_rows
 observed=0
 if WIN is not None:
  with WIN.scanner.lock:observed=len(WIN.scanner.markets)
 primary['startup']=startup_snapshot(state,token_rows,observed_markets=observed,
  history=HISTORY_BOOTSTRAP.snapshot() if HISTORY_BOOTSTRAP is not None else {})
 totals=[row for row in history.get('token_totals') or [] if row.get('account')=='pandora_win']
 closed_count=sum(int(row.get('closed_trades') or 0) for row in totals)
 wins=sum(int(row.get('wins') or 0) for row in totals)
 primary['statistics']={'closed_trades':closed_count,'wins':wins,'nonwinning':closed_count-wins,'win_rate_percent':wins/closed_count*100 if closed_count else None,'basis':'all_canonical_closed_trades_including_losses'} if history.get('token_totals') is not None else None
 primary['total_pnl_usdt']=primary['total_equity']-500 if primary['total_equity'] is not None else None
 primary['total_pnl_percent']=primary['total_pnl_usdt']/500*100 if primary['total_pnl_usdt'] is not None else None
 primary['realized_pnl_percent']=primary['realized_pnl']/500*100
 primary['max_equity']=(state.get('pandora_account') or {}).get('max_equity',500.)
 primary['current_exposure']=sum(float(p['notional_usd'])*float(p['mark'])/float(p['entry']) for p in positions) if all_marks else None
 primary['pyramid_adds']=[]
 if WIN is not None:
  with pg() as db:
   primary['pyramid_adds']=[{**row['payload'],'symbol':row['symbol'],'opened':row['opened']} for row in db.execute('select symbol,opened,payload from pandora_win_pyramid_adds order by id desc limit 200').fetchall()]
 primary['re_entries']=[t for t in history.get('trades',[]) if (t.get('features') or {}).get('entry_kind')=='REENTRY']
 primary['reversals']=[t for t in history.get('events',{}).get('events',[]) if str(t.get('kind','')).startswith('pandora_REVERSE_')]
 primary['token_rotations']=[t for t in history.get('events',{}).get('events',[]) if t.get('kind') in ('pandora_TOKEN_ROTATED','pandora_ROTATE_OUT')]
 return {'api_version':API_VERSION,'snapshot_id':int(time.time()*1000),'mode':'PAPER_ONLY',
  'freshness':{'market_at':state.get('last_poll'),'history_at':history.get('at'),'scanner_at':(state.get('bybit_discovery') or {}).get('at'),'execution_at':state.get('_execution_heartbeat')},
  'pandora':primary,
  'pandora_symbols':list(pandora_runtime_symbols()),
  'discovery':state.get('bybit_discovery',{}),
  'health':health_state(),'sources':state['sources'],'pandora_entry_diagnostics':state.get('pandora_entry_diagnostics',{}),
  'history_error':history.get('error'),'history_updated_at':history.get('at'),'positions':[],'snapshot_at':now()}

def dashboard():return build_dashboard_snapshot()
def html_dashboard(data):
 from pandora_monitor import render
 return render(data)

class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def send(self,code,result,content_type='application/json; charset=utf-8'):
  body=result.encode('utf-8') if isinstance(result,str) else json.dumps(json_safe(result),ensure_ascii=False,default=str,allow_nan=False).encode('utf-8')
  self.send_response(code);self.send_header('Content-Type',content_type);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers()
  try:self.wfile.write(body)
  except (BrokenPipeError,ConnectionResetError):pass
 def do_GET(self):
  parsed=urllib.parse.urlsplit(self.path);args=urllib.parse.parse_qs(parsed.query);path=parsed.path
  try:
   if path=='/openapi.json':self.send(200,openapi(os.getenv('RENDER_EXTERNAL_URL') or 'http://localhost:'+os.getenv('PORT','10000')))
   elif path in ('/health','/health/risk'):
    result=health_state();self.send(200 if result['healthy' if path=='/health' else 'risk_ready'] else 503,result)
   elif path=='/':self.send(200,html_dashboard(dashboard()),'text/html; charset=utf-8')
   elif path in ('/api/dashboard','/api/pandora','/status'):self.send(200,dashboard())
   elif path in ('/api/pandora/history','/pandora/history'):
    result=pandora_history_page('pandora_win',args.get('before',[None])[0],int(args.get('limit',['100'])[0]),args.get('symbol',[None])[0])
    if path=='/pandora/history':
     from pandora_monitor import render_history
     self.send(200,render_history(result),'text/html; charset=utf-8')
    else:self.send(200,result)
   elif path=='/api/pandora/events':self.send(200,pandora_event_page(args.get('before',[None])[0],int(args.get('limit',['100'])[0])))
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
   request=json.loads(self.rfile.read(size));symbols=list(S['pandora_win_positions']) if request.get('all') else [request.get('symbol')]
   results=[]
   for symbol in symbols:
    price=current_entry_price(symbol)
    if price is None:results.append({'symbol':symbol,'error':'fresh_mark_unavailable'});continue
    results.append(pandora_close(symbol,price,'operator_paper_close'))
   self.send(200,{'results':results})
  except (ValueError,TypeError):self.send(400,{'error':'invalid_request'})
  except Exception:self.send(503,{'error':'close_not_confirmed'})


def render_keepalive_loop():
 # Free Render sleeps after 15 minutes without inbound traffic. During PAPER A/B
 # tests, keep the public health endpoint active without touching trading logic.
 url=(os.getenv('RENDER_EXTERNAL_URL') or 'https://pandora-testnet-monitor-nfoc.onrender.com').rstrip('/')+'/health'
 while not SHUTDOWN.wait(240):
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'pandora-render-keepalive/1.0','Cache-Control':'no-cache'})
   with urllib.request.urlopen(req,timeout=30) as response:
    code=int(response.getcode() or 0)
   with LOCK:S['sources']['RenderKeepalive']={'ok':200<=code<500,'last_check':now(),'http_status':code}
  except Exception as error:
   with LOCK:S['sources']['RenderKeepalive']={'ok':False,'last_check':now(),'error':type(error).__name__+':'+str(error)[:160]}

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
  ('h1_history',market_history_bootstrap),('h1_scan',pandora_loop),('execution',pandora_risk_loop),
  ('checkpoint',pandora_live_state_loop),('history',dashboard_history_loop),('keepalive',render_keepalive_loop)]
 workers=[threading.Thread(target=supervise,args=job,daemon=True,name=job[0]) for job in jobs]
 for worker in workers:worker.start()
 try:server.serve_forever()
 finally:
  SHUTDOWN.set();server.server_close()
  for worker in workers:worker.join(3)
  try:STORE.release()
  except Exception:pass

if __name__=='__main__':main()
