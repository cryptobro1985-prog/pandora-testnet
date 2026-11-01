"""End-to-end isolated Postgres test for irreversible-once PAPER migration.

Uses private disposable schema in CI's isolated database. Production untouched.
"""
import datetime,os,unittest,uuid
from pathlib import Path
from unittest.mock import patch

@unittest.skipUnless(os.getenv("PANDORA_TEST_DATABASE_URL_FILE"),"requires isolated PostgreSQL")
class PumpResetTest(unittest.TestCase):
 def test_legacy_archived_new_account_400_and_restart_idempotent(self):
  import psycopg
  from psycopg.rows import dict_row
  import app
  from engine_store import EngineStore
  from pandora_flow_v2_reset import reset_once
  url=Path(os.environ["PANDORA_TEST_DATABASE_URL_FILE"]).read_text().strip()
  self.assertEqual(url,os.environ.get("DATABASE_URL"))
  schema="pump_reset_"+uuid.uuid4().hex[:16]
  def admin():return psycopg.connect(url,autocommit=True,row_factory=dict_row)
  with admin() as db:db.execute("CREATE SCHEMA "+schema)
  def connect():return psycopg.connect(url,autocommit=True,row_factory=dict_row,
     options="-c search_path="+schema+",public")
  try:
   with connect() as db:
    for query in app.SCHEMA:db.execute(query)
    db.execute("CREATE TABLE pandora_win_token_state(symbol text primary key,payload jsonb not null)")
    db.execute("CREATE TABLE pandora_win_runtime_state(name text primary key,payload jsonb not null)")
    db.execute("CREATE TABLE pandora_win_pyramid_adds(id bigserial primary key,payload jsonb)")
    db.execute("INSERT INTO pandora_win_account_state VALUES(1,220,-180,'old','old')")
    db.execute("INSERT INTO pandora_win_trade_history(symbol,pnl) VALUES('ESPORTS',-62)")
    db.execute("INSERT INTO pandora_win_positions(symbol,side,entry,notional,margin,leverage,opened,opened_epoch) VALUES('INIT',1,1,1000,40,25,'old',1000)")
   store=EngineStore(connect)
   store.migrate()
   self.assertTrue(store.claim())
   def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
   with patch.dict(os.environ,{"PANDORA_PUMP_V3":"1"}):
    self.assertTrue(reset_once(connect,store,utc))
    with connect() as db:
     account=db.execute("SELECT equity,realized_pnl FROM pandora_win_account_state WHERE id=1").fetchone()
     self.assertEqual(account["equity"],400)
     self.assertEqual(account["realized_pnl"],0)
     self.assertEqual(db.execute("SELECT count(*) n FROM pandora_win_positions").fetchone()["n"],0)
     self.assertEqual(db.execute("SELECT count(*) n FROM pandora_win_trade_history").fetchone()["n"],0)
     self.assertEqual(db.execute("SELECT count(*) n FROM pandora_win_legacy_pump_v3_20261101_positions").fetchone()["n"],1)
     self.assertEqual(db.execute("SELECT count(*) n FROM pandora_win_legacy_pump_v3_20261101_trade_history").fetchone()["n"],1)
     self.assertEqual(db.execute("SELECT starting_equity FROM pandora_win_experiment_migrations WHERE experiment='PANDORA_PUMP_STRUCTURE_V3_400'").fetchone()["starting_equity"],400)
     db.execute("INSERT INTO pandora_win_trade_history(symbol,pnl) VALUES('INIT',4)")
    self.assertFalse(reset_once(connect,store,utc))
    with connect() as db:self.assertEqual(db.execute("SELECT count(*) n FROM pandora_win_trade_history").fetchone()["n"],1)
  finally:
   try:store.release()
   except Exception:pass
   with admin() as db:db.execute("DROP SCHEMA "+schema+" CASCADE")
if __name__=="__main__":unittest.main()
