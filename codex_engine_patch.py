from pathlib import Path
p=Path("/app/codex_engine/app.py")
s=p.read_text()

old="def pg():return psycopg.connect(os.environ['DATABASE_URL'],autocommit=True,row_factory=dict_row,connect_timeout=5)"
new="""def pg():
 db=psycopg.connect(os.environ['DATABASE_URL'],autocommit=False,row_factory=dict_row,connect_timeout=5)
 db.execute('SET LOCAL search_path TO codex_million')
 return db"""
if old not in s: raise SystemExit("Codex pg() signature changed")
s=s.replace(old,new)

# The frozen revision ranks every second and also changes the active basket every
# second. That makes a newly-selected token disappear before H1/M15 bootstrap and
# 15s executed-flow evidence can finish. Keep market ticker ingestion continuous,
# but hold each active TOP-5 basket for one minute so locals/flow can become usable.
old_wait="   TRADE_WAKE.set();SHUTDOWN.wait(1)\n finally:\n  for worker in workers:worker.join(3)"
new_wait="   TRADE_WAKE.set();SHUTDOWN.wait(float(os.getenv('PANDORA_DISCOVERY_SCAN_SECONDS','60')))\n finally:\n  for worker in workers:worker.join(3)"
if old_wait not in s: raise SystemExit("Codex discovery loop signature changed")
s=s.replace(old_wait,new_wait)

# Do not spend H1/M15 bootstrap and trade-stream capacity on all 30 ranking
# candidates. Pre-warm only the next five candidates plus the active basket,
# retained positions/watches and the base symbols.
old_pool="with LOCK:pool=tuple((S.get('bybit_discovery') or {}).get('candidate_symbols') or ())"
new_pool="with LOCK:pool=tuple((S.get('bybit_discovery') or {}).get('candidate_symbols') or ())"
if old_pool not in s: raise SystemExit("Codex runtime-symbol pool signature changed")
s=s.replace(old_pool,new_pool)

# Faster read-only diagnostics while the active five are warming.
s=s.replace("if time.time()-last_entry_diagnostics>=30:","if time.time()-last_entry_diagnostics>=5:")


# Give the frozen Codex engine the bounded selected-first history bootstrap from
# the current repository. This keeps the active TOP-5 ahead of background names.
import shutil, re
bootstrap_src=Path("/app/pandora_bootstrap.py")
bootstrap_dst=Path("/app/codex_engine/pandora_bootstrap.py")
if bootstrap_src.exists():
 shutil.copyfile(bootstrap_src,bootstrap_dst)
if "from pandora_bootstrap import HistoryBootstrap" not in s:
 s=s.replace("from pandora_runtime import PandoraRuntime\n",
             "from pandora_runtime import PandoraRuntime\nfrom pandora_bootstrap import HistoryBootstrap\n")

bootstrap_code=r'''def needs_local_history(symbol):
 try:
  h1_rows,stamp=_local_h1_candles(symbol);m15_rows,_=_local_m15_candles(symbol)
  closed_h1=[r for r in h1_rows if int(r['T'])<=stamp-1000]
  closed_m15=sorted((r for r in m15_rows if int(r['T'])<=stamp-1000),key=lambda r:int(r['t']))
  if len(closed_h1)<6 or len(closed_m15)<5:return True
  latest_h1=max(int(r['t']) for r in closed_h1)
  expected=int((stamp-1000)//3600000*3600000-3600000)
  if latest_h1<expected:return True
  if not 0<=stamp-int(closed_m15[-1]['T'])<1020000:return True
  return False
 except Exception:return True

def market_history_bootstrap():
 global HISTORY_BOOTSTRAP
 def selected():
  with LOCK:return tuple((S.get('bybit_discovery') or {}).get('selected_symbols') or ()) if S.get('engine_active') else ()
 def retained():
  with LOCK:return tuple(dict.fromkeys(tuple(S.get('local_v12_positions',{}))+tuple(S.get('local_experiment_watch',{})))) if S.get('engine_active') else ()
 def candidates():
  if not S.get('engine_active'):return ()
  with LOCK:return tuple(((S.get('bybit_discovery') or {}).get('candidate_symbols') or ())[:50])
 def report(symbol,value):
  with LOCK:S['sources']['H1History:'+symbol]={**value,'last_check':now()}
  TRADE_WAKE.set()
 HISTORY_BOOTSTRAP=HistoryBootstrap(SHUTDOWN,bybit_local_history,accept_local_candles,
  checkpoint_local_candles,report,needs_local_history,selected,retained,candidates,
  selected_workers=5,background_workers=1,requests_per_second=5,poll_interval=.2,retry_min=3,retry_max=20)
 HISTORY_BOOTSTRAP.run()
'''
pattern=r"def market_history_bootstrap\(\):\n.*?\ndef local_experiment_loop\(\):"
replacement=bootstrap_code+"\ndef local_experiment_loop():"
s,n=re.subn(pattern,replacement,s,flags=re.S)
if n!=1: raise SystemExit("Codex market_history_bootstrap signature changed")


