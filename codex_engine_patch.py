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
for name in ("pandora_scanner.py","pandora_fixed_five_reset.py"):
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
(p.parent/"pandora_fixed_five_reset.py").write_text(reset)
p.write_text(s)
