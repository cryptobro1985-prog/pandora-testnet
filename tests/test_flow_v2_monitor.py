"""Flow v2 monitor is read-only and candle history has no readiness authority."""
import ast
import inspect
import unittest

from pandora_api import openapi
from pandora_decisions import entry_status, startup_snapshot
from pandora_monitor import SCRIPT, render


class FlowV2MonitorTests(unittest.TestCase):
    def setUp(self):
        self.flow=dict(trade_data_fresh=True, sequence_valid=True, evidence_ready=True,
                       sustained_control_side=1, fast_control_side=1,
                       context_control_side=1, buy_notional=700, sell_notional=300,
                       imbalance=.4, buy_absorbed=False, sell_absorbed=True,
                       buy_price_response=.03, sell_price_response=-.002,
                       latest_trade_epoch=1793491200, latest_receive_epoch=1793491200.1)
        self.ready=dict(active=True, scanner_ready=True, instrument_ready=True,
                        mark=.012691, checkpoint_ready=True)

    def test_old_structure_and_direction_cannot_gate_or_choose_flow_entry(self):
        blocked=dict(entry_side=-1, ready=False, anchor_confirmed=False,
                     entry_blocked=True, live_structure_fresh=False,
                     entry_block_reason='old candle structure')
        for analysis in ({}, blocked):
            status=entry_status('PUMP', analysis, self.flow,
                                h1_verified=False, **self.ready)
            self.assertTrue(status['data_ready'])
            self.assertEqual(status['side'], 1)
            self.assertTrue(status['signal_ready'])
            self.assertEqual(status['action'], 'WAIT')
        tree=ast.parse(inspect.getsource(entry_status))
        loaded={node.id for node in ast.walk(tree)
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
        self.assertNotIn('analysis', loaded)
        self.assertNotIn('h1_verified', loaded)

    def test_runtime_flow_decision_is_authoritative_for_reentry(self):
        waiting=entry_status('PUMP', {}, self.flow, watch={'side':1},
            flow_decision={'action':'WAIT','side':1,'reason':'New independent executions required'},
            **self.ready)
        self.assertFalse(waiting.get('signal_ready', False))
        self.assertEqual(waiting['message'], 'New independent executions required')
        resumed=entry_status('PUMP', {}, self.flow, watch={'side':1},
            flow_decision={'action':'REENTRY','side':1,'reason':'New BUY control confirmed'},
            **self.ready)
        self.assertTrue(resumed['signal_ready'])
        self.assertEqual(resumed['action'], 'WAIT')

    def test_stale_or_invalid_held_tape_reports_uncertainty_without_close(self):
        for flow in ({**self.flow,'trade_data_fresh':False},
                     {**self.flow,'sequence_valid':False}):
            status=entry_status('PUMP', {}, flow, position={'side':1}, **self.ready)
            self.assertEqual(status['action'], 'DATA_UNCERTAIN')
            self.assertFalse(status['data_ready'])

    def test_fresh_experiment_account_hourly_universe_and_flow_are_visible(self):
        token=dict(symbol='PUMP',rank=1,price=.012691,change_24h_pct=53.2,
                   selected_at='2026-11-01T00:00:00Z',next_hourly_refresh='2026-11-01T01:00:00Z',
                   management_state='ACTIVE_ENTRY',position_state='FLAT',flow_regime='BUY_CONTROL',
                   flow_state=self.flow,flow_decision={'action':'WAIT','reason':'Independent BUY executions required'})
        page=render({'pandora':dict(experiment_id='pandora_flow_v2',starting_equity=500,
             total_equity=500,realized_pnl=0,unrealized_pnl=0,closed_trades_count=0,
             tokens=[token],open_positions=[],closed_trades=[],
             universe={'selected_at':token['selected_at'],'next_hourly_refresh':token['next_hourly_refresh']}),
             'health':{}})
        for field in ('flow_regime','position_state','management_state','ratio',
                      'buy_absorption','sell_absorption','buy_response','sell_response',
                      'exchange_time','receive_time','change_24h','selected_at','next_refresh'):
            self.assertIn('data-field="'+field+'"', page)
        self.assertIn('pandora_flow_v2', page)
        self.assertIn('BUY_CONTROL', page)
        self.assertIn('+53.20%', page)
        self.assertIn('Independent BUY executions required', page)
        self.assertIn('id="account-open-count" class="">0</strong>', page)
        self.assertIn('id="account-closed-count" class="">0</strong>', page)
        discovery=page.split('<section id="panel-discovery"',1)[1].split('<details',1)[0]
        self.assertNotIn('H1/M15', discovery)
        self.assertNotIn('Разрешение входа', page)
        self.assertIn('История структуры · не участвует в торговых решениях', page)

    def test_managed_position_outside_top_five_stays_visible_and_does_not_count_as_selection(self):
        held={'symbol':'LEGACY','side':-1,'opened':'fixture','management_state':'MANAGED_POSITION',
              'flow_regime':'SELL_CONTROL','position_state':'SHORT','flow_state':self.flow}
        tokens=[dict(symbol=str(i),decision={'data_ready':True}) for i in range(5)]
        tokens.append({**held,'position':held,'decision':{'action':'HOLD','data_ready':True}})
        startup=startup_snapshot({'engine_active':True,'_bybit_instruments':{'PUMP':{}}},tokens)
        self.assertEqual(startup['selected_tokens'],5)
        self.assertEqual(startup['opened_positions'],1)
        self.assertEqual(startup['stage'],'RUNNING')
        page=render({'pandora':{'tokens':tokens[:5],'open_positions':[held]},'health':{}})
        positions=page.split('<section id="panel-positions"',1)[1].split('</section>',1)[0]
        self.assertIn('LEGACY',positions)
        self.assertIn('MANAGED_POSITION',positions)
        self.assertIn('SELL_CONTROL',positions)

    def test_api_documents_current_experiment_and_only_read_operations(self):
        spec=openapi('https://paper.example/')
        self.assertIn('experiment_id',spec['paths']['/api/pandora']['get']['description'])
        self.assertEqual(spec['components']['schemas']['FlowRegime']['enum'],
                         ['BUY_CONTROL','BUY_WEAKENING','NEUTRAL','SELL_WEAKENING','SELL_CONTROL'])
        self.assertTrue(all(list(operations)==['get'] for operations in spec['paths'].values()))
        for fragment in ('function syncList(', 'keep.node.isConnected', 'fieldCache',
                         "sessionStorage.setItem('pandora-tab'", 'flowMetrics(t)'):
            self.assertIn(fragment,SCRIPT)
        self.assertNotIn('.innerHTML',SCRIPT)