# Active Codex basket must be tradeable, not merely the five fastest ticker
# changes. Rank the market continuously, then activate the highest-ranked
# candidates that already have a durable confirmed H1 local. The selected-first
# bootstrap immediately refreshes those locals and executed-flow subscriptions.
old_rank="""   snapshot=scanner.rank(instruments,MARKET_OBS.flow_context,held)
   WIN.scanner_snapshot(snapshot)
   with LOCK:S['sources']['BybitDiscovery']={'ok':bool(snapshot['selected_symbols']),'at':now(),'selected':len(snapshot['selected_symbols']),'mode':'LIVE_STREAM'}"""
new_rank="""   raw_snapshot=scanner.rank(instruments,MARKET_OBS.flow_context,held)
   with LOCK:
    anchors=copy.deepcopy(S.get('local_h1_direction',{}))
    active_before=tuple((S.get('bybit_discovery') or {}).get('selected_symbols') or ())
   ranked=list(raw_snapshot.get('top_movers') or raw_snapshot.get('selected') or [])
   ready=[]
   for row in ranked:
    symbol=row.get('symbol');anchor=anchors.get(symbol) or {}
    try:
     local_ok=bool(anchor.get('ready') and anchor.get('anchor_confirmed') and anchor.get('pivot_type') and
      float(anchor.get('pivot_price') or 0)>0 and int(anchor.get('entry_side') or 0) in (-1,1) and
      not anchor.get('entry_blocked') and anchor.get('live_structure_fresh') is not False)
    except (TypeError,ValueError,OverflowError):
     local_ok=False
    if row.get('eligible') and local_ok:
     candidate=dict(row)
     candidate['_activation_flow_ready']=bool(row.get('flow_fresh'))
     candidate['_activation_local_live']=bool(anchor.get('live_structure_fresh') is not False and not anchor.get('entry_blocked'))
     ready.append(candidate)
   ready.sort(key=lambda row:(not row.get('_activation_flow_ready'),int(row.get('rank') or 999999),row.get('symbol') or ''))
   chosen=ready[:DISCOVERY_MAX_SELECTED]
   symbols=[row['symbol'] for row in chosen]
   # Do not publish a raw no-local basket. During startup keep the prior
   # confirmed-local basket until enough ranked candidates are prepared.
   if len(symbols)<DISCOVERY_MAX_SELECTED:
    prior_rows={row.get('symbol'):row for row in ranked}
    for symbol in active_before:
     if symbol in symbols:continue
     anchor=anchors.get(symbol) or {}
     try:
      local_ok=bool(anchor.get('ready') and anchor.get('anchor_confirmed') and anchor.get('pivot_type') and
       float(anchor.get('pivot_price') or 0)>0 and int(anchor.get('entry_side') or 0) in (-1,1) and
       not anchor.get('entry_blocked') and anchor.get('live_structure_fresh') is not False)
     except (TypeError,ValueError,OverflowError):
      local_ok=False
     if local_ok and symbol in prior_rows:
      chosen.append(prior_rows[symbol]);symbols.append(symbol)
      if len(symbols)>=DISCOVERY_MAX_SELECTED:break
   snapshot=copy.deepcopy(raw_snapshot)
   for row in chosen:
    row.pop('_activation_flow_ready',None);row.pop('_activation_local_live',None)
   snapshot['selected']=chosen[:DISCOVERY_MAX_SELECTED]
   snapshot['selected_symbols']=symbols[:DISCOVERY_MAX_SELECTED]
   snapshot['activation_basis']='fresh_unblocked_confirmed_local_then_executed_flow_then_rank'
   snapshot['raw_selected_symbols']=raw_snapshot.get('selected_symbols') or []
   events=[]
   for symbol in active_before:
    if symbol not in snapshot['selected_symbols']:
     events.append(dict(action='TOKEN_ROTATED',symbol=symbol,state='FADING' if symbol in held else 'ROTATE_OUT',
      reason='replaced_by_higher_ranked_local_ready_candidate'))
   for symbol in snapshot['selected_symbols']:
    if symbol not in active_before:
     events.append(dict(action='TOKEN_SELECTED',symbol=symbol,reason='ranked_candidate_with_confirmed_h1_local'))
   snapshot['events']=events
   states=dict(raw_snapshot.get('states') or {})
   for symbol in active_before:
    if symbol not in snapshot['selected_symbols']:states[symbol]='FADING' if symbol in held else 'ROTATE_OUT'
   for symbol in snapshot['selected_symbols']:states[symbol]='SELECTED'
   snapshot['states']=states
   with scanner.lock:
    scanner.selected=list(snapshot['selected_symbols']);scanner.states=dict(states);scanner.last_snapshot=copy.deepcopy(snapshot)
   WIN.scanner_snapshot(snapshot)
   with LOCK:S['sources']['BybitDiscovery']={'ok':bool(snapshot['selected_symbols']),'at':now(),'selected':len(snapshot['selected_symbols']),'mode':'LIVE_STREAM_LOCAL_READY'}"""
if old_rank not in s: raise SystemExit("Codex scanner publish signature changed")
s=s.replace(old_rank,new_rank)

# Spread the broader candidate flow warmup across four Bybit trade sockets.
s=s.replace("count=2 if trades else max(1,min(8,int(os.getenv('BYBIT_AUX_WS_SHARDS','2'))))",
            "count=4 if trades else max(1,min(8,int(os.getenv('BYBIT_AUX_WS_SHARDS','2'))))")

p.write_text(s)
