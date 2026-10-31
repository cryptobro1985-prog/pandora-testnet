"""Regression contracts for the operator's H1 -> flow -> Caterpillar workflow."""
import copy
import json
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import app
from h1_structure import analyze
from local_order_flow import initial_entry_candidate, pressure_exit, update_watch, reentry_ready
from market_data import RollingMarketData
from strategy1_monitor import render

H=3_600_000
BASE=1_780_002_000_000//H*H


def bars():
    values=[(100,102,99,101),(101,103,100,102),(102,104,101,103),(103,105,102,104),
            (104,110,103,109),(108,109,101,102),(102,108,100,101),(101,107,98,99),
            (100,108,99,107),(107,111,106,110)]
    return [dict(t=BASE+i*H,T=BASE+(i+1)*H-1,o=o,h=h,l=l,c=c,v=100) for i,(o,h,l,c) in enumerate(values)]


def flow(side=1,epoch=1000):
    return dict(trade_data_fresh=True,latest_trade_age_seconds=.1,latest_trade_epoch=epoch-.1,
                observed_at_epoch=epoch,buy_notional=200 if side>0 else 100,
                sell_notional=100 if side>0 else 200,price_direction=side)


class CausalStructureTests(unittest.TestCase):
    def test_high_confirms_only_after_lower_high_lower_low_closes(self):
        rows=bars()
        self.assertEqual(analyze(rows,BASE+6*H-1000).get('entry_side',0),0)
        result=analyze(rows,BASE+6*H+1000)
        self.assertEqual(result['entry_side'],-1)
        self.assertEqual(result['pivot_price'],110)
        self.assertEqual(result['signal_candle_close_time'],rows[5]['T'])

    def test_low_changes_only_after_higher_low_higher_high_closes(self):
        rows=bars()
        self.assertEqual(analyze(rows,BASE+8*H+1000)['entry_side'],-1)
        self.assertEqual(analyze(rows,BASE+9*H+1000)['entry_side'],1)

    def test_future_bars_cannot_change_any_prefix_decision(self):
        rows=bars()
        for n in range(6,len(rows)+1):
            stamp=BASE+n*H+1000
            self.assertEqual(analyze(rows,stamp),analyze(rows[:n],stamp))

    def test_gap_blocks_current_runtime_proof(self):
        rows=bars();rows.pop(3)
        self.assertEqual(analyze(rows,BASE+10*H+1000)['reason'],'gapped_h1_history')

    def test_no_percentage_retracement_or_candle_color_gate(self):
        rows=bars()[:6]
        rows[4].update(o=104,h=105.01,l=103,c=104)
        rows[5].update(o=103.5,h=105.0,l=102.99,c=104.99)
        self.assertEqual(analyze(rows,BASE+6*H+1000)['entry_side'],-1)


