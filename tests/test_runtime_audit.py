"""Concurrency, stale-input exits and transactional publication regressions."""
import copy
from contextlib import contextmanager
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from engine_store import LeaseLost
from pandora_runtime import PandoraRuntime
import pandora_runtime


class FakeDB:
    def __init__(self, fail_commit=False, updated=True):
        self.fail_commit=fail_commit
        self.updated=updated
        self.queries=[]

    @contextmanager
    def transaction(self):
        yield self
        if self.fail_commit:raise RuntimeError('commit failed')

    def execute(self,query,params=()):
        self.queries.append((query,params))
        return SimpleNamespace(fetchone=lambda:{'symbol':'BTC'} if self.updated else None)


def fake_runtime():
    a=SimpleNamespace(LOCK=threading.RLock(),ACCOUNT_LOCK=threading.RLock(),FEE=.00045)
    a.S=dict(engine_active=True,bybit_discovery={'at':0,'selected_symbols':['BTC']},
             local_v12_positions={},local_experiment_watch={},_local4_analysis={},sources={})
    a.now=lambda:'fixture'
    a.STORE=SimpleNamespace(fence=lambda db:None)
    database=FakeDB()
    @contextmanager
    def connect():yield database
    a.pg=connect
    a.strategy1_trade_symbols=lambda:tuple(a.S['bybit_discovery']['selected_symbols'])
    a.MARKET_OBS=SimpleNamespace(flow_context=lambda symbol:{'trade_data_fresh':True})
    a.current_entry_price=lambda symbol:None
    a.fresh_mark_price=lambda symbol:101
    a.local_experiment_mark_positions=lambda prices:None
    a._local_experiment_margin_state=lambda:(500.,0.,500.)
    a.strategy1_runtime_h1_verified=lambda *args:False
    r=PandoraRuntime.__new__(PandoraRuntime)
    r.a=a;r.tokens={};r.max_equity=500.;r.last_saved={'account':time.time()}
    r.last_scanner_save=0.;r.last_scanner_at=0.
    r.pyramid=lambda *args:False
    r.transition=lambda *args,**kwargs:None
    r.reload_token=lambda symbol:None
    return r,a,database


def position():
    return dict(symbol='BTC',side=1,entry=100.,margin=10.,notional=250.,
                leverage=25.,opened='fixture',features={})


