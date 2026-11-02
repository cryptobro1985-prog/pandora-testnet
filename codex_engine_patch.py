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
       S['pandora_watch']={}
       S['pandora_win_h1_direction']={}
       S['_pandora_analysis']={}
      if WIN is not None:
       WIN.scanner.restore({})
       WIN.max_equity=500.
     restore_state()"""
if s.count(old)!=1:raise SystemExit("Codex coordinator signature changed")
s=s.replace(old,new)
for name in ("pandora_scanner.py","pandora_fixed_five_reset.py"):
 shutil.copyfile(root/name,p.parent/name)
p.write_text(s)