class FlowContracts(unittest.TestCase):
    def test_entry_has_no_minute_candle_gate(self):
        f=flow();f['unrelated_display_metadata']='ignored'
        a=dict(ready=True,anchor_confirmed=True,h1_direction_anchor=True,entry_side=1)
        self.assertTrue(initial_entry_candidate('BTC',a,None,f,1000)['eligible'])

    def test_small_bounce_holds_and_structural_transfer_exits_symmetrically(self):
        for side in (-1,1):
            position=dict(side=side,entry=100,features={'mfe_price_move':.8})
            def tick(delta,control,epoch):
                return pressure_exit(position,None,100+side*delta,flow(control,epoch))
            self.assertIsNone(tick(1,side,1000))
            self.assertIsNone(tick(.9,-side,1001))
            self.assertIsNone(tick(1.2,side,1002))
            self.assertEqual(tick(.7,-side,1003),'confirmed_counter_move_exit')
            for count in range(15):
                w=dict(side=side,exit_price=100,reentries=count,context={})
                for delta,control,epoch in [(-1,-side,1004),(-.8,side,1005),(-.9,-side,1006)]:
                    w=update_watch(w,100+side*delta,None,flow(control,epoch),epoch)
                    self.assertFalse(reentry_ready(side,None,100,w,flow(side,epoch),epoch))
                w=update_watch(w,100+side*(-.5),None,flow(side,1007),1007)
                self.assertTrue(reentry_ready(side,None,100,w,flow(side,1007),1007))

    def test_declared_freshness_boundary_and_missing_data(self):
        a=dict(ready=True,anchor_confirmed=True,h1_direction_anchor=True,entry_side=1)
        for age in (14,22,45,61):
            f=flow();f.update(latest_trade_age_seconds=age,freshness_limit_seconds=60,trade_data_fresh=age<=60)
            self.assertEqual(initial_entry_candidate('BTC',a,None,f,1000)['eligible'],age<=60)
        self.assertIsNone(pressure_exit(dict(side=1,entry=100),None,100,{}))

    def test_live_peer_heartbeat_cannot_refresh_a_silent_shard(self):
        obs=RollingMarketData(freshness_seconds=15)
        obs.mark_connected(1000,['BTC'],owner='btc')
        obs.mark_connected(1000,['SOL'],owner='sol')
        for symbol in ('BTC','SOL'):
            obs.ingest_trades([dict(coin=symbol,px='100',sz='1',time=1001000,side='B',tid='1')],1001,owner=symbol.lower())
        obs.heartbeat(1020,owner='sol')
        # Even a permissive trade age cannot establish a live transport on BTC.
        self.assertFalse(obs.flow_context('BTC',1020)['trade_data_fresh'])
        self.assertNotEqual(obs._symbols['BTC']['since'],1020)
        self.assertEqual(obs._symbols['SOL']['since'],1020)

    def test_reconnect_invalidates_only_affected_shard(self):
        obs=RollingMarketData()
        obs.mark_connected(1000,['BTC'],owner='btc')
        obs.mark_connected(1000,['SOL'],owner='sol')
        for sym in ('BTC','SOL'):
            obs.ingest_trades([dict(coin=sym,px='100',sz='1',time=1001000,side='B',tid='1')],1001)
        self.assertTrue(obs.flow_context('BTC',1001)['trade_data_fresh'])
        obs.mark_disconnected(owner='btc')
        self.assertFalse(obs.flow_context('BTC',1001)['trade_data_fresh'])
        self.assertTrue(obs.flow_context('SOL',1001)['trade_data_fresh'])
        obs.mark_connected(1002,['BTC'],owner='btc')
        self.assertFalse(obs.flow_context('BTC',1002)['trade_data_fresh'])


