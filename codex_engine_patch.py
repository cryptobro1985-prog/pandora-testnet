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
EXPERIMENT="CODEX_SHORT10_30_180_300_20261103"
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
s=s.replace("if side not in (-1,1):continue","if side!=-1:continue")

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
