"""Fresh installation and repeat startup preserve every PAPER ledger."""
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
    def test_fresh_boot_and_repeated_boot_preserve_all_accounts_and_history(self):
        url = Path(os.environ['PANDORA_TEST_DATABASE_URL_FILE']).read_text().strip()
        schema = 'bootstrap_' + uuid.uuid4().hex
        saved = copy.deepcopy(app.S)
        engines = app.S11, app.S13, app.S14
        with psycopg.connect(url, autocommit=True) as db:
            db.execute(sql.SQL('create schema {}').format(sql.Identifier(schema)))
        connect = lambda: psycopg.connect(url, autocommit=True, row_factory=dict_row,
                                         options='-c search_path=' + schema)
        try:
            with patch.object(app, 'pg', connect), patch.object(app, 'STORE', app.EngineStore(connect)):
                app.pinit()  # no pre-existing archive or reset marker
                with connect() as db:
                    for prefix in ('local_v12', 'strategy11', 'strategy13', 'strategy14'):
                        db.execute(sql.SQL('update {} set equity=750,realized_pnl=250 where id=1')
                                   .format(sql.Identifier(prefix + '_account_state')))
                        db.execute(sql.SQL("insert into {} (symbol,pnl) values ('BTC',250)")
                                   .format(sql.Identifier(prefix + '_trade_history')))
                    db.execute("insert into audit_journal(recorded_at,event_id,kind,payload) "
                               "values ('fixture','preserve-me','local_experiment_trade_closed','{}')")
                    db.execute("insert into local_candle_checkpoints(symbol,interval,candles) "
                               "values ('BTC','1h','[]')")
                app.pinit()
                app.pinit()
                with connect() as db:
                    for prefix in ('local_v12', 'strategy11', 'strategy13', 'strategy14'):
                        row = db.execute(sql.SQL('select equity,realized_pnl from {} where id=1')
                                         .format(sql.Identifier(prefix + '_account_state'))).fetchone()
                        self.assertEqual((row['equity'], row['realized_pnl']), (750, 250))
                        self.assertEqual(db.execute(sql.SQL('select count(*) n from {}')
                                         .format(sql.Identifier(prefix + '_trade_history'))).fetchone()['n'], 1)
                    self.assertEqual(db.execute("select count(*) n from audit_journal where event_id='preserve-me'")
                                     .fetchone()['n'], 1)
                    self.assertEqual(db.execute('select count(*) n from local_candle_checkpoints').fetchone()['n'], 1)
                self.assertEqual(app.S['local_experiment_equity'], 750)
        finally:
            app.S.clear()
            app.S.update(saved)
            app.S11, app.S13, app.S14 = engines
            with psycopg.connect(url, autocommit=True) as db:
                db.execute(sql.SQL('drop schema {} cascade').format(sql.Identifier(schema)))


class RotationReadinessTests(unittest.TestCase):
    def setUp(self):
        self.saved = copy.deepcopy(app.S)

    def tearDown(self):
        app.S.clear()
        app.S.update(self.saved)

    def test_rotated_out_positions_and_watches_remain_subscribed(self):
        app.S['bybit_discovery'] = {'selected_symbols': ['NEW']}
        app.S['local_v12_positions'] = {'HELD': {}}
        app.S['local_experiment_watch'] = {'WATCHED': {}}
        self.assertEqual(set(app.strategy1_trade_symbols()), {'NEW', 'HELD', 'WATCHED'})
        self.assertTrue({'NEW', 'HELD', 'WATCHED'}.issubset(app.strategy1_runtime_symbols()))

    def test_no_selected_market_cannot_report_risk_ready(self):
        app.S.update(engine_active=True, last_checkpoint=app.now(), bybit_discovery={},
                     local_v12_positions={}, local_experiment_watch={})
        self.assertFalse(app.health_state()['risk_ready'])
