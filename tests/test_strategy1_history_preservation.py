"""Read-only full-history reporting, independent of dashboard page limits."""
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
from strategy1_monitor import render,render_history


@unittest.skipUnless(os.getenv('PANDORA_TEST_DATABASE_URL_FILE'),'isolated PostgreSQL required')
class HistoryPreservationTests(unittest.TestCase):
    def setUp(self):
        self.url=Path(os.environ['PANDORA_TEST_DATABASE_URL_FILE']).read_text().strip()
        self.schema='history_'+uuid.uuid4().hex
        with psycopg.connect(self.url,autocommit=True) as db:
            db.execute(sql.SQL('create schema {}').format(sql.Identifier(self.schema)))
        self.saved=copy.deepcopy(app.S)
        self.connect=lambda:psycopg.connect(self.url,autocommit=True,row_factory=dict_row,options='-c search_path='+self.schema)
        self.pg_patch=patch.object(app,'pg',self.connect);self.pg_patch.start()
        self.store_patch=patch.object(app,'STORE',app.EngineStore(self.connect));self.store_patch.start()
        app.pinit()
        with self.connect() as db:
            db.execute("create table local_s1_trade_history (like local_v12_trade_history including all)")
            with db.cursor() as cursor:
                cursor.executemany("""insert into local_v12_trade_history
                    (opened,closed,symbol,side,entry,exit,pnl,reason,margin,notional,leverage,features)
                    values ('2026-10-01T00:00:00Z','2026-10-01T01:00:00Z','BTC',1,100,101,%s,'fixture',10,250,25,%s::jsonb)""",
                    [(-50,'{"excluded_from_strategy_stats":true}')]+[(1,'{}')]*300)
            db.execute("""insert into local_s1_trade_history
                (opened,closed,symbol,side,entry,exit,pnl,reason,margin,notional,leverage,features)
                values ('legacy','legacy','BTC',1,100,101,7,'legacy',10,250,25,'{}')""")
            for kind in ('local_experiment_trade_opened','local_experiment_trade_closed'):
                db.execute("insert into audit_journal(recorded_at,kind,payload) values('2026-10-01T00:00:00Z',%s,%s::jsonb)",(kind,'{"symbol":"BTC"}'))

    def tearDown(self):
        self.store_patch.stop();self.pg_patch.stop();app.S.clear();app.S.update(self.saved)
        with psycopg.connect(self.url,autocommit=True) as db:
            db.execute(sql.SQL('drop schema {} cascade').format(sql.Identifier(self.schema)))

    def test_all_time_pnl_keeps_loss_outside_latest_300_and_legacy_separate(self):
        totals=app.strategy1_token_totals()
        canonical=next(r for r in totals if r['account']=='strategy1')
        legacy=next(r for r in totals if r['account']=='legacy_s1')
        self.assertEqual(canonical['closed_trades'],301)
        self.assertEqual(canonical['realized_pnl'],250)
        self.assertEqual(legacy['realized_pnl'],7)
        self.assertEqual(len(app.local_v10_history(300)),300)
        page=render({'local_experiment_symbols':['BTC'], 'strategy1_primary':{
            'token_totals':totals,'open_positions':[],'closed_trades':[]}})
        self.assertIn('250.0000',page)
        self.assertIn('legacy_s1',page)
        self.assertIn('7.0000',page)
        self.assertIn('/strategy1/history',page)

    def test_pagination_reaches_every_closed_trade_without_mutation(self):
        ids=[];before=None
        while True:
            page=app.strategy1_history_page(before_id=before,limit=100)
            ids.extend(r['id'] for r in page['trades'])
            before=page['next_before_id']
            if before is None:break
        self.assertEqual(len(ids),301)
        self.assertEqual(len(set(ids)),301)
        self.assertEqual(ids,sorted(ids,reverse=True))
        self.assertEqual(app.strategy1_history_page(before_id=2)['trades'][0]['pnl'],-50)
        with self.connect() as db:
            row=db.execute('select count(*) n,sum(pnl) pnl from local_v12_trade_history').fetchone()
            self.assertEqual((row['n'],row['pnl']),(301,250))
            self.assertEqual(db.execute('select equity from local_v12_account_state where id=1').fetchone()['equity'],500)

    def test_legacy_reset_cannot_erase_history_or_account_state(self):
        app.S['local_experiment_equity']=750
        app.S['local_experiment_realized_pnl']=250
        self.assertFalse(app.apply_local4_user_reset())
        self.assertEqual(app.S['local_experiment_equity'],750)
        self.assertEqual(app.S['local_experiment_realized_pnl'],250)
        with self.connect() as db:
            row=db.execute('select count(*) n,sum(pnl) pnl from local_v12_trade_history').fetchone()
            self.assertEqual((row['n'],row['pnl']),(301,250))

    def test_event_archive_retains_open_and_close_and_filters_are_bound(self):
        self.assertEqual({r['kind'] for r in app.strategy1_event_page()['events']},
            {'local_experiment_trade_opened','local_experiment_trade_closed'})
        self.assertEqual(app.strategy1_history_page(symbol="BTC' OR TRUE --")['trades'],[])
        with self.assertRaises(ValueError):app.strategy1_history_page(account='local_v12_trade_history;drop table')
        page=app.strategy1_history_page(limit=1)
        html=render_history(page)
        self.assertIn('Более ранние сделки',html)
        self.assertIn('before=',html)
        self.assertIn('strategy1',html)


class FailureViewTests(unittest.TestCase):
    def test_missing_aggregates_are_not_reported_as_zero(self):
        page=render({'strategy1_primary':{},'local_experiment_symbols':['BTC']})
        self.assertIn('нулевой PnL не подставляется',page)
        self.assertNotIn('377.36',page)
