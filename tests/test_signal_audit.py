"""Audit regressions for observed evidence, freshness and safe signal gates."""
import unittest

from local_order_flow import initial_entry_candidate, flow_profile, pressure_exit
from market_data import RollingMarketData
from pandora_flow import summarize
from pandora_locals import live_locals, execution_anchor
from pandora_scanner import LiveScanner
from tests.test_pandora_restoration import bars, BASE, H


class SignalEvidenceTests(unittest.TestCase):
    @staticmethod
    def takeover(side=1, single=False, warmed=True):
        first=1000 if warmed else 1018
        rows=[(first,100+side*10,100000,'B' if side>0 else 'A')]
        epochs=[1020] if single else list(range(1006 if warmed else 1019,1021,2 if warmed else 1))
        rows.extend((stamp,100+side*(9-index),1000,'A' if side>0 else 'B') for index,stamp in enumerate(epochs))
        flow=summarize(rows,1020,1020-first)
        flow.update(trade_data_fresh=True,latest_trade_age_seconds=0,
                    latest_trade_epoch=1020,decision_event_epoch=1020,
                    buy_notional=flow['windows']['60']['buy_volume'],
                    sell_notional=flow['windows']['60']['sell_volume'],price_direction=-side)
        return flow,rows[-1][1]

    def test_fast_structural_exit_is_not_vetoed_by_old_minute_volume(self):
        for side in (-1,1):
            with self.subTest(side=side):
                flow,mark=self.takeover(side)
                self.assertEqual(flow['context_control_side'],side)
                self.assertEqual(flow['fast_control_side'],-side)
                self.assertEqual(flow['sustained_control_side'],0)
                position=dict(side=side,entry=100,features={'pressure_state':dict(
                    best=side*(100+side*10),noise=.1,barrier=side*(100+side*9),phase='HOLDING')})
                self.assertIsNone(pressure_exit(position,None,mark,flow))
                later={**flow,'latest_trade_epoch':1023,'decision_event_epoch':1023}
                self.assertEqual(pressure_exit(position,None,mark,later),'confirmed_counter_move_exit')
                analysis=dict(ready=True,anchor_confirmed=True,h1_direction_anchor=True,entry_side=-side)
                self.assertFalse(initial_entry_candidate('BTC',analysis,None,flow,1020)['eligible'])

    def test_single_counter_print_cannot_establish_fast_exit_control(self):
        for kwargs in ({'single':True},{'warmed':False}):
            flow,mark=self.takeover(**kwargs)
            self.assertEqual(flow['fast_control_side'],0)
            position=dict(side=1,entry=100,features={'pressure_state':dict(best=110,noise=.1,barrier=109)})
            self.assertIsNone(pressure_exit(position,None,mark,flow))

    def test_identical_bootstrap_prints_do_not_establish_sustained_control(self):
        flow=summarize([(1000,100,100,'B'),(1001,101,200,'B')],1001,600)
        self.assertFalse(flow['evidence_ready'])
        self.assertEqual(flow['sustained_control_side'],0)
        self.assertFalse(flow['windows']['15']['complete'])

    def test_socket_uptime_does_not_replace_actual_tape_coverage(self):
        obs=RollingMarketData();obs.mark_connected(1000,['BTC'],owner='test')
        for epoch,price in ((1030,100),(1031,101)):
            obs.ingest_trades([dict(coin='BTC',px=price,sz=1,time=epoch*1000,side='B',tid=str(epoch))],epoch,owner='test')
        flow=obs.flow_context('BTC',1031)
        self.assertEqual(flow['trade_coverage_seconds'],1)
        self.assertEqual(flow['sustained_control_side'],0)

    def test_rich_flow_cannot_enter_from_one_tick_against_short_window_control(self):
        flow=dict(trade_data_fresh=True,latest_trade_age_seconds=.1,buy_notional=1000,
                  sell_notional=500,price_direction=1,windows={},sustained_control_side=-1)
        analysis=dict(ready=True,anchor_confirmed=True,h1_direction_anchor=True,entry_side=1)
        self.assertFalse(initial_entry_candidate('BTC',analysis,None,flow,1000)['eligible'])
        self.assertFalse(flow_profile(flow,1)['aligned_control'])

    def test_warmed_consistent_volume_and_price_response_allow_control(self):
        rows=[(1000,100,1,'B'),(1015,101,100,'B'),(1016,102,200,'B')]
        flow=summarize(rows,1016,16)
        self.assertTrue(flow['evidence_ready'])
        self.assertEqual(flow['sustained_control_side'],1)

    def test_stopped_buying_cannot_open_long_from_old_minute_majority(self):
        obs=RollingMarketData(freshness_seconds=15)
        obs.mark_connected(1000,['BTC'],owner='test')
        for epoch,price in ((1001,100),(1015,101)):
            obs.ingest_trades([dict(coin='BTC',px=price,sz=10,time=epoch*1000,side='B',tid=str(epoch))],epoch,owner='test')
        obs.heartbeat(1021,owner='test')
        flow=obs.flow_context('BTC',1021)
        self.assertTrue(flow['trade_data_fresh'])
        self.assertGreater(flow['buy_notional'],flow['sell_notional'])
        self.assertEqual(flow['windows']['5']['trade_count'],0)
        analysis=dict(ready=True,anchor_confirmed=True,h1_direction_anchor=True,entry_side=1)
        self.assertFalse(initial_entry_candidate('BTC',analysis,None,flow,1021)['eligible'])

    def test_window_expiration_resets_observed_dominance_duration(self):
        rows=[(1000,100,100,'B'),(1001,100,100,'A'),(1002,100,100,'B')]
        flow=summarize(rows,1062,62)
        self.assertEqual(flow['dominance_side'],1)
        self.assertAlmostEqual(flow['dominance_duration'],.999999,places=5)

    def test_owner_cannot_inject_trade_into_another_shard(self):
        obs=RollingMarketData();obs.mark_connected(1000,['BTC'],owner='btc')
        obs.mark_connected(1000,['SOL'],owner='sol')
        row=dict(coin='SOL',px=100,sz=1,time=1001000,side='B',tid='wrong-shard')
        self.assertEqual(obs.ingest_trades([row],1001,owner='btc'),0)
        self.assertFalse(obs.flow_context('SOL',1001)['trade_data_fresh'])

    def test_expired_old_price_level_cannot_prove_current_price_response(self):
        obs=RollingMarketData(freshness_seconds=120);obs.mark_connected(1000,['BTC'],owner='test')
        for epoch,price in ((1001,90),(1002,100),(1070,100)):
            obs.ingest_trades([dict(coin='BTC',px=price,sz=1,time=epoch*1000,side='B',tid=str(epoch))],epoch,owner='test')
        self.assertEqual(obs.flow_context('BTC',1070)['price_direction'],0)


