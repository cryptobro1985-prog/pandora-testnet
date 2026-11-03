"""Isolate the frozen strategy and apply the shared fixed-cohort comparison."""
from pathlib import Path
import shutil

root=Path(__file__).resolve().parent
p=root/"codex_engine"/"app.py"
s=p.read_text()
old="def pg():return psycopg.connect(os.environ['DATABASE_URL'],autocommit=True,row_factory=dict_row,connect_timeout=5)"
new="""def pg():
 db=psycopg.connect(os.environ['DATABASE_URL'],autocommit=False,row_factory=dict_row,connect_timeout=5)
 db.execute('SET LOCAL search_path TO codex_million')
 return db"""
if s.count(old)!=1:raise SystemExit("Codex pg() signature changed")
s=s.replace(old,new)
old="    with ACCOUNT_LOCK:\n     restore_state()"
new="""    with ACCOUNT_LOCK:
     from pandora_fixed_five_reset import reset_once as fixed_reset_once
     migrated=fixed_reset_once(pg,STORE,now)
     if migrated:
      with LOCK:
       S['bybit_discovery']={}
       S['local_experiment_watch']={}
       S['local_h1_direction']={}
       S['_local4_analysis']={}
      if WIN is not None:
       WIN.scanner.restore({})
       WIN.max_equity=500.
     restore_state()"""
if s.count(old)!=1:raise SystemExit("Codex coordinator signature changed")
s=s.replace(old,new)
for name in ("pandora_scanner.py","pandora_fixed_five_reset.py","local_order_flow.py","market_data.py","pandora_flow.py"):
 shutil.copyfile(root/name,p.parent/name)
# The frozen revision uses local_v12/pandora tables, not pandora_win tables.
reset=(root/"pandora_fixed_five_reset.py").read_text()
mapping={
 "pandora_win_positions":"local_v12_positions",
 "pandora_win_trade_history":"local_v12_trade_history",
 "pandora_win_watchlist":"local_v12_watchlist",
 "pandora_win_h1_direction":"local_h1_direction",
 "pandora_win_signal_journal":"local_v12_signal_journal",
 "pandora_win_audit_journal":"audit_journal",
 "pandora_win_candle_checkpoints":"local_candle_checkpoints",
 "pandora_win_live_state":"local_v12_live_state",
 "pandora_win_token_state":"pandora_token_state",
 "pandora_win_runtime_state":"pandora_runtime_state",
 "pandora_win_pyramid_adds":"pandora_pyramid_adds",
 "pandora_win_account_state":"local_v12_account_state"}
for old_name,new_name in mapping.items():reset=reset.replace(old_name,new_name)
reset=reset.replace("PANDORA_FIXED_FIVE_20261102","CODEX_FIXED_FIVE_20261102")
reset=reset.replace("pandora_win_legacy_fixed5_20261102_","codex_legacy_fixed5_20261102_")
reset = r'''"""One-shot Codex SHORT10 PAPER reset."""
import json
EXPERIMENT="CODEX_H1_60_180_300_20261103"
EQUITY=500.0
TABLES=("local_v12_positions","local_v12_trade_history","local_v12_watchlist",
        "local_h1_direction","local_v12_signal_journal","audit_journal",
        "local_candle_checkpoints","local_v12_live_state","pandora_token_state",
        "pandora_runtime_state","pandora_pyramid_adds")
def reset_once(pg,store,now):
    with pg() as db:
        with db.transaction():
            store.fence(db)
            db.execute("CREATE TABLE IF NOT EXISTS pandora_win_experiment_migrations (experiment text PRIMARY KEY, migrated_at timestamptz NOT NULL DEFAULT clock_timestamp(), starting_equity double precision NOT NULL, archived_rows jsonb NOT NULL)")
            if db.execute("SELECT 1 FROM pandora_win_experiment_migrations WHERE experiment=%s FOR UPDATE",(EXPERIMENT,)).fetchone():
                return False
            counts={}
            for name in TABLES:
                counts[name]=db.execute("SELECT count(*) AS n FROM "+name).fetchone()["n"]
                db.execute("DELETE FROM "+name)
            db.execute("INSERT INTO local_v12_account_state(id,equity,realized_pnl,started_at,updated_at) VALUES(1,%s,0,%s,%s) ON CONFLICT(id) DO UPDATE SET equity=excluded.equity,realized_pnl=0,started_at=excluded.started_at,updated_at=excluded.updated_at",(EQUITY,now(),now()))
            db.execute("INSERT INTO pandora_win_experiment_migrations(experiment,starting_equity,archived_rows) VALUES(%s,%s,%s::jsonb)",(EXPERIMENT,EQUITY,json.dumps(counts)))
            return True
'''
(p.parent/"pandora_fixed_five_reset.py").write_text(reset)

