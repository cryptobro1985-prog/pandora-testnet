"""Observable H1/M15 selection and allocation order, without exchange orders."""
import copy
import unittest
from unittest.mock import MagicMock, patch

import app
from local_caterpillar import entry_candidate, rank_candidates


def evidence(side=1, stamp=1000., score=4, imbalance=.5, notional=1000.):
    return (
        dict(ready=True, h1_direction_anchor=True, entry_side=side, signal_candle_time=1),
        dict(ready=True, side=side, observed_at_ms=stamp*1000, recovery_confirmed=True,
             recovery_score=score, adverse_score=0, strong_adverse_pressure=False),
        dict(trade_data_fresh=True, latest_trade_age_seconds=1, trade_coverage_seconds=120,
             flow_imbalance=side*imbalance, trade_count_60s=10, observed_notional_60s=notional),
    )


class CandidateTests(unittest.TestCase):
    def test_short_and_long_are_symmetric(self):
        for side in (-1, 1):
            candidate=entry_candidate('HYPE', *evidence(side), 1000.)
            self.assertTrue(candidate['eligible'])
            self.assertEqual(candidate['side'],side)
            self.assertEqual(candidate['aligned_flow'],.5)

    def test_invalid_or_missing_flow_never_qualifies(self):
        changes=[dict(flow_imbalance=float('nan')),dict(flow_imbalance=1.1),
                 dict(flow_imbalance=-.5),dict(latest_trade_age_seconds=16),
                 dict(latest_trade_age_seconds=None),dict(trade_coverage_seconds=59),
                 dict(trade_count_60s=None),dict(trade_count_60s=4),
                 dict(observed_notional_60s=float('inf')),dict(observed_notional_60s=None),
                 dict(observed_notional_60s=99),dict(trade_data_fresh=False)]
        for change in changes:
            with self.subTest(change=change):
                a,m,f=evidence();f.update(change)
                self.assertFalse(entry_candidate('HYPE',a,m,f,1000.)['eligible'])

    def test_wrong_side_unconfirmed_or_stale_m15_cannot_enter(self):
        for change in (dict(side=-1),dict(ready=False),dict(recovery_confirmed=False),
                       dict(recovery_score=2),dict(strong_adverse_pressure=True),
                       dict(observed_at_ms=989000),dict(observed_at_ms=1000001)):
            with self.subTest(change=change):
                a,m,f=evidence();m.update(change)
                self.assertFalse(entry_candidate('HYPE',a,m,f,1000.)['eligible'])

    def test_h1_pending_extreme_blocks_both_directions(self):
        for side in (-1,1):
            a,m,f=evidence(side);a['entry_blocked']=True
            self.assertFalse(entry_candidate('HYPE',a,m,f,1000.)['eligible'])

    def test_selection_is_independent_of_symbol_order(self):
        weak=entry_candidate('HYPE',*evidence(score=3),1000.)
        strong=entry_candidate('TAO',*evidence(score=5),1000.)
        for rows in ([weak,strong],[strong,weak]):
            self.assertEqual([c['symbol'] for c in rank_candidates(rows)],['TAO','HYPE'])
        stronger_flow=entry_candidate('NEAR',*evidence(score=5,imbalance=.8),1000.)
        self.assertEqual(rank_candidates([strong,stronger_flow])[0]['symbol'],'NEAR')


