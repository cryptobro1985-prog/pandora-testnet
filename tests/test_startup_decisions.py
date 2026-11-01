import copy
import unittest

from pandora_decisions import entry_status, startup_snapshot


class StartupDecisionTests(unittest.TestCase):
    def setUp(self):
        self.analysis=dict(ready=True,anchor_confirmed=True,h1_direction_anchor=True,
                           pivot_type='LOCAL_LOW',pivot_price=99,entry_side=1)
        self.flow=dict(trade_data_fresh=True,evidence_ready=True,evidence_required_seconds=15,
                       trade_coverage_seconds=20,latest_trade_age_seconds=0,
                       latest_trade_epoch=1000,buy_notional=200,sell_notional=100,
                       price_direction=1,windows={},sustained_control_side=1,fast_control_side=1)
        self.ready=dict(active=True,scanner_ready=True,instrument_ready=True,
                        h1_verified=True,mark=100,checkpoint_ready=True,stamp=1000)

    def test_cold_start_requires_metadata_but_never_candle_structure(self):
        self.assertEqual(entry_status('BTC',{},self.flow,**{**self.ready,'instrument_ready':False})['reason'],'WAIT_CONTRACT_METADATA')
        self.assertEqual(entry_status('BTC',{},self.flow,**{**self.ready,'h1_verified':False})['reason'],'ENTRY_SIGNAL_READY_WAITING_EXECUTOR')

    def test_real_tape_warmup_is_explicit_instead_of_instant_fake_readiness(self):
        flow={**self.flow,'evidence_ready':False,'trade_coverage_seconds':4}
        status=entry_status('BTC',self.analysis,flow,**self.ready)
        self.assertEqual(status['action'],'WAIT')
        self.assertEqual(status['reason'],'WAIT_OBSERVED_TAPE')
        self.assertEqual(status['remaining_observation_seconds'],11)
        self.assertFalse(status['data_ready'])

    def test_buying_stopped_is_wait_not_long_even_with_old_minute_majority(self):
        flow={**self.flow,'sustained_control_side':0,'fast_control_side':-1}
        status=entry_status('BTC',self.analysis,flow,**self.ready)
        self.assertEqual(status['reason'],'WAIT_BUY_CONTROL')
        self.assertTrue(status['data_ready'])

    def test_signal_is_not_misreported_as_committed_open(self):
        status=entry_status('BTC',self.analysis,self.flow,**self.ready)
        self.assertEqual(status['action'],'WAIT')
        self.assertTrue(status['signal_ready'])
        held=entry_status('BTC',self.analysis,self.flow,position={'side':1},**self.ready)
        self.assertEqual(held['action'],'HOLD')

    def test_five_tokens_have_independent_entry_or_wait_status_without_changing_state(self):
        tokens=[{'symbol':s,'decision':entry_status(s,self.analysis,self.flow,**self.ready)}
                for s in ('BTC','ETH','SOL','HYPE','NEAR')]
        state={'engine_active':True,'_bybit_instruments':{t['symbol']:{} for t in tokens},'bybit_discovery':{}}
        before=copy.deepcopy(state)
        status=startup_snapshot(state,tokens,observed_markets=600)
        self.assertEqual(status['stage'],'RUNNING')
        self.assertEqual(status['decisions_ready'],5)
        self.assertEqual(status['waiting_tokens'],5)
        self.assertEqual(status['opened_positions'],0)
        self.assertEqual(len(status['token_reasons']),5)
        self.assertEqual(status['observed_markets'],600)
        self.assertEqual(state,before)

    def test_global_scanner_outage_is_not_reported_as_startup_complete(self):
        tokens=[{'symbol':'BTC','decision':{'action':'HOLD','data_ready':True}}]
        status=startup_snapshot({'engine_active':True,'_bybit_instruments':{'BTC':{}},
                                 'bybit_discovery':{'selection_frozen':True}},tokens)
        self.assertEqual(status['stage'],'WAIT_SCANNER')
