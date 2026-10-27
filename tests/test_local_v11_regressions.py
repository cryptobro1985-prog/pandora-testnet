import copy
import json
import unittest
from unittest.mock import MagicMock, patch
import app
from hype_h1_swing import analyze
from hyperliquid_transport import RestBudget
from tests.test_h1_direction_m15_execution import history, H


class LocalV11Regressions(unittest.TestCase):
    def setUp(self):
        self.saved=copy.deepcopy(app.S)
        app.S.update(engine_active=True,mode='PAPER_ONLY',orders_enabled=False,
            _day_volumes={'HYPE':1},_max_leverage={'HYPE':10},_prices={'HYPE':99.},
            local_v12_positions={},local_experiment_watch={},local_experiment_equity=500.,sources={})

    def tearDown(self):
        app.S.clear();app.S.update(self.saved)

    def pending_rows(self, side):
        rows=history(side)
        # A new opposite extreme has closed; the following H1 bar is still live.
        values=[(95,104,94,102),(102,110,101,108),(108,109,100,102)]
        if side<0:values=[(200-o,200-l,200-h,200-c) for o,h,l,c in values]
        for i,(o,h,l,c) in enumerate(values,6):rows.append(dict(t=i*H,T=(i+1)*H-1,o=o,h=h,l=l,c=c,v=100))
        return rows

    def test_possible_high_pauses_longs_but_never_confirms_short_early(self):
        for side in (-1,1):
            rows=self.pending_rows(side)
            r=analyze(rows,8*H+H//2)
            self.assertEqual(r['entry_side'],side)
            self.assertTrue(r['entry_blocked'])
            self.assertEqual(r['pending_pivot_type'],'LOCAL_HIGH' if side>0 else 'LOCAL_LOW')
            confirmed=analyze(rows,9*H+1001)
            self.assertEqual(confirmed['entry_side'],-side)
            self.assertFalse(confirmed['entry_blocked'])

    def test_provisional_extreme_is_cancelled_by_new_price_extreme(self):
        for side in (-1,1):
            rows=self.pending_rows(side)
            rows[-1].update(h=111 if side>0 else 101,l=100 if side>0 else 89,c=110 if side>0 else 90)
            self.assertFalse(analyze(rows,8*H+H//2)['entry_blocked'])

    def test_entry_mutation_rejects_provisional_opposite_extreme(self):
        for side in (-1,1):
            r=dict(ready=True,h1_direction_anchor=True,entry_side=side,entry_blocked=True)
            with patch.object(app,'current_entry_price') as price:
                self.assertFalse(app.local_experiment_open('HYPE',side,r))
            price.assert_not_called()

    def test_shorter_history_cannot_replace_newer_persisted_anchor(self):
        prior=dict(ready=True,h1_direction_anchor=True,entry_side=-1,signal_candle_time=9*H,pivot_type='LOCAL_HIGH')
        old=dict(ready=True,anchor_confirmed=True,h1_direction_anchor=True,entry_side=1,signal_candle_time=5*H,last_candle_time=10*H)
        app.S['local_h1_direction']={'HYPE':prior}
        with patch.object(app,'analyze_hype_h1',return_value=old),patch.object(app,'pg') as db:
            r=app.local_h1_direction([],11*H,'HYPE')
        self.assertEqual((r['entry_side'],r['signal_candle_time']),(-1,9*H))
        db.assert_not_called()

    def test_actual_m15_exit_reason_arms_persistent_reentry_watch(self):
        for side in (-1,1):
            app.S['local_experiment_watch']={}
            app.S['local_v12_positions']={'HYPE':dict(opened='fixture',entry=100.,side=side,notional=250.,margin=10.,leverage=25.,signal_candle_time=123,features={})}
            db=MagicMock();db.execute.return_value.fetchone.return_value=dict(symbol='HYPE',equity=501.,realized_pnl=1.)
            pg=MagicMock();pg.return_value.__enter__.return_value=db
            with patch.object(app,'pg',pg),patch.object(app.STORE,'fence'),patch.object(app,'log_learning_decision'):
                app.local_experiment_close('HYPE',100.+side*.3,'m15_pressure_reversal_profit_only')
            watch=app.S['local_experiment_watch']['HYPE']
            self.assertEqual(watch['side'],side)
            self.assertEqual(watch['context']['phase'],'WAIT_PULLBACK')
            self.assertTrue(watch['context']['counter_pressure_seen'])
            self.assertTrue(any('insert into local_v12_watchlist' in c.args[0] for c in db.execute.call_args_list))

    def test_opposite_h1_closes_losing_position_even_if_m15_is_unavailable(self):
        app.S['local_v12_positions']={'HYPE':dict(opened='fixture',entry=100.,side=1,notional=250.,margin=10.,leverage=25.,signal_candle_time=1,features={})}
        stop=MagicMock();stop.is_set.side_effect=[False,True]
        analysis=dict(ready=True,h1_direction_anchor=True,entry_side=-1,signal_candle_time=2,pivot_type='LOCAL_HIGH')
        with patch.object(app,'SHUTDOWN',stop),patch.object(app,'LOCAL_EXPERIMENT_SYMBOLS',('HYPE',)), \
             patch.object(app,'refresh_market_prices',return_value={'HYPE':99.}), \
             patch.object(app,'local_experiment_mark_positions'),patch.object(app,'_local_h1_candles',return_value=([],0)), \
             patch.object(app,'_local_m15_candles',side_effect=RuntimeError('local_swing_history_bootstrap_pending')), \
             patch.object(app,'local_h1_direction',return_value=analysis),patch.object(app,'analyze_local_h1_context',return_value={}), \
             patch.object(app,'_local_experiment_claim'),patch.object(app,'local_experiment_stats',return_value={}), \
             patch.object(app,'local_experiment_close',return_value={'pnl':-3.}) as close:
            app.local_experiment_loop()
        close.assert_called_once_with('HYPE',99.,'opposite_local_high',analysis)
        self.assertFalse(app.S['sources']['Local12TokenH1M15']['ready'])

    def test_low_budget_still_allows_regime_history_recovery(self):
        for limit in (120,125,150):
            budget=RestBudget(limit=limit,clock=lambda:0)
            budget.acquire({'type':'candleSnapshot','req':{'interval':'1m','startTime':0,'endTime':6*3600000}})
            self.assertEqual(budget.status()['sent'],1)

    def test_monitor_shows_confirmed_direction_separately_from_position(self):
        with patch.object(app,'pg',side_effect=RuntimeError('offline')):
            d=app.dashboard()
            d['local_experiment_engine']={'details':{'HYPE':{'h1_local':{'pivot_type':'LOCAL_HIGH','entry_side':-1,'pivot_price':79.439,'signal_candle_time':1793109600000},'last_action':'WAIT_ENTRY'}}}
            page=app.html_dashboard(d)
        self.assertIn('SHORT ONLY',page)
        self.assertIn('LOCAL_HIGH @ 79.439',page)
        self.assertIn('confirmation time Samara UTC+4',page)

    def test_websocket_starts_for_known_local_symbols_during_metadata_429(self):
        app.S.update(_day_volumes={},_max_leverage={})
        stop=MagicMock();stop.is_set.return_value=False
        with patch.object(app,'SHUTDOWN',stop),patch.object(app,'run_trade_stream') as stream:
            app.market_trade_stream()
        stream.assert_called_once()
        subscribed=stream.call_args.args[2]()
        self.assertTrue(set(app.LOCAL_EXPERIMENT_SYMBOLS).issubset(subscribed))
        stop.wait.assert_not_called()

    def test_local_position_protection_does_not_wait_for_metadata(self):
        app.S.update(_day_volumes={},_max_leverage={})
        stop=MagicMock();stop.is_set.side_effect=[False,True]
        with patch.object(app,'SHUTDOWN',stop),patch.object(app,'LOCAL_EXPERIMENT_SYMBOLS',()), \
             patch.object(app,'refresh_market_prices',return_value={'HYPE':99.}), \
             patch.object(app,'local_experiment_mark_positions') as marks, \
             patch.object(app,'local_experiment_stats',return_value={}):
            app.local_experiment_loop()
        marks.assert_called_once_with({'HYPE':99.})

    def test_durable_history_is_checkpointed_once_per_closed_bar(self):
        from tests.test_hyperliquid_transport import CandleTests
        cache=copy.deepcopy(app._LOCAL_CANDLE_CACHE);seen=dict(app._LOCAL_CANDLE_CHECKPOINTED)
        try:
            app._LOCAL_CANDLE_CACHE.clear();app._LOCAL_CANDLE_CHECKPOINTED.clear()
            rows=CandleTests().rows()
            app.accept_local_candles(rows,history=True)
            db=MagicMock();pg=MagicMock();pg.return_value.__enter__.return_value=db
            with patch.object(app,'pg',pg),patch.object(app.STORE,'fence'):
                app.checkpoint_local_candles()
                app.checkpoint_local_candles()
            writes=[c for c in db.execute.call_args_list if 'insert into local_candle_checkpoints' in c.args[0]]
            self.assertEqual(len(writes),1)
            stored=json.loads(writes[0].args[1][2])
            self.assertEqual(len(stored),12)
            app._LOCAL_CANDLE_CACHE.clear()
            app.accept_local_candles(stored,history=True)
            with patch.object(app,'get') as net:
                restored,_=app._local_m15_candles('HYPE')
            net.assert_not_called()
            self.assertEqual(len(restored),12)
        finally:
            app._LOCAL_CANDLE_CACHE.clear();app._LOCAL_CANDLE_CACHE.update(cache)
            app._LOCAL_CANDLE_CHECKPOINTED.clear();app._LOCAL_CANDLE_CHECKPOINTED.update(seen)

    def test_h1_high_is_confirmed_by_lower_high_even_on_green_confirmation(self):
        rows=self.pending_rows(1)
        rows[-1].update(o=108,h=109,l=107,c=108.5)
        r=analyze(rows,9*H+1001)
        self.assertEqual((r['entry_side'],r['pivot_type']),(-1,'LOCAL_HIGH'))

    def test_h1_low_is_confirmed_by_higher_low_even_on_red_confirmation(self):
        rows=self.pending_rows(-1)
        rows[-1].update(o=92,h=93,l=91,c=91.5)
        r=analyze(rows,9*H+1001)
        self.assertEqual((r['entry_side'],r['pivot_type']),(1,'LOCAL_LOW'))