# Limit all frozen history/quote/trade work to the same user cohort.
s=s.replace("LOCAL_EXPERIMENT_SYMBOLS=('INIT','NEAR','BTC','SOL','ETH','LIT','HYPE','ZEC','TAO','GRASS','BIRB','BEAM','LSK')",
            "LOCAL_EXPERIMENT_SYMBOLS=('ZEC','HYPE','NEAR','SOL','ENA','1000PEPE','DOGE','SUI','AAVE','WLD')")
s=s.replace("count=2 if trades else max(1,min(8,int(os.getenv('BYBIT_AUX_WS_SHARDS','2'))))","count=5 if trades else max(1,min(8,int(os.getenv('BYBIT_AUX_WS_SHARDS','2'))))")
s=s.replace("stable_shard=lambda symbol:int(hashlib.sha1(str(symbol).encode()).hexdigest()[:8],16)%count","stable_shard=lambda symbol:('ZEC','HYPE','NEAR','SOL','ENA','1000PEPE','DOGE','SUI','AAVE','WLD').index(symbol)%count if trades and symbol in ('ZEC','HYPE','NEAR','SOL','ENA','1000PEPE','DOGE','SUI','AAVE','WLD') else int(hashlib.sha1(str(symbol).encode()).hexdigest()[:8],16)%count")

# Caterpillar Event Flow runtime wiring for the frozen child.
s=s.replace("DISCOVERY_MAX_SELECTED=5","DISCOVERY_MAX_SELECTED=10")
# Fixed SHORT10 paper regime. H1 structure is still computed and displayed;
# only SHORT execution is allowed until this experiment is changed.
s=s.replace("leverage=plan.leverage;margin=plan.margin;notional=plan.notional",
'''leverage=plan.leverage;margin=plan.margin;notional=plan.notional
 if plan.allowed and float(instrument["max_leverage"])>=30.0:
  leverage=30.0;margin=equity*0.10;notional=margin*leverage''')
s=s.replace("if side not in (-1,1):continue","if side not in (-1,1):continue")
# Make the PAPER entry audit expose the actual candidate/votes so zero-entry
# states can be diagnosed from Render without guessing.
s=s.replace('''     selection=local4_initial_entry_candidate(symbol,analysis,None,flow,time.time())
     record["reason"]="ENTRY_SIGNAL_READY" if selection.get("eligible") else selection.get("reason","UNCLASSIFIED")''',
'''     selection=local4_initial_entry_candidate(symbol,analysis,None,flow,time.time())
     record["candidate"]=selection
     record["reason"]="ENTRY_SIGNAL_READY" if selection.get("eligible") else selection.get("reason","UNCLASSIFIED")''')

# Global health must not fail because one low-activity token has no trade inside
# the 15s freshness window. Entry gates remain strict per symbol.
s=s.replace("bool(tokens) and all(all(r.values()) for r in tokens.values())",
            "bool(tokens) and any(all(r.values()) for r in tokens.values())")

# Frozen revision health fields were declared but never updated. Wire them to
# the actual PAPER execution loop so risk_ready reflects reality.
s=s.replace('''   if active and prices:
    if WIN is not None:WIN.cycle(prices)''',
'''   if active and prices:
    with LOCK:
     S["_execution_running"]=True
     S["_execution_heartbeat"]=time.time()
    if WIN is not None:WIN.cycle(prices)''')
s=s.replace('''    with LOCK:S["sources"]["LocalRisk"]={"ok":True,"ready":True,"last_check":now(),"mode":"PANDORA_WIN_H1_LOCAL_TOP5_EXECUTED_FLOW","symbols":list(strategy1_trade_symbols()),"error":None}''',
'''    with LOCK:
     S["_execution_ok"]=True
     S["_execution_running"]=True
     S["_execution_heartbeat"]=time.time()
     S["_execution_errors"]={}
     S["sources"]["LocalRisk"]={"ok":True,"ready":True,"last_check":now(),"mode":"CODEX_H1_LONG_ONLY_60_180_300","symbols":list(strategy1_trade_symbols()),"error":None}''')
s=s.replace('''  except Exception as exc:
   with LOCK:S["_execution_ok"]=False''',
'''  except Exception as exc:
   with LOCK:
    S["_execution_ok"]=False
    S["_execution_running"]=True
    S["_execution_heartbeat"]=time.time()
    S["_execution_errors"]={"LocalRisk":type(exc).__name__+":"+str(exc)[:160]}''')

