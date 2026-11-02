from pathlib import Path

# Integration-only patch for the frozen Codex engine.
# Do not change scanner, locals, flow, entry/exit, risk, re-entry or sizing logic.
p=Path("/app/codex_engine/app.py")
s=p.read_text()

old="def pg():return psycopg.connect(os.environ['DATABASE_URL'],autocommit=True,row_factory=dict_row,connect_timeout=5)"
new="""def pg():
 db=psycopg.connect(os.environ['DATABASE_URL'],autocommit=False,row_factory=dict_row,connect_timeout=5)
 db.execute('SET LOCAL search_path TO codex_million')
 return db"""
if old not in s:
 raise SystemExit("Codex pg() signature changed")

p.write_text(s.replace(old,new))
