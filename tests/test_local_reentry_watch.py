import copy
import unittest
from unittest.mock import MagicMock, patch
import app


class LocalReentryWatchTests(unittest.TestCase):
    def setUp(self):
        self.saved=copy.deepcopy(app.S)
        app.S.update(engine_active=True,local_swing_positions={},local_swing_watch={},sources={},trades=0)

    def tearDown(self):
        app.S.clear();app.S.update(self.saved)

    def test_protective_exits_persist_watch_for_both_assets_and_directions(self):
        for symbol,side in [('HYPE',1),('NEAR',-1)]:
            for reason in ('profit_lock_stop','m15_adverse_pressure_profit_protect','m15_momentum_weakening'):
                with self.subTest(symbol=symbol,side=side,reason=reason):
                    pos=dict(opened='test',entry=100.,side=side,notional=250.,margin=10.,leverage=25.,
                             features=dict(origin_m15_signal_candle=123,swing_reentries=1))
                    app.S['local_swing_positions']={symbol:pos}
                    db=MagicMock()
                    db.execute.return_value.fetchone.return_value=dict(symbol=symbol,equity=100.,realized_pnl=0.)
                    pg=MagicMock();pg.return_value.__enter__.return_value=db
                    with patch.object(app,'pg',pg),patch.object(app.STORE,'fence'):
                        result=app.local_swing_close(symbol,100.2,reason)
                    self.assertTrue(result['watch_armed'])
                    watch=app.S['local_swing_watch'][symbol]
                    self.assertEqual((watch['side'],watch['origin_signal_candle'],watch['reentries']),(side,123,1))
                    self.assertTrue(any('insert into local_swing_watchlist' in c.args[0] for c in db.execute.call_args_list))

    def run_scan(self,candle,opened):
        watch=dict(side=1,origin_signal_candle=123,expires_epoch=app.time.time()+1000,reentries=0)
        app.S['local_swing_watch']={'HYPE':watch}
        stop=MagicMock();stop.is_set.side_effect=[False,True]
        analysis=dict(ready=True,entry_side=1,signal_candle_time=candle)
        with patch.object(app,'SHUTDOWN',stop),patch.object(app,'LOCAL_SWING_SYMBOLS',('HYPE',)), \
             patch.object(app,'refresh_market_prices',return_value={'HYPE':100.}), \
             patch.object(app,'_local_h1_candles',return_value=([],0)), \
             patch.object(app,'_local_m15_candles',return_value=([],0)), \
             patch.object(app,'analyze_hype_h1',return_value=analysis), \
             patch.object(app,'analyze_local_h1_context',return_value={}), \
             patch.object(app,'analyze_local_m15',return_value={'ready':True,'recovery_confirmed':True,'recovery_score':4}), \
             patch.object(app,'_local_claim'),patch.object(app,'_local_update_shadows'), \
             patch.object(app.MARKET_OBS,'context',return_value={'flow_imbalance':.5}), \
             patch.object(app,'local_swing_open',return_value=opened) as enter, \
             patch.object(app,'_local_watch_clear') as clear:
            app.hype_h1_local_swing_loop()
        self.assertTrue(app.S['sources']['HypeH1LocalSwing']['ok'])
        return enter,clear

    def test_existing_pivot_does_not_swallow_recovery_reentry(self):
        enter,clear=self.run_scan(123,True)
        self.assertEqual(enter.call_args.args[3],'REENTRY')
        clear.assert_not_called()

    def test_failed_new_pivot_entry_keeps_watch_for_retry(self):
        enter,clear=self.run_scan(124,False)
        self.assertEqual(enter.call_args.args[3],'M15')
        clear.assert_not_called()
        self.assertIn('HYPE',app.S['local_swing_watch'])

    def test_successful_new_pivot_consumes_watch(self):
        enter,clear=self.run_scan(124,True)
        clear.assert_called_once_with('HYPE','new_same_side_m15_pivot')
