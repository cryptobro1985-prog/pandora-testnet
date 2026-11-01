"""Deterministic software contracts; synthetic inputs, no PnL optimization."""
import copy
import json
import os
import unittest

from accounting import paper_pnl
from pandora_flow import summarize
from pandora_locals import live_locals, execution_anchor
from pandora_scanner import LiveScanner
from pandora_win_core import allocation, apply_add, pyramid_decision, mark_metrics
from tests import test_strategy1_end_to_end as fixture
from tests.test_strategy1_restoration import bars, BASE, H
import app


class ExecutedStrengthTests(unittest.TestCase):
    def test_volume_majority_is_not_trade_count_and_absorption_is_visible(self):
        trades=[(1000+i*.01,100,1,'A') for i in range(100)]
        trades += [(1001,100,1000,'B'),(1002,100,1000,'B')]
        f=summarize(trades,1002,60)
        self.assertEqual(f['windows']['60']['trade_count'],102)
        self.assertGreater(f['windows']['60']['imbalance'],0)
        self.assertTrue(f['buy_absorbed'])
        self.assertEqual(f['sustained_control_side'],0)

    def test_sustained_sellers_have_price_response_velocity_and_multiple_windows(self):
        rows=[(1000,100,100,'A'),(1001,99,200,'A'),(1002,98,300,'A')]
        f=summarize(rows,1002,60)
        self.assertEqual(f['sustained_control_side'],-1)
        self.assertGreater(f['sell_price_response'],0)
        self.assertGreater(f['volume_velocity'],0)
        self.assertEqual(set(f['windows']),{'5','15','30','60','180','300'})


class ScannerTests(unittest.TestCase):
    def test_live_acceleration_beats_old_daily_pump_and_retains_open_rotations(self):
        scanner=LiveScanner()
        instruments={str(i):{} for i in range(7)}
        for i in range(7):
            scanner.ingest(dict(symbol=str(i)+'USDT',lastPrice='100',turnover24h='1000000',price24hPcnt='0.1'),1000000,1000)
        first=scanner.rank(instruments,lambda *args:{},epoch=1000)
        self.assertEqual(len(first['selected_symbols']),5)
        held=first['selected_symbols'][0]
        for i in range(7):
            scanner.ingest(dict(symbol=str(i)+'USDT',lastPrice=str(99 if str(i)==held else 101+i),turnover24h=str(1001000+i*100)),1020000,1020)
        second=scanner.rank(instruments,lambda *args:{},held=[held],epoch=1020)
        self.assertNotIn(held,second['selected_symbols'])
        self.assertIn(held,second['retained_open_positions'])
        self.assertEqual(second['states'][held],'FADING')
        third=scanner.rank(instruments,lambda *args:{},epoch=1020)
        self.assertEqual(third['states'][held],'ROTATE_OUT')

    def test_stale_regressing_or_restored_observations_cannot_create_live_selection(self):
        scanner=LiveScanner()
        row=dict(symbol='BTCUSDT',lastPrice='100',turnover24h='1000',price24hPcnt='.5')
        self.assertFalse(scanner.ingest(row,1000000,1020))
        self.assertTrue(scanner.ingest(row,1020000,1020))
        self.assertFalse(scanner.ingest(row,1019000,1020))
        snapshot=scanner.rank({'BTC':{}},lambda *a:{},epoch=1020)
        restored=LiveScanner();restored.restore(snapshot)
        self.assertEqual(restored.rank({'BTC':{}},lambda *a:{},epoch=1020)['selected_symbols'],[])


