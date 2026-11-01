"""Static and UI regression for the isolated Pandora Beda deployment."""
from pathlib import Path
import importlib.util,py_compile,unittest
from pandora_beda_launcher import BEDA,BedaBridge
from pandora_monitor import render

ROOT=Path(__file__).resolve().parents[1]
VENDOR=ROOT/"pandora_beda"

class BedaEmbeddedTests(unittest.TestCase):
 def test_original_executed_flow_vendor_complete_and_compilable(self):
  for name in ("app.py","pandora_flow_strategy.py","pandora_runtime.py",
               "pandora_experiment.py","pandora_scanner.py","bybit_market_stream.py",
               "scripts/reset_paper_experiment.py"):
   target=VENDOR/name
   self.assertTrue(target.is_file(),name)
   compile(target.read_text(),str(target),"exec")
  self.assertGreater((VENDOR/"pandora_flow_strategy.py").stat().st_size,30000)
 def test_isolated_schema_and_unchanged_paper_capital(self):
  spec=importlib.util.spec_from_file_location("beda_config_only",VENDOR/"pandora_experiment.py")
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  self.assertEqual(module.EXPERIMENT_ID,"pandora_beda")
  self.assertEqual(module.SCHEMA_NAME,"pandora_beda")
  self.assertEqual(module.STARTING_EQUITY,500.0)
 def test_monitor_shows_independent_account_and_both_histories(self):
  payload={
   "pandora":{"starting_equity":400,"total_equity":400,"realized_pnl":0,
      "unrealized_pnl":0,"open_positions":[],"closed_trades":[]},
   "beda":{"status":"PAPER_RUNNING","starting_equity":500,
      "realized_pnl":0,"unrealized_pnl":0,"positions":[],"trades":[]},
   "health":{"healthy":True,"risk_ready":True},"snapshot_at":"2026-11-02T00:00:00Z"}
  html=render(payload)
  for marker in ("Pandora Беда","compare-beda-pnl","compare-v3-pnl",
                 "beda-positions","beda-trades","data-tab=\"beda\""):
   self.assertIn(marker,html)
 def test_beda_init_subprocess_on_isolated_ci_postgres(self):
  """Exercise the same reset command used on Render, not just compilation."""
  import os,subprocess,sys
  from psycopg.rows import dict_row
  bound=os.getenv("PANDORA_TEST_DATABASE_URL_FILE")
  if not bound or not Path(bound).is_file():
   self.skipTest("isolated CI PostgreSQL unavailable")
  dsn=Path(bound).read_text().strip()
  self.assertEqual(dsn,os.getenv("DATABASE_URL"))
  env=os.environ.copy()
  env["DATABASE_URL"]=dsn
  proc=subprocess.run([sys.executable,"scripts/reset_paper_experiment.py"],
    cwd=VENDOR,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
    text=True,timeout=30)
  self.assertEqual(proc.returncode,0,"Beda initialization failed in isolated CI database")
  import psycopg
  with psycopg.connect(dsn,autocommit=True,row_factory=dict_row) as db:
   row=db.execute("SELECT equity,realized_pnl FROM pandora_beda.pandora_win_account_state WHERE id=1").fetchone()
   self.assertEqual(row["equity"],500.0)
   self.assertEqual(row["realized_pnl"],0.0)
 def test_bridge_does_not_start_trading_when_imported(self):
  bridge=BedaBridge()
  self.assertIsNone(bridge.process)
  self.assertFalse(bridge.snapshot()["online"])
  self.assertNotEqual(bridge.root,ROOT)

if __name__=="__main__":unittest.main()
