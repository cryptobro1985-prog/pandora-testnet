"""Incident paths across application allocation, recovery, valuation and reversal."""
import copy
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app
from tests import test_app_risk_audit as risk_fixture
from tests import test_incident_locals as locals_fixture
from tests.test_runtime_audit import fake_runtime, position


class IncidentStateTests(unittest.TestCase):
    def setUp(self):
        self.saved=copy.deepcopy(app.S)
    def tearDown(self):
        app.S.clear();app.S.update(self.saved)

    def test_fresh_other_market_cannot_refresh_stale_position_valuation(self):
        p=position()
        values,total,missing=app.value_live_positions({'BTC':p},{'BTC':90,'ETH':200},{'BTC':980,'ETH':1000},1001)
        self.assertIsNone(total)
        self.assertEqual(missing,['BTC'])
        self.assertIsNone(values['BTC']['mark'])
        self.assertIsNone(values['BTC']['unrealized_pnl'])
        self.assertEqual(values['BTC']['price_age_seconds'],21)

    def test_fresh_snapshot_keeps_actual_negative_pnl(self):
        values,total,missing=app.value_live_positions({'BTC':position()},{'BTC':90},{'BTC':1000},1001)
        self.assertFalse(missing)
        self.assertLess(total,0)
        self.assertEqual(total,values['BTC']['unrealized_pnl'])

    def test_stale_partial_history_requests_recovery_before_hour_boundary(self):
        h1,m15,stamp=locals_fixture.IncidentLocalTests.context()
        with patch.object(app,'_pandora_h1_candles',return_value=(h1,stamp)),patch.object(app,'_local_m15_candles',return_value=(m15,stamp)):
            self.assertFalse(app.needs_local_history('BTC'))
            h1[-1]['observed_at_ms']=stamp-16000
            self.assertTrue(app.needs_local_history('BTC'))

    def test_dashboard_does_not_copy_raw_price_arrays_or_fake_new_mark(self):
        class Expensive:
            def __deepcopy__(self,memo):raise AssertionError('price-history deepcopy')
        epoch=time.time()
        app.S.update(pandora_win_positions={},pandora_watch={},_pandora_analysis={},
            pandora_win_h1_direction={},_timeline={'BTC':Expensive()},_hist={'BTC':Expensive()},
            _prices={},_price_received_epoch={},bybit_discovery={'selected_symbols':['AIXBT'],
                'selected':[dict(symbol='AIXBT',last=.12,price_received=epoch)],'candidate_symbols':[]})
        with patch.object(app,'WIN',None):
            data=app.build_dashboard_snapshot({'trades':[],'token_totals':[],'events':{}})
        token=data['pandora']['tokens'][0]
        self.assertIsNone(token['price'])
        self.assertFalse(token['mark_fresh'])
        self.assertAlmostEqual(token['scanner_price'],.12)
        self.assertEqual(token['decision']['reason'],'WAIT_ENGINE_LEASE')

    def test_committed_close_can_reverse_in_same_cycle_only_with_new_direction(self):
        for allow in (False,True):
            runtime,a,_=fake_runtime();p=position();p['side']=-1
            a.S['pandora_win_positions']['BTC']=p
            a.S['_pandora_analysis']['BTC']={'entry_side':1 if allow else -1}
            attempted=[]
            a.pandora_mark_positions=lambda prices:a.S['pandora_win_positions'].pop('BTC')
            def entry(prices):
                self.assertNotIn('BTC',a.S['pandora_win_positions'])
                attempted.append(prices)
            a.pandora_flow_fast_entries=entry
            runtime.cycle({'BTC':101})
            self.assertEqual(len(attempted),int(allow))