class OnlineLocalTests(unittest.TestCase):
    def test_observed_forming_extension_never_erases_confirmed_local(self):
        history=bars()[:9]
        now=BASE+9*H+30_000
        partial=dict(t=BASE+9*H,T=BASE+10*H-1,o=107,h=108,l=90,c=91,v=50,observed_at_ms=now)
        a=live_locals(history+[partial],[],now,'BTC')
        self.assertEqual(a['confirmed_local']['pivot_type'],'LOCAL_LOW')
        self.assertEqual(a['forming_local']['pivot_type'],'LOCAL_LOW')
        self.assertEqual(a['forming_local']['pivot_price'],90)
        self.assertTrue(a['entry_blocked'])
        partial.update(l=85,c=86,observed_at_ms=now+1)
        b=live_locals(history+[partial],[],now+1,'BTC')
        self.assertEqual(b['forming_local']['pivot_price'],85)
        self.assertEqual(a['confirmed_local'],b['confirmed_local'])

    def test_historical_final_partial_candle_is_never_read_without_observation_proof(self):
        rows=bars();stamp=BASE+6*H+1000
        self.assertEqual(live_locals(rows,[],stamp,'BTC'),live_locals(rows[:6],[],stamp,'BTC'))

    def test_m15_confirmation_cannot_precede_observed_extreme(self):
        history=bars()[:9];start=BASE+9*H;now=start+31*60_000
        partial=dict(t=start,T=start+H-1,o=107,h=108,l=90,c=100,v=50,observed_at_ms=now)
        m15=[dict(t=start+i*900000,T=start+(i+1)*900000-1,o=95+i,h=100+i,l=91+i,c=96+i,v=10) for i in range(2)]
        a=live_locals(history+[partial],m15,now,'BTC')
        self.assertFalse(a['forming_local']['m15_confirmation'])
        partial['low_observed_at_ms']=start+1000
        b=live_locals(history+[partial],m15,now,'BTC')
        self.assertTrue(b['forming_local']['m15_confirmation'])
        f=dict(trade_data_fresh=True,sustained_control_side=1,latest_trade_epoch=now/1000)
        promoted=execution_anchor(b,f)
        self.assertEqual(promoted['entry_side'],1)
        self.assertFalse(promoted['entry_blocked'])
        self.assertEqual(promoted['confirmed_local'],b['confirmed_local'])


class PyramidAccountingTests(unittest.TestCase):
    def test_add_preserves_quantity_accounting_and_separate_mfe_record(self):
        p=dict(entry=100,notional=1000,margin=40,side=1,leverage=25,features={})
        f=dict(windows={'15':dict(volume_velocity=20,buy_volume=100,sell_volume=0)},decision_event_epoch=1000)
        updated,record=apply_add(p,110,20,f,{},'fixture')
        self.assertAlmostEqual(updated['notional']/updated['entry'],1000/100+500/110)
        for mark in (90,110,120):
            self.assertAlmostEqual(paper_pnl(updated['notional'],updated['entry'],mark,1),
                paper_pnl(1000,100,mark,1)+paper_pnl(500,110,mark,1))
        self.assertEqual(record['add_number'],1)
        marked=mark_metrics(updated,120,{},{});peak=marked['features']['peak_mfe_usd']
        pulled=mark_metrics(marked,115,{}, {})
        self.assertEqual(pulled['features']['peak_mfe_usd'],peak)
        self.assertGreater(pulled['features']['mfe_giveback_usd'],0)

    def test_add_requires_profit_later_event_volume_increase_and_respects_cap(self):
        p=dict(entry=100,notional=1000,margin=40,side=1,leverage=25,features={
            'pyramid_state':dict(last_impulse_price=100,baseline_velocity=10,baseline_side_volume=100,last_add_event=10)})
        a=dict(anchor_confirmed=True,entry_side=1)
        f=dict(trade_data_fresh=True,sustained_control_side=1,decision_event_epoch=11,
               windows={'15':dict(volume_velocity=20,buy_volume=200)})
        self.assertTrue(pyramid_decision(p,a,f,110)[0])
        self.assertFalse(pyramid_decision(p,a,f,99)[0])
        self.assertFalse(pyramid_decision(p,a,{**f,'decision_event_epoch':10},110)[0])
        self.assertFalse(pyramid_decision(p,a,{**f,'trade_data_fresh':False},110)[0])
        capped=copy.deepcopy(p);capped['features']['pyramid_level']=2
        self.assertFalse(pyramid_decision(capped,a,f,110,max_adds=2)[0])

    def test_allocation_compounds_and_honors_contract_leverage(self):
        self.assertEqual(allocation(500,500,10)['margin'],100)
        self.assertEqual(allocation(800,800,100)['margin'],160)
        self.assertEqual(allocation(800,800,100)['leverage'],25)