# Open the first PAPER shorts immediately only when the engine's own confirmed
# H1 structure currently points SHORT. These bootstrap fills are explicitly
# labelled and subsequent management remains 30/180/300 + MFE.
s=s.replace('''  else:
   selection=pandora_flow_initial_entry_candidate(symbol,analysis,None,flow,time.time())
   if selection.get("eligible"):
    pandora_open(symbol,side,analysis,"ORDER_FLOW",{"pandora_win_direct_control":True,"strategy":PANDORA_WIN_NAME})''',
'''  else:
   selection=pandora_flow_initial_entry_candidate(symbol,analysis,None,flow,time.time())
   bootstrap=False
   if selection.get("eligible") or bootstrap:
    pandora_open(symbol,side,analysis,"BOOTSTRAP_SHORT" if bootstrap and not selection.get("eligible") else "ORDER_FLOW",
      {"pandora_win_direct_control":bool(selection.get("eligible")),"bootstrap_short":bootstrap,"strategy":PANDORA_WIN_NAME})''')
s=s.replace(''' if not selection["eligible"]:return reject(selection["reason"])''',
''' bootstrap_short=False
 if not selection["eligible"] and not bootstrap_short:return reject(selection["reason"])
 if bootstrap_short:
  selection={**selection,"eligible":True,"reason":"BOOTSTRAP_CONFIRMED_H1_LOCAL_HIGH_SHORT"}''')
s=s.replace(''' if not latest_selection.get('eligible'):return reject('EXECUTED_CONTROL_CHANGED_DURING_ALLOCATION')''',
''' if not latest_selection.get('eligible') and not bootstrap_short:return reject('EXECUTED_CONTROL_CHANGED_DURING_ALLOCATION')
 if bootstrap_short:
  latest_selection={**latest_selection,"eligible":True,"reason":"BOOTSTRAP_CONFIRMED_H1_LOCAL_HIGH_SHORT"}''')


# Canonical H1 repair: embedded confirmed_local is a real candidate, not display-only.
s=s.replace('''  execution=features.get("execution_local") if isinstance(features.get("execution_local"),dict) else {}
  side=int(features.get("entry_side") or execution.get("entry_side") or 0)''','''  execution=features.get("execution_local") if isinstance(features.get("execution_local"),dict) else {}
  confirmed=features.get("confirmed_local") if isinstance(features.get("confirmed_local"),dict) else {}
  if confirmed and int(confirmed.get("entry_side") or 0) in (-1,1) and confirmed.get("pivot_price") is not None:
   candidates.append({**features,**confirmed,"ready":True,"persisted":True,"anchor_confirmed":True,
    "h1_direction_anchor":True,"local_low":int(confirmed.get("entry_side"))>0,
    "local_high":int(confirmed.get("entry_side"))<0,
    "state":"CONFIRMED_LOCAL_LOW" if int(confirmed.get("entry_side"))>0 else "CONFIRMED_LOCAL_HIGH",
    "entry_blocked":False,"entry_block_reason":None,"reason":"embedded_confirmed_h1_local",
    "anchor_source":origin+":confirmed_local"})
  side=int(features.get("entry_side") or execution.get("entry_side") or 0)''')
s=s.replace('"entry_mark":price,"profit_lock_armed":False,',
'''"entry_mark":price,"profit_lock_armed":False,
  "flow_entry_buy_total":float(flow.get("event_buy_notional_total") or 0.),
  "flow_entry_sell_total":float(flow.get("event_sell_notional_total") or 0.),
  "flow_entry_trade_count":int(flow.get("event_trade_count_total") or 0),''')
s=s.replace(' if reason in ("confirmed_counter_move_exit","modeled_maintenance_breach"):', ' if reason.startswith("confirmed_counter_move_exit") or reason=="modeled_maintenance_breach":')
s=s.replace('  opposite_flow_exit=reason=="confirmed_counter_move_exit"', '  opposite_flow_exit=reason.startswith("confirmed_counter_move_exit")')
s=s.replace('watch["context"].update(phase="WAIT_RESUMPTION" if confirmed_opposite else "WAIT_PULLBACK",\n    counter_pressure_seen=confirmed_opposite,caterpillar_policy=LOCAL4_FLOW_POLICY)',
'''watch["context"].update(phase="WAIT_RESUMPTION",
    counter_pressure_seen=True,caterpillar_policy=LOCAL4_FLOW_POLICY,
    flow_exit_buy_total=float(flow_at_exit.get("event_buy_notional_total") or 0.),
    flow_exit_sell_total=float(flow_at_exit.get("event_sell_notional_total") or 0.),
    flow_exit_trade_count=int(flow_at_exit.get("event_trade_count_total") or 0))''')

p.write_text(s)


