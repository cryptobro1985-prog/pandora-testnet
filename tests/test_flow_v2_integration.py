"""Real PostgreSQL and WebSocket integration of the active flow-only executor."""
import copy
import json
import os
from pathlib import Path
import threading
import time
import unittest
import uuid
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import app
from bybit_market_stream import run_bybit_stream
from engine_store import EngineStore
from market_data import RollingMarketData
from pandora_runtime import PandoraRuntime
from tests.archive_v1 import pandora_end_to_end_v1 as wire


@unittest.skipUnless(os.getenv('PANDORA_TEST_DATABASE_URL_FILE'),'isolated PostgreSQL required')
class FlowV2ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.url=Path(os.environ['PANDORA_TEST_DATABASE_URL_FILE']).read_text().strip()
        self.schema='flow_wire_'+uuid.uuid4().hex
        self.saved=copy.deepcopy(app.S);self.saved_win=app.WIN
        self.connect=lambda:psycopg.connect(self.url,autocommit=True,row_factory=dict_row,options='-c search_path='+self.schema)
        self.obs=RollingMarketData()
        self.store=EngineStore(self.connect)
        self.patches=[patch.object(app,'pg',self.connect),patch.object(app,'EXPERIMENT_SCHEMA',self.schema),
                      patch.object(app,'STORE',self.store),patch.object(app,'MARKET_OBS',self.obs)]
        for binding in self.patches:binding.start()
        app.initialize(app.pg,app.SCHEMA,schema=self.schema)
        app.pinit();self.assertTrue(self.store.claim())
        app.S.update(engine_active=True,mode='PAPER_ONLY',orders_enabled=False,_prices={},_price_received_epoch={},
                     _pandora_path_persist_epoch={},sources={},_execution_errors={})
        stamp=time.time()
        discovery=dict(observations_ready=True,ranked_rows=[dict(symbol='BTC',rank=1,last=100,
                       change_24h_pct=50,turnover_24h=1000000,volume_24h=10000)])
        snapshot=app.WIN.universe.update(discovery,epoch=stamp)
        app.WIN.scanner_snapshot(snapshot)
        app.S['_bybit_instruments']={'BTC':dict(max_leverage=25,observed_at=stamp)}
        self.server=wire.BybitFixtureServer();self.stop=threading.Event();self.reports=[]
        self.transport=threading.Thread(target=run_bybit_stream,args=(self.obs,self.stop,lambda:set(app.pandora_runtime_symbols()),self.reports.append),
            kwargs={'url':f'ws://127.0.0.1:{self.server.port}/public','worker_name':'flow-wire','on_trade_mids':app.accept_market_prices},daemon=True)
        self.transport.start();self.wait_for(lambda:'publicTrade.BTCUSDT' in self.server.topics)

    def wait_for(self,condition):
        limit=time.monotonic()+5
        while time.monotonic()<limit:
            if condition():return
            time.sleep(.005)
        self.fail('wire timeout '+str(self.reports[-1:]))

    def trade(self,side,price,notional=100):
        previous=self.obs.stats()['accepted']
        self.server.trade('BTC',side,notional/price,price)
        self.wait_for(lambda:self.obs.stats()['accepted']>previous)
        self.wait_for(lambda:app.S.get('_prices',{}).get('BTC')==price)
        app.S['last_checkpoint']=app.now()
        app.WIN.cycle({'BTC':price})
        self.assertFalse(app.S.get('_execution_errors'),app.S.get('_execution_errors'))
        return app.WIN.current_decision('BTC')

    def pump(self):
        for price in (100,100.2,100.4):self.trade(1,price)
        self.assertIn('BTC',app.S['pandora_win_positions'],app.WIN.current_decision('BTC'))
        self.assertEqual(app.S['pandora_win_positions']['BTC']['side'],1)

    def tearDown(self):
        self.stop.set();self.server.close();self.transport.join(5)
        self.assertFalse(self.transport.is_alive())
        self.store.release()
        for binding in reversed(self.patches):binding.stop()
        app.S.clear();app.S.update(self.saved);app.WIN=self.saved_win
        with psycopg.connect(self.url,autocommit=True) as db:
            db.execute(sql.SQL('drop schema {} cascade').format(sql.Identifier(self.schema)))

    def test_wire_opens_from_new_executions_without_candles_and_polling_adds_no_proof(self):
        self.pump()
        state=copy.deepcopy(app.WIN.strategy.get_state('BTC'))
        for _ in range(100):app.WIN.cycle({'BTC':100.4})
        after=app.WIN.strategy.get_state('BTC')
        self.assertEqual(after['event_count'],state['event_count'])
        self.assertEqual(after['dominance_persistence_events'],state['dominance_persistence_events'])
        self.assertEqual(len(app.S['pandora_win_positions']),1)
        self.assertEqual(app.S['pandora_trades'],0)

    def test_rotation_preserves_held_position_and_restart_preserves_account_and_universe(self):
        self.pump()
        before=copy.deepcopy(app.S['pandora_win_positions']['BTC'])
        first=app.WIN.universe.to_dict();due=first['next_refresh_at']
        snapshot=app.WIN.universe.update({'observations_ready':True,'ranked_rows':[{'symbol':'ETH','rank':1,'last':200}]},held=['BTC'],epoch=due)
        app.WIN.scanner_snapshot(snapshot)
        self.assertEqual(app.S['pandora_win_positions']['BTC']['opened'],before['opened'])
        self.assertIn('BTC',app.pandora_runtime_symbols())
        self.assertEqual(snapshot['states']['BTC'],'MANAGED_POSITION')
        restored=PandoraRuntime(app)
        self.assertEqual(restored.universe.entry_symbols,('ETH',))
        self.assertEqual(restored.universe.next_refresh_at,app.WIN.universe.next_refresh_at)
        self.assertEqual(app.S['pandora_equity'],500)
        self.assertEqual(app.S['pandora_win_positions']['BTC']['entry'],before['entry'])
        self.assertGreaterEqual(self.obs.execution_sequences()['BTC'],3)

    def test_money_close_and_strategy_ack_commit_together_and_retries_cannot_double_credit(self):
        self.pump()
        result=app.pandora_close('BTC',100.5,'operator_paper_close')
        self.assertIsNotNone(result)
        self.assertIsNone(app.pandora_close('BTC',100.5,'operator_paper_close'))
        self.assertEqual(app.WIN.strategy.get_state('BTC')['actual_side'],0)
        with self.connect() as db:
            self.assertEqual(db.execute('select count(*) n from pandora_win_trade_history').fetchone()['n'],1)
            state=db.execute("select payload from pandora_win_runtime_state where name='flow_strategy'").fetchone()['payload']
            self.assertEqual(state['tokens']['BTC']['close_ack']['sequence'],3)
            self.assertAlmostEqual(db.execute('select equity from pandora_win_account_state where id=1').fetchone()['equity'],500+result['pnl'])

    def test_real_flow_transfer_closes_then_new_independent_executions_reverse(self):
        for price in (100,100.2,100.4,100.8,101.2,101.6,102,102.4,102.8,103):self.trade(1,price)
        self.trade(-1,102.9,10)
        self.assertEqual(app.S['pandora_win_positions']['BTC']['side'],1)
        self.trade(1,103.5,300)
        for price in (103.2,102.9,102.4):self.trade(-1,price,3000)
        self.assertNotIn('BTC',app.S['pandora_win_positions'])
        for price in (102.1,101.8):
            self.trade(-1,price,3000)
            self.assertNotIn('BTC',app.S['pandora_win_positions'])
        self.trade(-1,101.5,3000)
        self.assertEqual(app.S['pandora_win_positions']['BTC']['side'],-1)
        with self.connect() as db:
            self.assertEqual(db.execute("select count(*) n from pandora_win_audit_journal where kind='pandora_REVERSE_LONG_TO_SHORT'").fetchone()['n'],1)
            self.assertEqual(db.execute('select count(*) n from pandora_win_trade_history').fetchone()['n'],1)

    def test_profitable_flow_add_keeps_quantity_average_and_survives_restart(self):
        self.pump()
        original=copy.deepcopy(app.S['pandora_win_positions']['BTC'])
        self.trade(1,101,10000)
        current=app.S['pandora_win_positions']['BTC']
        self.assertGreater(current['features']['pyramid_level'],0,current['features'].get('pyramid_state'))
        record=current['features']['pyramid_adds'][0]
        self.assertAlmostEqual(current['notional']/current['entry'],original['notional']/original['entry']+record['added_notional']/101)
        app.restore_state()
        restored=PandoraRuntime(app)
        self.assertEqual(app.S['pandora_win_positions']['BTC']['features']['pyramid_level'],1)
        self.assertEqual(app.S['pandora_equity'],500)
        with self.connect() as db:
            self.assertEqual(db.execute('select count(*) n from pandora_win_pyramid_adds').fetchone()['n'],1)

    def test_close_requires_executions_after_actual_fill_not_already_queued_trades(self):
        self.pump()
        for price in (100.3,100.2,100.1):
            previous=self.obs.stats()['accepted']
            self.server.trade('BTC',-1,1000/price,price)
            self.wait_for(lambda:self.obs.stats()['accepted']>previous)
        self.assertIsNotNone(app.pandora_close('BTC',100.1,'operator_paper_close'))
        self.assertEqual(app.WIN.strategy.get_state('BTC')['close_ack']['sequence'],6)
        app.WIN.cycle({'BTC':100.1})
        self.assertNotIn('BTC',app.S['pandora_win_positions'])
        for price in (99.8,99.5):
            self.trade(-1,price,1000)
            self.assertNotIn('BTC',app.S['pandora_win_positions'])
        self.trade(-1,99.2,1000)
        self.assertEqual(app.S['pandora_win_positions']['BTC']['side'],-1)

    def test_failed_money_transaction_never_acknowledges_strategy_close(self):
        self.pump()
        original=app.WIN.semantic_close
        def fail_after_writes(*args):
            original(*args)
            raise RuntimeError('forced transaction rollback')
        with patch.object(app.WIN,'semantic_close',side_effect=fail_after_writes):
            with self.assertRaisesRegex(RuntimeError,'forced transaction rollback'):
                app.pandora_close('BTC',100.5,'operator_paper_close')
        self.assertIn('BTC',app.S['pandora_win_positions'])
        self.assertEqual(app.WIN.strategy.get_state('BTC')['actual_side'],1)
        with self.connect() as db:
            self.assertEqual(db.execute('select count(*) n from pandora_win_trade_history').fetchone()['n'],0)
            self.assertEqual(db.execute('select equity from pandora_win_account_state where id=1').fetchone()['equity'],500)

    def test_stale_is_uncertain_without_immediate_close_then_fresh_mark_breach_can_reduce_risk(self):
        self.pump()
        self.obs.mark_disconnected(owner='flow-wire')
        # The stream worker has its own owner; explicitly stale every owner heartbeat.
        with self.obs._lock:
            for owner in self.obs._owner_heartbeats:self.obs._owner_heartbeats[owner]=time.time()-100
        app.WIN.cycle({'BTC':100.4})
        self.assertIn('BTC',app.S['pandora_win_positions'])
        self.assertEqual(app.WIN.current_decision('BTC')['action'],'DATA_UNCERTAIN')
        app.accept_market_prices({'BTC':99.9})
        app.WIN.cycle({'BTC':99.9})
        self.assertNotIn('BTC',app.S['pandora_win_positions'])
        with self.connect() as db:
            row=db.execute('select reason,pnl from pandora_win_trade_history').fetchone()
        self.assertEqual(row['reason'],'data_loss_observed_structure_breach')
        self.assertLess(row['pnl'],0)