class RuntimeSerializationTests(unittest.TestCase):
    def test_operator_mutation_waits_until_whole_position_cycle_finishes(self):
        runtime,a,_=fake_runtime()
        entered=threading.Event();release=threading.Event();operator_done=threading.Event()
        def token_cycle(symbol,prices):
            entered.set()
            if not release.wait(2):raise RuntimeError('test synchronization timeout')
        runtime._cycle_symbol=token_cycle
        worker=threading.Thread(target=runtime.cycle,args=({},))
        def operator():
            with a.ACCOUNT_LOCK:operator_done.set()
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            closer=threading.Thread(target=operator);closer.start()
            self.assertFalse(operator_done.wait(.05))
            release.set();worker.join(2);closer.join(2)
            self.assertFalse(worker.is_alive())
            self.assertTrue(operator_done.is_set())
        finally:
            release.set();worker.join(2)

    def test_position_removed_at_metrics_boundary_is_never_resurrected(self):
        runtime,a,_=fake_runtime()
        a.S['local_v12_positions']['BTC']=position()
        runtime.last_saved['position:BTC']=time.time()
        def external_close(p,*args):
            updated=copy.deepcopy(p)
            a.S['local_v12_positions'].pop('BTC')
            return updated
        with patch.object(pandora_runtime,'mark_metrics',external_close):
            runtime.cycle({'BTC':101})
        self.assertNotIn('BTC',a.S['local_v12_positions'])

    def test_zero_row_canonical_update_does_not_publish_phantom_features(self):
        runtime,a,database= fake_runtime()
        a.S['local_v12_positions']['BTC']=position()
        database.updated=False
        runtime.cycle({'BTC':101})
        self.assertNotIn('BTC',a.S['local_v12_positions'])
        self.assertTrue(any('returning symbol' in q for q,_ in database.queries))

    def test_one_token_error_does_not_block_other_positions_and_marks_readiness_failed(self):
        runtime,a,_=fake_runtime()
        a.S['bybit_discovery']['selected_symbols']=['BTC','ETH']
        seen=[]
        def process(symbol,prices):
            seen.append(symbol)
            if symbol=='BTC':raise ValueError('invalid token state')
        runtime._cycle_symbol=process
        runtime.cycle({})
        self.assertEqual(seen,['BTC','ETH'])
        self.assertFalse(a.S['_execution_ok'])
        self.assertIn('BTC',a.S['_execution_errors'])
        self.assertGreater(a.S['_execution_heartbeat'],0)

    def test_lost_lease_aborts_every_new_mutation_instead_of_continuing(self):
        runtime,a,_=fake_runtime()
        a.S['bybit_discovery']['selected_symbols']=['BTC','ETH']
        seen=[]
        def process(symbol,prices):seen.append(symbol);raise LeaseLost('lease lost')
        runtime._cycle_symbol=process
        with self.assertRaises(LeaseLost):runtime.cycle({})
        self.assertEqual(seen,['BTC'])
        self.assertFalse(a.S['_execution_ok'])
        self.assertIn('__cycle__',a.S['_execution_errors'])

    def test_fresh_mark_risk_guard_runs_despite_stale_flow_and_entry_checkpoint(self):
        runtime,a,_=fake_runtime()
        a.S['local_v12_positions']['BTC']=position()
        a.MARKET_OBS.flow_context=lambda symbol:{'trade_data_fresh':False}
        seen=[]
        def guard(prices):
            seen.append(prices)
            a.S['local_v12_positions'].pop('BTC')
        a.local_experiment_mark_positions=guard
        runtime.cycle({'BTC':101})
        self.assertEqual(seen,[{'BTC':101}])
        self.assertNotIn('BTC',a.S['local_v12_positions'])


class ScannerPublicationTests(unittest.TestCase):
    def snapshot(self):
        return dict(at=1.,selected_symbols=[],states={'OLD':'ROTATE_OUT'},events=[
            dict(action='TOKEN_ROTATED',symbol='OLD',state='ROTATE_OUT',reason='faded')])

    def test_failed_commit_keeps_prior_selection_and_watch_in_memory(self):
        runtime,a,db=fake_runtime()
        a.S['local_experiment_watch']['OLD']={'exit_at':'old'}
        original=copy.deepcopy(a.S['bybit_discovery'])
        db.fail_commit=True
        with self.assertRaisesRegex(RuntimeError,'commit failed'):
            runtime.scanner_snapshot(self.snapshot())
        self.assertEqual(a.S['bybit_discovery'],original)
        self.assertIn('OLD',a.S['local_experiment_watch'])

    def test_fresh_position_snapshot_overrides_stale_rotate_out_decision(self):
        runtime,a,db=fake_runtime()
        a.S['local_v12_positions']['OLD']={**position(),'symbol':'OLD'}
        a.S['local_experiment_watch']['OLD']={'exit_at':'old'}
        self.assertTrue(runtime.scanner_snapshot(self.snapshot()))
        current=a.S['bybit_discovery']
        self.assertEqual(current['states']['OLD'],'FADING')
        self.assertIn('OLD',current['retained_open_positions'])
        self.assertIn('OLD',a.S['local_experiment_watch'])
        self.assertFalse(any('delete from local_v12_watchlist' in q for q,_ in db.queries))

    def test_older_selection_cannot_replace_newer_published_selection(self):
        runtime,a,_=fake_runtime()
        runtime.last_scanner_at=2.
        self.assertFalse(runtime.scanner_snapshot(self.snapshot()))
        self.assertEqual(a.S['bybit_discovery']['selected_symbols'],['BTC'])
