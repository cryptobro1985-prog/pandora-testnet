"""Optional integration tests. Point ONLY to an isolated database branch."""
import contextlib
import datetime
import os
from pathlib import Path
import unittest
import uuid

import psycopg
from psycopg.rows import dict_row
from engine_store import EngineStore,LeaseLost
from risk import evaluate_exit

TEST_FILE=os.environ.get("PANDORA_TEST_DATABASE_URL_FILE")


@unittest.skipUnless(TEST_FILE,"isolated test database is not configured")
class StoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url=Path(TEST_FILE).read_text().strip()
        cls.connect=staticmethod(lambda:psycopg.connect(cls.url,autocommit=True,row_factory=dict_row,connect_timeout=10))
        EngineStore(cls.connect).migrate()

    def setUp(self):
        self.store=EngineStore(self.connect)
        self.assertTrue(self.store.claim())
        self.symbol="TEST_"+uuid.uuid4().hex[:12]

    def tearDown(self):
        self.store.release()

    def pos(self):
        return {"entry":.00039,"side":-1,"notional":250.,"opened":"2026-10-23T00:00:00+00:00",
                "t":1792713600.,"headline":"isolated fixture","locked":False,"stop":None,
                "leverage":10.,"margin":25.,"event_id":None,"peak":.00039,"history":[]}

    def test_migration_is_repeatable(self):
        self.store.migrate();self.store.migrate()

    def test_checkpoint_roundtrip_including_local_extreme_history(self):
        p=self.pos();self.assertTrue(self.store.save(self.symbol,p,create=True))
        p,_=evaluate_exit(p,.00038,"checkpoint")
        self.assertTrue(self.store.save(self.symbol,p))
        _,rows=EngineStore(self.connect).load()
        restored=rows[self.symbol]
        for key in ("peak","history","last_price","last_evaluated_at","last_exit_check","stop"):
            self.assertEqual(restored.get(key),p.get(key))

    def test_legacy_minimum_is_recovered_and_local_extreme_exit_still_works(self):
        p=self.pos();self.store.save(self.symbol,p,create=True)
        with self.connect() as c:
            c.execute("UPDATE open_positions SET risk_state='{}'::jsonb WHERE symbol=%s",(self.symbol,))
            c.execute("INSERT INTO market_context_snapshots(ts,symbol,price,context) VALUES(%s,%s,%s,'{}'::jsonb)",("2026-10-23T22:52:35+00:00",self.symbol,.00038))
        _,rows=self.store.load()
        restored=rows[self.symbol]
        self.assertEqual(restored["peak"],.00038)
        why=None
        for i,price in enumerate((.000381,.000382,.000384,.000388),1):
            restored,why=evaluate_exit(restored,price,"resume-"+str(i))
        self.assertEqual(why,"local_extreme_weakening")

    def test_close_retry_cannot_double_credit_or_resurrect(self):
        p=self.pos();self.store.save(self.symbol,p,create=True)
        with self.connect() as c:before=c.execute("SELECT equity FROM account_state WHERE id=1").fetchone()["equity"]
        result=self.store.close(self.symbol,p,.000388,"fixture_close")
        self.assertIsNotNone(result)
        self.assertIsNone(self.store.close(self.symbol,p,.000388,"fixture_close"))
        self.assertFalse(self.store.save(self.symbol,p))
        with self.connect() as c:
            after=c.execute("SELECT equity FROM account_state WHERE id=1").fetchone()["equity"]
            count=c.execute("SELECT count(*) AS n FROM trade_history WHERE symbol=%s",(self.symbol,)).fetchone()["n"]
        self.assertAlmostEqual(after,before+result["pnl"]);self.assertEqual(count,1)

    def test_other_owner_is_blocked_and_stale_owner_is_fenced(self):
        other=EngineStore(self.connect);self.assertFalse(other.claim())
        with self.connect() as c:
            c.execute("UPDATE engine_lease SET expires_at=clock_timestamp()-interval '1 second' WHERE name='paper'")
        self.assertTrue(other.claim())
        try:
            with self.assertRaises(LeaseLost):self.store.save(self.symbol,self.pos(),create=True)
        finally:other.release()

    def test_transaction_failure_rolls_back_position_deletion(self):
        p=self.pos();self.store.save(self.symbol,p,create=True)
        def fail(*args):raise RuntimeError("injected journal failure")
        self.store._journal=fail
        with self.assertRaises(RuntimeError):self.store.close(self.symbol,p,.000388,"fixture_close")
        with self.connect() as c:
            row=c.execute("SELECT symbol FROM open_positions WHERE symbol=%s",(self.symbol,)).fetchone()
            count=c.execute("SELECT count(*) AS n FROM trade_history WHERE symbol=%s",(self.symbol,)).fetchone()["n"]
        self.assertIsNotNone(row);self.assertEqual(count,0)


if __name__=="__main__":unittest.main()