@unittest.skipUnless(__import__('os').getenv('PANDORA_TEST_DATABASE_URL_FILE'),'isolated PostgreSQL required')
class IncidentPostgresTests(unittest.TestCase):
    setUp=risk_fixture.ApplicationRiskAuditTests.setUp
    tearDown=risk_fixture.ApplicationRiskAuditTests.tearDown
    seed_position=risk_fixture.ApplicationRiskAuditTests.seed_position

    def test_moving_market_is_repriced_instead_of_permanently_rejecting_entry(self):
        stamp=time.time()
        a=dict(ready=True,anchor_confirmed=True,h1_direction_anchor=True,
               entry_side=1,pivot_type='LOCAL_LOW',pivot_price=99,
               signal_candle_time=1,pivot_candle_time=1)
        f=dict(trade_data_fresh=True,latest_trade_age_seconds=0,latest_trade_epoch=stamp,
               buy_notional=70,sell_notional=30,price_direction=1)
        app.S.update(bybit_discovery={'selected_symbols':['BTC']},_pandora_analysis={'BTC':a},
            pandora_win_h1_direction={'BTC':a},_bybit_instruments={'BTC':{'max_leverage':25,'observed_at':stamp}})
        with patch.object(app,'pandora_runtime_h1_verified',return_value=True),\
             patch.object(app,'current_entry_price',side_effect=[100,100.1]),\
             patch.object(app,'MARKET_OBS',SimpleNamespace(flow_context=lambda *args:f)):
            self.assertTrue(app.pandora_open('BTC',1,a))
        self.assertEqual(app.S['pandora_win_positions']['BTC']['entry'],100.1)
        self.assertAlmostEqual(app.S['pandora_win_positions']['BTC']['features']['risk_plan']['average_entry'],100.1)

    def test_short_above_historical_high_is_rejected_before_allocation(self):
        a=dict(ready=True,anchor_confirmed=True,h1_direction_anchor=True,
               entry_side=-1,pivot_type='LOCAL_HIGH',pivot_price=.01264,
               signal_candle_time=1,pivot_candle_time=1)
        f=dict(trade_data_fresh=True,latest_trade_age_seconds=0,latest_trade_epoch=time.time(),
               buy_notional=30,sell_notional=70,price_direction=-1)
        app.S.update(bybit_discovery={'selected_symbols':['BTC']},_pandora_analysis={'BTC':a})
        with patch.object(app,'pandora_runtime_h1_verified',return_value=True),\
             patch.object(app,'current_entry_price',return_value=.01269),\
             patch.object(app,'MARKET_OBS',SimpleNamespace(flow_context=lambda *args:f)):
            self.assertFalse(app.pandora_open('BTC',-1,a))
        self.assertEqual(app.S['pandora_executor_rejections']['BTC']['reason'],'STRUCTURE_REFERENCE_BROKEN_BY_MARK')

    def test_new_m15_direction_survives_application_monotonic_guards_and_restore(self):
        h1,m15,stamp=locals_fixture.IncidentLocalTests.context()
        f=dict(trade_data_fresh=True,sustained_control_side=1)
        with patch.object(app,'_local_m15_candles',return_value=(m15,stamp)),\
             patch.object(app,'MARKET_OBS',SimpleNamespace(flow_context=lambda *args:f)):
            active=app.pandora_win_h1_direction(h1,stamp,'BTC')
        self.assertEqual(active['entry_side'],1)
        self.assertFalse(active['entry_blocked'])
        self.assertEqual(active['confirmed_local']['entry_side'],-1)
        app.restore_state()
        resolved=app._local_persisted_anchor('BTC')
        self.assertEqual(resolved['confirmation_source'],'closed_M15_structure_and_executed_control')
        self.assertEqual(resolved['execution_local']['entry_side'],1)
        self.assertEqual(resolved['execution_local']['interval'],'15m')

    def test_maintenance_loss_arms_watch_without_inventing_counterflow(self):
        self.seed_position(mark=50)
        app.pandora_mark_positions({'BTC':50})
        watch=app.S['pandora_watch']['BTC']
        self.assertFalse(watch['context']['counter_pressure_seen'])
        self.assertEqual(watch['context']['phase'],'WAIT_COUNTER_CONTROL')
        with self.connect() as db:
            row=db.execute('select pnl,reason from pandora_win_trade_history').fetchone()
        self.assertLess(row['pnl'],0)
        self.assertEqual(row['reason'],'modeled_maintenance_breach')