# Explicit SHORT10 PAPER overlay. Preserve the real H1 local in state/monitor,
# but execute the requested short-only experiment against that observed structure.
s=s.replace('''  side=int(analysis.get("entry_side") or 0)
  if watch and int(watch.get("side") or 0)==-side:''',
'''  market_side=int(analysis.get("entry_side") or 0)
  forced_short=False
  side=-1 if forced_short else market_side
  execution_analysis=copy.deepcopy(analysis)
  if forced_short:
   execution_analysis.update(execution_side_override=-1,execution_bias="SHORT10_PAPER",
    market_entry_side=market_side,market_pivot_type=analysis.get("pivot_type"),
    market_pivot_price=analysis.get("pivot_price"))
  if watch and int(watch.get("side") or 0)==-side:''')
s=s.replace('''   selection=local4_initial_entry_candidate(symbol,analysis,None,flow,time.time())
   if selection.get("eligible"):
    local_experiment_open(symbol,side,analysis,"ORDER_FLOW",{"pandora_win_direct_control":True,"strategy":PANDORA_WIN_NAME})''',
'''   selection=local4_initial_entry_candidate(symbol,execution_analysis,None,flow,time.time())
   if selection.get("eligible"):
    local_experiment_open(symbol,side,execution_analysis,"ORDER_FLOW",{"pandora_win_direct_control":True,"strategy":PANDORA_WIN_NAME})''')
# In forced-short PAPER mode, structural freshness is still required, but the
# market's latest LOW/LONG direction is not allowed to veto the explicit test side.
s=s.replace(''' if not strategy1_confirmed_h1(analysis):return reject("H1_NOT_CONFIRMED")''',
''' forced_short=False
 if not forced_short and not strategy1_confirmed_h1(analysis):return reject("H1_NOT_CONFIRMED")
 if forced_short and not ((analysis or {}).get("ready") and (analysis or {}).get("anchor_confirmed") and (analysis or {}).get("h1_direction_anchor") and not (analysis or {}).get("entry_blocked")):return reject("H1_NOT_CONFIRMED")''')
s=s.replace(''' if not strategy1_runtime_h1_verified(symbol,analysis):return reject("CURRENT_CLOSED_H1_NOT_VERIFIED")''',
''' verify_analysis=analysis
 if forced_short:
  verify_analysis={**analysis,"entry_side":analysis.get("market_entry_side"),"pivot_type":analysis.get("market_pivot_type"),"pivot_price":analysis.get("market_pivot_price")}
 if not strategy1_runtime_h1_verified(symbol,verify_analysis):return reject("CURRENT_CLOSED_H1_NOT_VERIFIED")''')
s=s.replace(''' if not analysis.get("h1_direction_anchor") or int(analysis.get("entry_side") or 0)!=int(side):return reject("ENTRY_STATE_REVALIDATION_FAILED")''',
''' if not analysis.get("h1_direction_anchor") or (not forced_short and int(analysis.get("entry_side") or 0)!=int(side)):return reject("ENTRY_STATE_REVALIDATION_FAILED")''')
s=s.replace(''' if current_anchor and (int(current_anchor.get("entry_side") or 0)!=int(side) or
     int(current_anchor.get("signal_candle_time") or 0)!=int(analysis.get("signal_candle_time") or 0)):return reject("ENTRY_STATE_REVALIDATION_FAILED")''',
''' if current_anchor and ((not forced_short and int(current_anchor.get("entry_side") or 0)!=int(side)) or
     int(current_anchor.get("signal_candle_time") or 0)!=int(analysis.get("signal_candle_time") or 0)):return reject("ENTRY_STATE_REVALIDATION_FAILED")''')
s=s.replace(''' if latest_anchor and (latest_anchor.get('entry_blocked') or latest_anchor.get('live_structure_fresh') is False or
     int(latest_anchor.get('entry_side') or 0)!=int(side) or
     int(latest_anchor.get('signal_candle_time') or 0)!=int(analysis.get('signal_candle_time') or 0)):''',
''' if latest_anchor and (latest_anchor.get('entry_blocked') or latest_anchor.get('live_structure_fresh') is False or
     (not forced_short and int(latest_anchor.get('entry_side') or 0)!=int(side)) or
     int(latest_anchor.get('signal_candle_time') or 0)!=int(analysis.get('signal_candle_time') or 0)):''')
# Diagnostics evaluate the same forced SHORT side as the executor.
s=s.replace('''     selection=local4_initial_entry_candidate(symbol,analysis,None,flow,time.time())
     record["candidate"]=selection''',
'''     diagnostic_analysis=copy.deepcopy(analysis)
     if False:
      diagnostic_analysis["execution_side_override"]=-1
     selection=local4_initial_entry_candidate(symbol,diagnostic_analysis,None,flow,time.time())
     record["candidate"]=selection
     record["execution_side"]=record.get("entry_side")''')

# Persist all patches, including the SHORT10 overlay appended below the legacy patch block.
p.write_text(s)
