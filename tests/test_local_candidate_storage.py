"""Real PostgreSQL entry rollback checks, isolated in a disposable schema."""
import copy
import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import app
from engine_store import EngineStore
from tests.test_local_candidate_selection import evidence


@unittest.skipUnless(os.getenv('PANDORA_TEST_DATABASE_URL_FILE'),'isolated PostgreSQL URL file required')
class LocalEntryStorageTests(unittest.TestCase):
    def setUp(self):
        self.url=Path(os.environ['PANDORA_TEST_DATABASE_URL_FILE']).read_text().strip()
        self.schema='local_selection_test_'+uuid.uuid4().hex
        with psycopg.connect(self.url,autocommit=True) as db:
            db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.saved=copy.deepcopy(app.S)
        self.connect=lambda:psycopg.connect(self.url,autocommit=True,row_factory=dict_row,options='-c search_path='+self.schema)
        self.pg_patch=patch.object(app,'pg',self.connect);self.pg_patch.start()
        self.store=EngineStore(self.connect)
        self.store_patch=patch.object(app,'STORE',self.store);self.store_patch.start()
        app.pinit();self.assertTrue(self.store.claim())
        app.S.update(engine_active=True,mode='PAPER_ONLY',orders_enabled=False,
                     local_v12_positions={},local_experiment_watch={},local_h1_direction={},
                     local_experiment_equity=500.,_prices={'HYPE':100.},
                     _last_poll_epoch=app.time.time(),last_checkpoint=app.now())

    def tearDown(self):
        self.store.release();self.store_patch.stop();self.pg_patch.stop()
        app.S.clear();app.S.update(self.saved)
        with psycopg.connect(self.url,autocommit=True) as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    def test_conflicting_position_does_not_consume_signal_or_mutate_memory(self):
        with self.connect() as db:
            db.execute("""INSERT INTO local_v12_positions
                (symbol,side,entry,notional,margin,leverage,opened,opened_epoch,signal_candle_time,features)
                VALUES ('HYPE',1,100,250,10,25,'existing',0,1,'{}')""")
        a,m,f=evidence(stamp=app.time.time())
        with patch.object(app.MARKET_OBS,'flow_context',return_value=f),patch.object(app,'log_learning_decision'):
            self.assertFalse(app.local_experiment_open('HYPE',1,a,m15=m))
            self.assertNotIn('HYPE',app.S['local_v12_positions'])
            with self.connect() as db:
                self.assertEqual(db.execute("SELECT count(*) AS n FROM local_v12_signal_journal WHERE action='OPEN'").fetchone()['n'],0)
                db.execute("DELETE FROM local_v12_positions WHERE symbol='HYPE'")
            self.assertTrue(app.local_experiment_open('HYPE',1,a,m15=m))
            self.assertFalse(app.local_experiment_open('HYPE',1,a,m15=m))
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) AS n FROM local_v12_positions").fetchone()['n'],1)
            features=db.execute("SELECT features FROM local_v12_positions WHERE symbol='HYPE'").fetchone()['features']
            self.assertTrue(features['candidate_selection']['eligible'])

    def test_next_entry_compounds_current_equity_without_resizing_open_position(self):
        a,m,f=evidence(stamp=app.time.time())
        with patch.object(app.MARKET_OBS,'flow_context',return_value=f),patch.object(app,'log_learning_decision'):
            self.assertTrue(app.local_experiment_open('HYPE',1,a,m15=m))
            first=copy.deepcopy(app.S['local_v12_positions']['HYPE'])
            self.assertEqual(first['margin'],100.)
            app.S['_prices'].update(HYPE=101.,NEAR=100.)
            expected_equity=500.+app.paper_pnl(first['notional'],100.,101.,1,app.FEE)
            self.assertTrue(app.local_experiment_open('NEAR',1,a,m15=m))
        second=app.S['local_v12_positions']['NEAR']
        self.assertAlmostEqual(second['margin'],expected_equity*.2)
        self.assertGreater(second['margin'],first['margin'])
        self.assertEqual(app.S['local_v12_positions']['HYPE']['margin'],first['margin'])
        self.assertEqual(app.S['local_v12_positions']['HYPE']['notional'],first['notional'])
        self.assertLessEqual(first['margin']+second['margin'],expected_equity)


if __name__=='__main__':
    unittest.main()
