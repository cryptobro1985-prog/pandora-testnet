"""Fast application-level risk regressions on an isolated PostgreSQL schema."""
import copy
import datetime
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

import app
from accounting import paper_pnl
from pandora_risk import plan_entry


@unittest.skipUnless(os.getenv('PANDORA_TEST_DATABASE_URL_FILE'),'isolated PostgreSQL required')
class ApplicationRiskAuditTests(unittest.TestCase):
    def setUp(self):
        self.url=Path(os.environ['PANDORA_TEST_DATABASE_URL_FILE']).read_text().strip()
        self.schema='app_risk_'+uuid.uuid4().hex
        self.saved=copy.deepcopy(app.S)
        with psycopg.connect(self.url,autocommit=True) as db:
            db.execute(sql.SQL('create schema {}').format(sql.Identifier(self.schema)))
        self.connect=lambda:psycopg.connect(self.url,autocommit=True,row_factory=dict_row,
            options='-c search_path='+self.schema)
        self.store=app.EngineStore(self.connect)
        self.patches=[patch.object(app,'pg',self.connect),patch.object(app,'STORE',self.store),
                      patch.object(app,'WIN',None),patch.object(app,'MARKET_OBS',SimpleNamespace(
                          flow_context=lambda *args:{'trade_data_fresh':False}))]
        for binding in self.patches:binding.start()
        with self.connect() as db:
            for query in app.SCHEMA:db.execute(query)
            db.execute('insert into local_v12_account_state values(1,500,0,%s,%s)',(app.now(),app.now()))
        self.store.migrate()
        self.assertTrue(self.store.claim())
        app.S.update(engine_active=True,orders_enabled=False,mode='PAPER_ONLY',
            local_experiment_equity=500.,local_experiment_realized_pnl=0.,local_experiment_trades=0,
            local_v12_positions={},local_experiment_watch={},local_h1_direction={},_local4_analysis={},
            _prices={},_price_received_epoch={},risk_circuit={},margin_valuation={})

    def tearDown(self):
        self.store.release()
        for binding in reversed(self.patches):binding.stop()
        app.S.clear();app.S.update(self.saved)
        with psycopg.connect(self.url,autocommit=True) as db:
            db.execute(sql.SQL('drop schema {} cascade').format(sql.Identifier(self.schema)))

    def seed_position(self,mark=100.):
        plan=plan_entry(500,500,50,100,1,{},{}).to_dict()
        position=dict(symbol='BTC',side=1,entry=100.,notional=plan['notional'],
            margin=plan['margin'],leverage=plan['leverage'],opened=app.now(),t=time.time(),
            signal_candle_time=1,features={'risk_plan':plan})
        with self.connect() as db:
            db.execute('insert into local_v12_positions values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)',
                ('BTC',1,100.,position['notional'],position['margin'],position['leverage'],position['opened'],
                 position['t'],1,json.dumps(position['features'])))
        app.S['local_v12_positions']={'BTC':position}
        app.S['_prices']={'BTC':mark};app.S['_price_received_epoch']={'BTC':time.time()}
        return position

    def test_stale_held_mark_cannot_finance_another_entry(self):
        self.seed_position()
        app.S['_price_received_epoch']['BTC']=time.time()-60
        status=app.risk_snapshot()
        self.assertFalse(status['allowed'])
        self.assertEqual(status['reason'],'PORTFOLIO_MARKS_STALE')
        self.assertEqual(status['free_margin'],0)
        self.assertEqual(app.S['local_experiment_equity'],500)
        self.assertEqual(app.S['margin_valuation']['missing_marks'],['BTC'])

    def test_stale_checkpoint_and_flow_do_not_disable_fresh_mark_stop_or_hide_loss(self):
        position=self.seed_position(mark=50.)
        app.S['last_checkpoint']=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(minutes=1)).isoformat()
        self.assertIsNone(app.current_entry_price('BTC'))
        self.assertEqual(app.fresh_mark_price('BTC'),50)
        app.local_experiment_mark_positions({'BTC':50.})
        self.assertNotIn('BTC',app.S['local_v12_positions'])
        expected=paper_pnl(position['notional'],100,50,1,app.FEE)
        self.assertLess(expected,0)
        with self.connect() as db:
            history=db.execute('select * from local_v12_trade_history').fetchone()
            equity=db.execute('select equity from local_v12_account_state where id=1').fetchone()['equity']
        self.assertAlmostEqual(history['pnl'],expected)
        self.assertEqual(history['exit'],50)
        self.assertEqual(history['reason'],'modeled_maintenance_breach')
        self.assertAlmostEqual(equity,500+expected)
        self.assertEqual(app.local_experiment_stats()['win_rate'],0)

    def test_stale_flow_does_not_turn_fixed_stop_or_mfe_giveback_into_an_exit(self):
        self.seed_position(mark=98.)
        app.S['last_checkpoint']=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(minutes=1)).isoformat()
        app.local_experiment_mark_positions({'BTC':98.})
        self.assertIn('BTC',app.S['local_v12_positions'])
        # Neither a configured legacy stop nor giving back a large fraction of
        # observed profit is an active strategy exit without flow/local transfer.
        for mark in (110.,105.):
            app.S['_prices']['BTC']=mark;app.S['_price_received_epoch']['BTC']=time.time()
            app.local_experiment_mark_positions({'BTC':mark})
            self.assertIn('BTC',app.S['local_v12_positions'])
        with self.connect() as db:
            self.assertEqual(db.execute('select count(*) n from local_v12_trade_history').fetchone()['n'],0)

    def test_historical_halt_row_and_stale_memory_do_not_pause_funded_trading(self):
        day=app.risk_day() if hasattr(app,'risk_day') else datetime.date.today().isoformat()
        with self.connect() as db:
            db.execute("create table if not exists pandora_risk_sessions(day text primary key,opening_equity double precision not null,peak_equity double precision not null,halted boolean not null default false,reason text,updated_at timestamptz not null default clock_timestamp())")
            db.execute("insert into pandora_risk_sessions(day,opening_equity,peak_equity,halted,reason) values(%s,500,1000,true,'DAILY_LOSS_LIMIT')",(day,))
        app.S['risk_circuit']={'day':day,'allowed':False,'reason':'DAILY_LOSS_LIMIT'}
        status=app.risk_snapshot()
        self.assertTrue(status['allowed'])
        self.assertIsNone(status.get('reason'))
        with self.connect() as db:
            historical=db.execute('select halted,reason from pandora_risk_sessions where day=%s',(day,)).fetchone()
        self.assertTrue(historical['halted'])
        self.assertEqual(historical['reason'],'DAILY_LOSS_LIMIT')

    def test_loss_close_does_not_latch_a_pause_but_cash_and_marks_still_gate_new_risk(self):
        position=self.seed_position(mark=98.)
        result=app.local_experiment_close('BTC',98,'confirmed_counter_move_exit')
        self.assertLess(result['pnl'],0)
        app.restore_state()
        status=app.risk_snapshot()
        self.assertTrue(status['allowed'])
        self.assertLess(status['equity'],500)
        self.assertGreater(status['free_margin'],0)
        next_plan=plan_entry(status['equity'],status['free_margin'],50,100,1,{}, {},status['portfolio_risk'])
        self.assertTrue(next_plan.allowed)
        self.assertGreaterEqual(next_plan.margin,status['equity']*.10-1e-8)
        self.assertGreaterEqual(next_plan.leverage,10)
        self.assertLessEqual(next_plan.margin,status['free_margin'])
        with self.connect() as db:
            row=db.execute('select count(*) n,min(pnl) loss from local_v12_trade_history').fetchone()
        self.assertEqual(row['n'],1)
        self.assertLess(row['loss'],0)
        self.seed_position()
        app.S['_price_received_epoch']['BTC']=time.time()-60
        self.assertFalse(app.risk_snapshot()['allowed'])
        with self.connect() as db:
            db.execute('delete from local_v12_positions')
            db.execute('update local_v12_account_state set equity=0 where id=1')
        app.restore_state()
        self.assertFalse(app.risk_snapshot()['allowed'])

    def test_failed_close_commit_preserves_cash_position_and_trade_count(self):
        position=self.seed_position(mark=98.)
        with patch.object(app,'WIN',SimpleNamespace(semantic_close=lambda *args:(_ for _ in ()).throw(RuntimeError('audit failed')))):
            with self.assertRaisesRegex(RuntimeError,'audit failed'):
                app.local_experiment_close('BTC',98,'risk_stop')
        with self.connect() as db:
            self.assertEqual(db.execute('select count(*) n from local_v12_positions').fetchone()['n'],1)
            self.assertEqual(db.execute('select count(*) n from local_v12_trade_history').fetchone()['n'],0)
            self.assertEqual(db.execute('select equity from local_v12_account_state where id=1').fetchone()['equity'],500)
        self.assertEqual(app.S['local_v12_positions']['BTC']['notional'],position['notional'])
        self.assertEqual(app.S['local_experiment_equity'],500)

    def test_execution_failure_prevents_risk_ready_despite_fresh_market_gates(self):
        stamp=time.time()
        app.S.update(bybit_discovery={'selected_symbols':['BTC']},last_checkpoint=app.now(),
                     _execution_ok=False,_execution_heartbeat=stamp,_execution_errors={'BTC':'failed'},
                     _prices={'BTC':100},_price_received_epoch={'BTC':stamp},
                     _bybit_instruments={'BTC':{'observed_at':stamp}})
        flow=SimpleNamespace(flow_context=lambda *args:{'trade_data_fresh':True,'evidence_ready':True})
        with patch.object(app,'MARKET_OBS',flow),patch.object(app,'strategy1_runtime_h1_verified',return_value=True):
            failed=app.health_state()
            self.assertFalse(failed['risk_ready'])
            self.assertFalse(failed['execution_ok'])
            app.S['_execution_ok']=True
            self.assertTrue(app.health_state()['risk_ready'])

    def test_long_is_refused_if_buy_control_disappears_during_allocation(self):
        stamp=time.time()
        analysis=dict(ready=True,anchor_confirmed=True,h1_direction_anchor=True,
                      entry_side=1,pivot_type='LOCAL_LOW',pivot_price=99,
                      signal_candle_time=1000,pivot_candle_time=500)
        buying=dict(trade_data_fresh=True,latest_trade_age_seconds=0,latest_trade_epoch=stamp,
                    buy_notional=200,sell_notional=100,price_direction=1,
                    windows={},sustained_control_side=1,fast_control_side=1)
        stopped={**buying,'sustained_control_side':0,'fast_control_side':-1}
        app.S.update(bybit_discovery={'selected_symbols':['BTC']},
                     _local4_analysis={'BTC':analysis},local_h1_direction={'BTC':analysis},
                     _bybit_instruments={'BTC':dict(max_leverage=50,observed_at=stamp)})
        tape=SimpleNamespace(flow_context=unittest.mock.Mock(side_effect=[buying,stopped]))
        with patch.object(app,'MARKET_OBS',tape),patch.object(app,'current_entry_price',return_value=100), \
             patch.object(app,'strategy1_runtime_h1_verified',return_value=True):
            self.assertFalse(app.local_experiment_open('BTC',1,analysis))
        self.assertEqual(app.S['strategy1_executor_rejections']['BTC']['reason'],
                         'EXECUTED_CONTROL_CHANGED_DURING_ALLOCATION')
        with self.connect() as db:
            self.assertEqual(db.execute('select count(*) n from local_v12_positions').fetchone()['n'],0)
