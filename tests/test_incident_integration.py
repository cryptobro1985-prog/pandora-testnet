"""Retained valuation, recovery, dashboard and maintenance accounting contracts."""
import copy
import time
import unittest
from unittest.mock import patch

import app
from tests import test_app_risk_audit as risk_fixture
from tests import test_incident_locals as locals_fixture
from tests.test_runtime_audit import position


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



@unittest.skipUnless(__import__('os').getenv('PANDORA_TEST_DATABASE_URL_FILE'),'isolated PostgreSQL required')
class IncidentPostgresTests(unittest.TestCase):
    setUp=risk_fixture.ApplicationRiskAuditTests.setUp
    tearDown=risk_fixture.ApplicationRiskAuditTests.tearDown
    seed_position=risk_fixture.ApplicationRiskAuditTests.seed_position




    def test_maintenance_loss_arms_watch_without_inventing_counterflow(self):
        self.seed_position(mark=50)
        app.pandora_mark_positions({'BTC':50})
        watch=app.S['pandora_watch']['BTC']
        self.assertNotIn('counter_pressure_seen',watch['context'])
        self.assertEqual(watch['context']['phase'],'WAIT_INDEPENDENT_EXECUTIONS')
        with self.connect() as db:
            row=db.execute('select pnl,reason from pandora_win_trade_history').fetchone()
        self.assertLess(row['pnl'],0)
        self.assertEqual(row['reason'],'modeled_maintenance_breach')