class LocalFreshnessTests(unittest.TestCase):
    def test_stale_observed_forming_low_remains_blocked_and_cannot_promote(self):
        history=bars()[:9];now=BASE+9*H+30_000
        partial=dict(t=BASE+9*H,T=BASE+10*H-1,o=107,h=108,l=90,c=91,v=50,observed_at_ms=now)
        current=live_locals(history+[partial],[],now,'BTC')
        self.assertTrue(current['entry_blocked'])
        stale=live_locals(history+[partial],[],now+16_000,'BTC')
        self.assertFalse(stale['live_structure_fresh'])
        self.assertTrue(stale['entry_blocked'])
        self.assertEqual(stale['forming_local']['pivot_price'],90)
        promoted=execution_anchor(stale,dict(trade_data_fresh=True,sustained_control_side=1))
        self.assertTrue(promoted['entry_blocked'])


class ScannerObservationTests(unittest.TestCase):
    @staticmethod
    def tape(velocity=100,side=1,quiet=False):
        buy=0 if side<0 or quiet else velocity
        sell=0 if side>0 or quiet else velocity
        window=dict(buy_volume=buy,sell_volume=sell,volume_velocity=0 if quiet else velocity,
                    trade_count=0 if quiet else 10,trade_velocity=0 if quiet else 2,volume_change=0)
        return dict(trade_data_fresh=True,latest_trade_epoch=1020,windows={str(n):dict(window) for n in (5,15,60)})

    def test_individual_stale_price_does_not_freeze_other_observations_or_rotate(self):
        from tests.test_incident_scanner import warm,ticker,tape
        scanner=LiveScanner(top=1);warm(scanner)
        ticker(scanner,'NEW',1036,102)
        current=scanner.rank({'OLD':{},'NEW':{}},lambda *args:tape(),held=['OLD'],epoch=1036)
        self.assertFalse(current['selection_frozen'])
        self.assertEqual(current['selected_symbols'],['OLD'])
        self.assertIn('NEW',current['candidate_symbols'])

    def test_short_quiet_interval_cannot_evict_held_market(self):
        from tests.test_incident_scanner import warm,ticker,tape
        scanner=LiveScanner(top=1);warm(scanner)
        for epoch in (1020,1036):
            ticker(scanner,'OLD',epoch,111);ticker(scanner,'NEW',epoch,100+(epoch-1020))
            current=scanner.rank({'OLD':{},'NEW':{}},lambda s,*args:tape(0,0) if s=='OLD' else tape(),held=['OLD'],epoch=epoch)
        self.assertEqual(current['selected_symbols'],['OLD'])
        self.assertFalse(current['events'])

    def test_high_participation_correction_remains_eligible_for_short(self):
        from tests.test_incident_scanner import ticker
        scanner=LiveScanner(top=1);instruments={'BTC':{}}
        for epoch,price in ((1000,100),(1010,105),(1020,110)):
            ticker(scanner,'BTC',epoch,price)
            scanner.rank(instruments,lambda *args:self.tape(),epoch=epoch)
        ticker(scanner,'BTC',1030,109)
        ticker(scanner,'BTC',1040,108)
        current=scanner.rank(instruments,lambda *args:self.tape(1000,side=-1),epoch=1040)
        self.assertEqual(current['selected_symbols'],['BTC'])
        self.assertTrue(current['selected'][0]['active_correction'])
        self.assertFalse(current['selected'][0]['fading'])

    def test_metadata_outage_preserves_selection_without_rotation_events(self):
        scanner=LiveScanner();snapshot=dict(selected_symbols=['BTC'],selected=[{'symbol':'BTC'}],candidate_symbols=['BTC'])
        scanner.restore(snapshot)
        frozen=scanner.rank({},lambda *args:{},held=['BTC'],epoch=1000)
        self.assertEqual(frozen['selected_symbols'],['BTC'])
        self.assertTrue(frozen['selection_frozen'])
        self.assertFalse(frozen['observations_ready'])
        self.assertEqual(frozen['events'],[])

    def test_non_price_delta_cannot_refresh_a_stale_price_for_selection(self):
        scanner=LiveScanner()
        scanner.ingest(dict(symbol='BTCUSDT',lastPrice=100,turnover24h=1000,price24hPcnt=.1),1000000,1000)
        scanner.rank({'BTC':{}},lambda *args:{},epoch=1000)
        scanner.ingest(dict(symbol='BTCUSDT',fundingRate='.01'),1020000,1020)
        snapshot=scanner.rank({'BTC':{}},lambda *args:{},epoch=1020)
        self.assertTrue(snapshot['selection_frozen'])
        self.assertFalse(snapshot['observations_ready'])

    def test_invalid_metric_cannot_poison_ranking_or_previous_snapshot(self):
        scanner=LiveScanner()
        self.assertFalse(scanner.ingest(dict(symbol='BTCUSDT',lastPrice=100,turnover24h=1000,price24hPcnt='nan'),1000000,1000))
        self.assertEqual(scanner.rank({'BTC':{}},lambda *args:{},epoch=1000)['selected_symbols'],[])


class ScannerContinuityTests(unittest.TestCase):
    def test_small_activity_decrease_does_not_churn_an_actively_controlled_market(self):
        scanner=LiveScanner(top=1)
        def tape(velocity):
            window=dict(buy_volume=velocity,sell_volume=0,volume_velocity=velocity,
                        trade_count=10,trade_velocity=2,volume_change=0)
            return dict(trade_data_fresh=True,latest_trade_epoch=1021,fast_control_side=1,
                        sustained_control_side=1,windows={str(n):dict(window) for n in (5,15,60)})
        from tests.test_incident_scanner import warm,ticker
        warm(scanner,('BTC',))
        ticker(scanner,'BTC',1020,112)
        scanner.rank({'BTC':{}},lambda *a:tape(100),epoch=1020)
        ticker(scanner,'BTC',1021,112)
        result=scanner.rank({'BTC':{}},lambda *a:tape(99),epoch=1021)
        self.assertEqual(result['selected_symbols'],['BTC'])
        self.assertFalse(result['selected'][0]['fading'])
        self.assertEqual(result['events'],[])
