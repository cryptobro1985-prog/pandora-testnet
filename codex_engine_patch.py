from pathlib import Path
p=Path("/app/codex_engine/app.py")
s=p.read_text()
old="def pg():return psycopg.connect(os.environ['DATABASE_URL'],autocommit=True,row_factory=dict_row,connect_timeout=5)"
new="""def pg():
 db=psycopg.connect(os.environ['DATABASE_URL'],autocommit=False,row_factory=dict_row,connect_timeout=5)
 # Neon pooled connections use transaction pooling, so a session-level SET search_path
 # can disappear between statements. Keep the schema selection inside the same
 # transaction as every use of this connection.
 db.execute('SET LOCAL search_path TO codex_million')
 return db"""
if old not in s: raise SystemExit("Codex pg() signature changed")
p.write_text(s.replace(old,new))
