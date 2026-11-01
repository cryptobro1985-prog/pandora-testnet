"""A clean Pandora Win account is isolated and survives later restarts."""
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


@unittest.skipUnless(os.getenv('PANDORA_TEST_DATABASE_URL_FILE'), 'isolated PostgreSQL required')
class BootstrapSafetyTests(unittest.TestCase):
    def test_first_start_is_clean_and_repeat_start_preserves_only_new_account(self):
        url=Path(os.environ['PANDORA_TEST_DATABASE_URL_FILE']).read_text().strip()
        schema='bootstrap_'+uuid.uuid4().hex
        saved=copy.deepcopy(app.S)
        saved_runtime=app.WIN
        with psycopg.connect(url,autocommit=True) as db:
            db.execute(sql.SQL('create schema {}').format(sql.Identifier(schema)))
        connect=lambda:psycopg.connect(url,autocommit=True,row_factory=dict_row,
                                      options='-c search_path='+schema)
        try:
            with patch.object(app,'pg',connect),patch.object(app,'STORE',app.EngineStore(connect)):
                with connect() as db:
                    db.execute('create table unrelated_account_state(id integer primary key,equity double precision,realized_pnl double precision)')
                    db.execute('insert into unrelated_account_state values(1,900000,899500)')
                    db.execute('create table unrelated_trade_history(symbol text,pnl double precision)')
                    db.execute("insert into unrelated_trade_history values('BTC',899500)")
                app.pinit()
                with connect() as db:
                    account=db.execute('select equity,realized_pnl from pandora_win_account_state where id=1').fetchone()
                    self.assertEqual((account['equity'],account['realized_pnl']),(500,0))
                    self.assertEqual(db.execute('select count(*) n from pandora_win_trade_history').fetchone()['n'],0)
                    self.assertEqual(db.execute('select count(*) n from pandora_win_positions').fetchone()['n'],0)
                    self.assertEqual(db.execute('select count(*) n from pandora_win_pyramid_adds').fetchone()['n'],0)
                    db.execute('update pandora_win_account_state set equity=750,realized_pnl=250 where id=1')
                    db.execute("insert into pandora_win_trade_history(symbol,pnl) values('BTC',250)")
                    db.execute("insert into pandora_win_positions(symbol,side,entry,notional,margin,leverage,opened,opened_epoch,features) "
                               "values('ETH',1,100,1000,100,10,'fixture',1000,'{}')")
                    db.execute("insert into pandora_win_audit_journal(recorded_at,event_id,kind,payload) "
                               "values('fixture','preserve-me','pandora_CLOSE_LONG','{}')")
                    db.execute("insert into pandora_win_candle_checkpoints(symbol,interval,candles) values('BTC','1h','[]')")
                app.pinit();app.pinit()
                with connect() as db:
                    account=db.execute('select equity,realized_pnl from pandora_win_account_state where id=1').fetchone()
                    self.assertEqual((account['equity'],account['realized_pnl']),(750,250))
                    self.assertEqual(db.execute('select count(*) n from pandora_win_trade_history').fetchone()['n'],1)
                    self.assertEqual(db.execute('select count(*) n from pandora_win_positions').fetchone()['n'],1)
                    self.assertEqual(db.execute("select count(*) n from pandora_win_audit_journal where event_id='preserve-me'").fetchone()['n'],1)
                    self.assertEqual(db.execute('select count(*) n from pandora_win_candle_checkpoints').fetchone()['n'],1)
                    self.assertEqual(db.execute('select equity from unrelated_account_state where id=1').fetchone()['equity'],900000)
                self.assertEqual(app.S['pandora_equity'],750)
                self.assertEqual(set(app.S['pandora_win_positions']),{'ETH'})
                self.assertEqual({r['account'] for r in app.pandora_token_totals()},{'pandora_win'})
        finally:
            app.S.clear();app.S.update(saved);app.WIN=saved_runtime
            with psycopg.connect(url,autocommit=True) as db:
                db.execute(sql.SQL('drop schema {} cascade').format(sql.Identifier(schema)))


class RotationReadinessTests(unittest.TestCase):
    def setUp(self):self.saved=copy.deepcopy(app.S)
    def tearDown(self):app.S.clear();app.S.update(self.saved)

    def test_rotated_out_positions_and_watches_remain_subscribed(self):
        app.S['bybit_discovery']={'selected_symbols':['NEW']}
        app.S['pandora_win_positions']={'HELD':{}}
        app.S['pandora_watch']={'WATCHED':{}}
        self.assertEqual(set(app.pandora_trade_symbols()),{'NEW','HELD','WATCHED'})
        self.assertTrue({'NEW','HELD','WATCHED'}.issubset(app.pandora_runtime_symbols()))

    def test_no_selected_market_cannot_report_risk_ready(self):
        app.S.update(engine_active=True,last_checkpoint=app.now(),bybit_discovery={},
                     pandora_win_positions={},pandora_watch={})
        self.assertFalse(app.health_state()['risk_ready'])