class AllocationTests(unittest.TestCase):
    def setUp(self):
        self.saved=copy.deepcopy(app.S)
        app.S.update(engine_active=True,mode='PAPER_ONLY',orders_enabled=False,
                     local_v12_positions={},local_experiment_watch={},local_h1_direction={},
                     local_experiment_equity=500.,sources={})

    def tearDown(self):
        app.S.clear();app.S.update(self.saved)

    def test_flow_must_still_be_aligned_at_position_mutation(self):
        a,m,f=evidence(stamp=app.time.time());f['flow_imbalance']=-.7
        with patch.object(app.MARKET_OBS,'context',return_value=f),patch.object(app,'pg') as db:
            self.assertFalse(app.local_experiment_open('HYPE',1,a,m15=m))
        db.assert_not_called()

    def test_newer_persisted_h1_anchor_rejects_old_ranked_candidate(self):
        a,m,f=evidence(stamp=app.time.time())
        app.S['local_h1_direction']={'HYPE':dict(entry_side=-1,signal_candle_time=2)}
        with patch.object(app.MARKET_OBS,'context',return_value=f),patch.object(app,'pg') as db:
            self.assertFalse(app.local_experiment_open('HYPE',1,a,m15=m))
        db.assert_not_called()

    def test_scan_allocates_best_candidate_before_first_configured_symbol(self):
        stop=MagicMock();stop.is_set.side_effect=[False,True]
        stamp=app.time.time();a,_,f=evidence(stamp=stamp)
        def m15(rows,observed,side):
            return evidence(side,stamp,score=rows[0])[1]
        def candles(symbol):
            return ([3 if symbol=='HYPE' else 5],int(stamp*1000))
        with patch.object(app,'SHUTDOWN',stop),patch.object(app,'LOCAL_EXPERIMENT_SYMBOLS',('HYPE','TAO')), \
             patch.object(app,'refresh_market_prices',return_value={'HYPE':100.,'TAO':100.}), \
             patch.object(app,'local_experiment_mark_positions'),patch.object(app,'_local_h1_candles',return_value=([],int(stamp*1000))), \
             patch.object(app,'_local_m15_candles',side_effect=candles),patch.object(app,'local_h1_direction',return_value=a), \
             patch.object(app,'analyze_local_h1_context',return_value={}),patch.object(app,'analyze_local_m15',side_effect=m15), \
             patch.object(app.MARKET_OBS,'context',return_value=f),patch.object(app,'_local_experiment_claim'), \
             patch.object(app,'local_experiment_stats',return_value={}),patch.object(app,'local_experiment_open',return_value=True) as opening:
            app.local_experiment_loop()
        self.assertEqual([c.args[0] for c in opening.call_args_list],['TAO','HYPE'])
        self.assertEqual(app.S['sources']['Local12TokenH1M15']['ranked_candidates'],['TAO','HYPE'])

    def test_risk_worker_runs_without_metadata_or_candle_requests(self):
        app.S.update(_last_poll_epoch=app.time.time(),_prices={'HYPE':101.},_day_volumes={},_max_leverage={})
        stop=MagicMock();stop.is_set.side_effect=[False,True]
        with patch.object(app,'SHUTDOWN',stop),patch.object(app,'local_experiment_mark_positions') as protect, \
             patch.object(app,'_local_h1_candles') as candles:
            app.local_experiment_risk_loop()
        protect.assert_called_once_with({'HYPE':101.})
        candles.assert_not_called()

    def test_risk_worker_never_uses_stale_or_future_marks(self):
        for offset in (-20,20):
            app.S.update(_last_poll_epoch=app.time.time()+offset,_prices={'HYPE':101.})
            stop=MagicMock();stop.is_set.side_effect=[False,True]
            with patch.object(app,'SHUTDOWN',stop),patch.object(app,'local_experiment_mark_positions') as protect:
                app.local_experiment_risk_loop()
            protect.assert_not_called()

    def test_newly_armed_floor_is_persisted_before_periodic_checkpoint(self):
        for side in (-1,1):
            stamp=app.time.time()
            app.S['local_v12_positions']={'HYPE':dict(side=side,entry=100.,notional=250.,margin=10.,leverage=25.,opened='fixture',
                features=dict(caterpillar_policy=app.CATERPILLAR_POLICY,estimated_round_trip_cost_move=.0013))}
            app.S['_local_experiment_path_persist_epoch']={'HYPE':stamp}
            with patch.object(app,'pg') as pg,patch.object(app.STORE,'fence'):
                app.local_experiment_mark_positions({'HYPE':100.+side*.3})
            db=pg.return_value.__enter__.return_value
            self.assertTrue(db.execute.called)
            self.assertTrue(app.S['local_v12_positions']['HYPE']['features']['profit_lock_armed'])

    def test_failed_floor_checkpoint_is_retried_on_next_observation(self):
        app.S['local_v12_positions']={'HYPE':dict(side=1,entry=100.,notional=250.,margin=10.,leverage=25.,opened='fixture',
            features=dict(caterpillar_policy=app.CATERPILLAR_POLICY,estimated_round_trip_cost_move=.0013))}
        app.S['_local_experiment_path_persist_epoch']={'HYPE':app.time.time()}
        with patch.object(app,'pg') as pg,patch.object(app.STORE,'fence'):
            db=pg.return_value.__enter__.return_value
            db.execute.side_effect=[RuntimeError('checkpoint unavailable'),None]
            with self.assertRaises(RuntimeError):
                app.local_experiment_mark_positions({'HYPE':100.3})
            app.local_experiment_mark_positions({'HYPE':100.3})
        self.assertEqual(db.execute.call_count,2)

    def test_monitor_displays_candidate_rank_and_observable_evidence(self):
        with patch.object(app,'pg',side_effect=RuntimeError('offline')):
            d=app.dashboard()
        d['local_experiment_engine']={'details':{'HYPE':dict(last_action='M15_ENTRY',candidate_selection=dict(rank=1,recovery_score=5,aligned_flow=.7))}}
        self.assertIn('rank 1 · M15 5 · aligned flow 0.70',app.html_dashboard(d))


if __name__=='__main__':
    unittest.main()
