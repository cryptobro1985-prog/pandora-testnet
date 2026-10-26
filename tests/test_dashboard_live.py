import copy
import unittest
from unittest.mock import patch
import app


class DashboardLiveTests(unittest.TestCase):
    def setUp(self):
        self.saved=copy.deepcopy(app.S)
        pos=dict(entry=100.,side=1,leverage=25.,margin=10.,notional=250.,opened=app.now(),headline='fixture',features={})
        app.S.update(equity=100.,realized_pnl=0.,positions={'BTC':copy.deepcopy(pos)},
                     pump_positions={'SOL':copy.deepcopy(pos)},whale_positions={'ETH':copy.deepcopy(pos)},
                     local_swing_positions={'HYPE':copy.deepcopy(pos),'NEAR':copy.deepcopy(pos)},
                     _prices={s:101. for s in ('BTC','SOL','ETH','HYPE','NEAR')},
                     _dashboard_cache={'total_equity':9999.,'positions':[]},
                     _dashboard_history={'trades':[],'news':[],'features':[],'today_pnl':{'pnl':2.,'trades':1},'error':'database offline'})
    def tearDown(self):app.S.clear();app.S.update(self.saved)

    def test_history_failure_and_old_cache_cannot_freeze_prices_or_hide_other_books(self):
        with patch.object(app,'pg',side_effect=AssertionError('HTTP dashboard must not query DB')):
            first=app.dashboard()
            app.S['_prices']['HYPE']=103.
            second=app.dashboard()
        self.assertEqual(len(first['positions']),5)
        before=next(p for p in first['positions'] if p['symbol']=='HYPE')
        after=next(p for p in second['positions'] if p['symbol']=='HYPE')
        self.assertEqual((before['mark'],after['mark']),(101.,103.))
        self.assertGreater(after['unrealized_pnl'],before['unrealized_pnl'])
        self.assertGreater(second['total_equity'],first['total_equity'])
        self.assertEqual(second['history_error'],'database offline')
        self.assertEqual(second['today_pnl']['pnl'],2.)

    def test_monitor_html_can_refresh_without_reloading_and_keeps_position_controls(self):
        page=app.html_dashboard(app.dashboard())
        self.assertIn('id="dashboardContent"',page)
        self.assertIn('id="refreshStatus"',page)
        self.assertIn('AbortController',page)
        self.assertIn('visibilitychange',page)
        self.assertIn('/api/positions/close',page)
        self.assertNotIn('setInterval(()=>',page)
        self.assertNotIn('__MARKET_POLL__',page)
