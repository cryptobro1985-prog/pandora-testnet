from pathlib import Path
p=Path("/app/codex_engine/app.py")
s=p.read_text()
old="def pg():return psycopg.connect(os.environ['DATABASE_URL'],autocommit=True,row_factory=dict_row,connect_timeout=5)"
new="def pg():\n db=psycopg.connect(os.environ['DATABASE_URL'],autocommit=True,row_factory=dict_row,connect_timeout=5)\n db.execute('SET search_path TO codex_million')\n return db"
if old not in s: raise SystemExit("Codex pg() signature changed")
p.write_text(s.replace(old,new))