class RuntimeContracts(unittest.TestCase):
    def setUp(self):self.saved=copy.deepcopy(app.S)
    def tearDown(self):app.S.clear();app.S.update(self.saved)

    def test_subscriptions_do_not_depend_on_h1_readiness(self):
        app.S['_local4_analysis']={};app.S['local_h1_direction']={}
        self.assertEqual(set(app.strategy1_trade_symbols()),set(app.LOCAL_EXPERIMENT_SYMBOLS))

    def test_verified_closed_hour_does_not_expire_after_90_seconds(self):
        stamp=(BASE+6*H+1000)/1000
        a=analyze(bars(),stamp*1000)
        meta={k:a.get(k) for k in ('entry_side','signal_candle_time','pivot_candle_time','last_candle_time')}
        meta['verified_at']=stamp
        app.S['_local_h1_runtime_verified']={'BTC':meta}
        self.assertTrue(app.strategy1_runtime_h1_verified('BTC',a,stamp+300))
        self.assertFalse(app.strategy1_runtime_h1_verified('BTC',a,stamp+H/1000))

    def test_no_wait_holds_global_state_lock(self):
        import ast
        tree=ast.parse(Path(app.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.With) and any(ast.unparse(item.context_expr)=='LOCK' for item in node.items):
                waits=[call for call in ast.walk(node) if isinstance(call,ast.Call)
                       and ast.unparse(call.func)=='SHUTDOWN.wait']
                self.assertFalse(waits, f"wait under LOCK at line {node.lineno}")

    def test_quote_and_checkpoint_alone_never_claim_live_trade_readiness(self):
        stamp=time.time()
        app.S.update(engine_active=True,_last_poll_epoch=stamp,last_checkpoint=app.now(),
                     _market_heartbeat=stamp,_coordinator_heartbeat=stamp,_local4_analysis={})
        self.assertFalse(app.health_state()['risk_ready'])
        self.assertEqual(len(app.health_state()['token_readiness']),10)

    def test_removed_strategy_entrypoints_are_absent(self):
        for name in ('emergency_profit_take','xnews','whale_liq_open','comparison_strategies_loop'):
            self.assertFalse(hasattr(app,name))

    def test_monitor_never_adds_benchmark_to_actual_result(self):
        data=dict(strategy1_primary=dict(realized_pnl=0,unrealized_pnl=0,total_equity=500),health={},local_experiment_symbols=['BTC'])
        page=render(data)
        self.assertNotIn('377.36',page)
        self.assertNotIn('● PAPER LIVE',page)
        self.assertIn('НЕ ГОТОВ',page)
        self.assertIn('500.0000',page)
        self.assertIn('BTC',page)


@unittest.skipUnless(os.getenv('PANDORA_TEST_DATABASE_URL_FILE'),'isolated PostgreSQL required')
class PaperIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg.rows import dict_row
        cls.url=Path(os.environ['PANDORA_TEST_DATABASE_URL_FILE']).read_text().strip()
        cls.connect=staticmethod(lambda:psycopg.connect(cls.url,autocommit=True,row_factory=dict_row))

    def setUp(self):
        self.saved=copy.deepcopy(app.S)
        self.pgpatch=patch.object(app,'pg',self.connect);self.pgpatch.start()
        app.pinit()
        from engine_store import EngineStore
        self.store=EngineStore(self.connect)
        self.assertTrue(self.store.claim())
        self.storepatch=patch.object(app,'STORE',self.store);self.storepatch.start()

    def tearDown(self):
        with self.connect() as db:
            db.execute("delete from local_v12_watchlist where symbol='TEST'")
            db.execute("delete from local_v12_trade_history where symbol='TEST'")
        self.store.release();self.storepatch.stop();self.pgpatch.stop()
        app.S.clear();app.S.update(self.saved)

    def test_exit_arms_durable_reentry_watch_and_retry_cannot_credit_twice(self):
        position=dict(symbol='TEST',side=1,entry=100,notional=250,margin=10,leverage=25,
                      opened='2026-10-31T00:00:00+00:00',t=1000,signal_candle_time=1000,features={})
        with self.connect() as db:
            before=db.execute('select equity from local_v12_account_state where id=1').fetchone()['equity']
            db.execute("""insert into local_v12_positions(symbol,side,entry,notional,margin,leverage,opened,opened_epoch,signal_candle_time,features)
                          values('TEST',1,100,250,10,25,%s,1000,1000,'{}')""",(position['opened'],))
        app.S['local_v12_positions']={'TEST':position}
        result=app.local_experiment_close('TEST',99,'confirmed_counter_move_exit',watch_context={'flow_context':flow(-1)})
        self.assertIsNotNone(result)
        self.assertIsNone(app.local_experiment_close('TEST',99,'confirmed_counter_move_exit'))
        with self.connect() as db:
            watch=db.execute("select context from local_v12_watchlist where symbol='TEST'").fetchone()['context']
            after=db.execute('select equity from local_v12_account_state where id=1').fetchone()['equity']
            self.assertEqual(db.execute("select count(*) n from local_v12_trade_history where symbol='TEST'").fetchone()['n'],1)
            # Restore only this test's isolated account delta.
            db.execute('update local_v12_account_state set equity=equity-%s,realized_pnl=realized_pnl-%s where id=1',(result['pnl'],result['pnl']))
        self.assertEqual(watch['phase'],'WAIT_RESUMPTION')
        self.assertTrue(watch['counter_pressure_seen'])
        self.assertAlmostEqual(after-before,result['pnl'])

    def test_parallel_fences_do_not_serialize_unrelated_writes(self):
        with self.connect() as first,self.connect() as second:
            with first.transaction(),second.transaction():
                self.store.fence(first)
                self.store.fence(second)
        from engine_store import EngineStore
        self.assertFalse(EngineStore(self.connect).claim())