@unittest.skipUnless(os.getenv('PANDORA_TEST_DATABASE_URL_FILE'),'isolated PostgreSQL required')
class PersistentPyramidTests(unittest.TestCase):
    setUp=fixture.SelectedMarketExecutionTests.setUp
    tearDown=fixture.SelectedMarketExecutionTests.tearDown
    send=fixture.SelectedMarketExecutionTests.send
    wait_for=fixture.SelectedMarketExecutionTests.wait_for

    def test_real_wire_add_is_atomic_idempotent_and_survives_runtime_restart(self):
        from pandora_runtime import PandoraRuntime
        symbol='BTC';self.send(symbol,1,1);self.send(symbol,1,1,100.1)
        app.local4_fast_entries({symbol:100.1})
        self.assertIn(symbol,app.S['local_v12_positions'])
        self.send(symbol,1,20,101)
        flow=self.obs.flow_context(symbol)
        anchor=app.S['_local4_analysis'][symbol]
        before=app.S['local_experiment_equity']
        self.assertTrue(app.WIN.pyramid(symbol,anchor,flow,101))
        self.assertFalse(app.WIN.pyramid(symbol,anchor,flow,101))
        app.restore_state()
        restored=PandoraRuntime(app)
        p=app.S['local_v12_positions'][symbol]
        self.assertEqual(p['features']['pyramid_level'],1)
        self.assertEqual(len(p['features']['pyramid_adds']),1)
        self.assertEqual(app.S['local_experiment_equity'],before)
        with self.connect() as db:
            self.assertEqual(db.execute('select count(*) n from pandora_pyramid_adds').fetchone()['n'],1)
            self.assertEqual(db.execute("select count(*) n from audit_journal where kind='pandora_ADD_LONG'").fetchone()['n'],1)
        self.assertFalse(restored.pyramid(symbol,anchor,flow,101))
        self.assertIsNotNone(app.local_experiment_close(symbol,101,'operator_paper_close'))
        self.assertIsNone(app.local_experiment_close(symbol,101,'operator_paper_close'))

    def test_runtime_holds_bounce_then_closes_and_reverses_only_with_new_structure(self):
        symbol='BTC'
        self.send(symbol,1,1,100)
        self.send(symbol,1,1,100.1)
        app.WIN.cycle({symbol:100.1})
        self.assertEqual(app.S['local_v12_positions'][symbol]['side'],1)
        self.send(symbol,-1,.01,100.05)
        app.WIN.cycle({symbol:100.05})
        self.assertIn(symbol,app.S['local_v12_positions'])
        self.send(symbol,1,3,100.2)
        app.WIN.cycle({symbol:100.2})
        self.send(symbol,-1,90,99)
        app.WIN.cycle({symbol:99})
        self.assertNotIn(symbol,app.S['local_v12_positions'])
        self.assertIn(symbol,app.S['local_experiment_watch'])
        old=copy.deepcopy(app.S['_local4_analysis'][symbol])
        # Feed a new confirmed structure through the executor boundary. Local
        # causality itself is exercised separately against actual H1/M15 bars.
        opposite={**old,'entry_side':-1,'pivot_type':'LOCAL_HIGH','pivot_price':101,
                  'signal_candle_time':old['signal_candle_time']+1,
                  'pivot_candle_time':old['pivot_candle_time']+1}
        app.S['_local4_analysis'][symbol]=opposite
        app.S['local_h1_direction'][symbol]=opposite
        app.S['_local_h1_runtime_verified'][symbol].update(
            entry_side=-1,signal_candle_time=opposite['signal_candle_time'],
            pivot_candle_time=opposite['pivot_candle_time'])
        with self.connect() as db:
            db.execute('update local_h1_direction set analysis=%s::jsonb where symbol=%s',
                       (json.dumps(opposite),symbol))
        app.WIN.cycle({symbol:99})
        self.assertEqual(app.S['local_v12_positions'][symbol]['side'],-1)
        with self.connect() as db:
            self.assertEqual(db.execute("select count(*) n from audit_journal where kind='pandora_REVERSE_LONG_TO_SHORT'").fetchone()['n'],1)
            self.assertEqual(db.execute('select count(*) n from local_v12_trade_history').fetchone()['n'],1)
        app.WIN.cycle({symbol:99})
        with self.connect() as db:
            self.assertEqual(db.execute("select count(*) n from audit_journal where kind='pandora_REVERSE_LONG_TO_SHORT'").fetchone()['n'],1)
