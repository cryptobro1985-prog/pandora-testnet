"""Run only against the explicitly configured isolated CI database."""
import copy
import os
from pathlib import Path
import time
import unittest
import uuid
from unittest.mock import patch
import psycopg
from psycopg.rows import dict_row
import app
from engine_store import EngineStore

TEST_FILE=os.getenv("PANDORA_TEST_DATABASE_URL_FILE")


@unittest.skipUnless(TEST_FILE,"isolated test database is not configured")
class ReleaseStorageTests(unittest.TestCase):
    def setUp(self):
        self.saved=copy.deepcopy(app.S)
        url=Path(TEST_FILE).read_text().strip()
        self.connect=lambda:psycopg.connect(url,autocommit=True,row_factory=dict_row)
        self.store=EngineStore(self.connect);self.assertTrue(self.store.claim())
        self.pg_patch=patch.object(app,"pg",self.connect);self.pg_patch.start()
        self.store_patch=patch.object(app,"STORE",self.store);self.store_patch.start()
        self.symbol="TEST_"+uuid.uuid4().hex[:10]
        app.S.update(engine_active=True,mode="PAPER_ONLY",orders_enabled=False,equity=100.,
                     realized_pnl=0.,positions={},pump_positions={},whale_positions={},whale_v2_positions={},
                     hype_swing_position=None,_entry_reservations={},_emergency_until=0,
                     _prices={self.symbol:100.,"HYPE":100.},_last_poll_epoch=time.time(),last_checkpoint=app.now(),
                     trades=0,pump_trades=0,whale_v2_trades=0,hype_swing_trades=0)
        with self.connect() as db:
            db.execute("update account_state set equity=100,realized_pnl=0 where id=1")
            db.execute("delete from hype_swing_positions")

    def tearDown(self):
        with self.connect() as db:
            db.execute("delete from whale_liq_v2_positions where symbol=%s",(self.symbol,))
            db.execute("delete from pump_positions where symbol=%s",(self.symbol,))
            db.execute("delete from hype_swing_positions")
        self.store.release();self.pg_patch.stop();self.store_patch.stop()
        app.S.clear();app.S.update(self.saved)

    def test_wl2_close_credits_shared_cash_exactly_once_and_releases_reservation(self):
        self.assertTrue(app.whale_v2_open(self.symbol,-1,100,99,{}))
        self.assertEqual(app.S["whale_v2_positions"][self.symbol]["margin"],10)
        self.assertFalse(app.S.get("_entry_reservations"))
        result=app.whale_v2_close(self.symbol,99,"test")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(app.S["equity"],100+result["pnl"])
        self.assertIsNone(app.whale_v2_close(self.symbol,99,"test"))
        with self.connect() as db:
            balance=db.execute("select equity from account_state where id=1").fetchone()["equity"]
            count=db.execute("select count(*) as n from trade_history where strategy='whale_liquidation_v2' and symbol=%s",(self.symbol,)).fetchone()["n"]
        self.assertAlmostEqual(balance,app.S["equity"]);self.assertEqual(count,1)

    def test_h1_failed_position_write_does_not_consume_signal(self):
        candle=int(time.time()*1000)
        analysis={"ready":True,"entry_side":1,"signal_candle_time":candle,"pivot_type":"LOCAL_LOW"}
        name="reject_hype_"+uuid.uuid4().hex[:10]
        with self.connect() as db:
            db.execute("create function "+name+"() returns trigger language plpgsql as $$ begin raise exception 'isolated insertion failure'; end $$")
            db.execute("create trigger "+name+" before insert on hype_swing_positions for each row execute function "+name+"()")
        try:
            with self.assertRaises(psycopg.Error):app.hype_swing_open(1,100,analysis)
            with self.connect() as db:
                exists=db.execute("select 1 from hype_swing_signal_journal where id=%s",(f"HYPE_H1:OPEN:{candle}:1",)).fetchone()
            self.assertIsNone(exists);self.assertFalse(app.S.get("_entry_reservations"))
        finally:
            with self.connect() as db:
                db.execute("drop trigger "+name+" on hype_swing_positions");db.execute("drop function "+name+"()")
        self.assertTrue(app.hype_swing_open(1,100,analysis))
        self.assertEqual(app.S["hype_swing_position"]["margin"],10)
        result=app.hype_swing_close(101,"test")
        self.assertAlmostEqual(app.S["equity"],100+result["pnl"])

    def test_exclusion_removes_only_selected_paper_trade_and_is_idempotent(self):
        self.assertTrue(app.pump_open(self.symbol,1,100,99,{}))
        opened=app.S["pump_positions"][self.symbol]["opened"]
        app.S["_prices"][self.symbol]=99
        request={"symbol":self.symbol,"opened":opened,"id":"test-exclude-"+uuid.uuid4().hex}
        self.assertTrue(app.exclude_authorized_pump_position(request))
        self.assertNotIn(self.symbol,app.S["pump_positions"])
        self.assertAlmostEqual(app.S["equity"],100)
        self.assertTrue(app.exclude_authorized_pump_position(request))
        self.assertAlmostEqual(app.S["equity"],100)
        with self.connect() as db:
            rows=db.execute("select count(*) as n from trade_history where symbol=%s and opened=%s",(self.symbol,opened)).fetchone()["n"]
        self.assertEqual(rows,0)

    def test_batch_exclusion_freezes_identities_and_keeps_later_trades(self):
        self.assertTrue(app.pump_open(self.symbol,1,100,99,{}))
        request={'id':'test-batch-'+uuid.uuid4().hex,'type':'EXCLUDE_OPEN_PUMP_LONGS'}
        self.assertTrue(app.exclude_authorized_pump_longs(request))
        self.assertNotIn(self.symbol,app.S['pump_positions'])
        self.assertTrue(app.pump_open(self.symbol,1,100,99,{}))
        later=app.S['pump_positions'][self.symbol]['opened']
        self.assertTrue(app.exclude_authorized_pump_longs(request))
        self.assertEqual(app.S['pump_positions'][self.symbol]['opened'],later)
