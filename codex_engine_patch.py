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
new_pool="with LOCK:pool=tuple(((S.get('bybit_discovery') or {}).get('candidate_symbols') or ())[:5])"
if old_pool not in s: raise SystemExit("Codex runtime-symbol pool signature changed")
s=s.replace(old_pool,new_pool)

# Faster read-only diagnostics while the active five are warming.
s=s.replace("if time.time()-last_entry_diagnostics>=30:","if time.time()-last_entry_diagnostics>=5:")

p.write_text(s)
