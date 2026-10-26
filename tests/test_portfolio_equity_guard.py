import copy
import unittest
from unittest.mock import MagicMock,patch
from emergency_guard import equity_drawdown_state
import app


class EquityStateTests(unittest.TestCase):
    def test_peak_and_five_percent_trigger_use_observed_equity(self):
        s=equity_drawdown_state({},170.,0,True)
        self.assertEqual(s['peak'],170.)
        s=equity_drawdown_state(s,220.,1,True)
        self.assertEqual(s['status'],'ARMED')
        s=equity_drawdown_state(s,208.,2,True)
        self.assertEqual(s['status'],'CLOSING')
        self.assertEqual(s['blocked_until'],902)

    def test_restart_and_price_recovery_do_not_cancel_pending_closes(self):
        s=equity_drawdown_state({'peak':220.},208.,2,True)
        restored=copy.deepcopy(s)
        self.assertEqual(equity_drawdown_state(restored,225.,3,True)['status'],'CLOSING')

    def test_pause_waits_for_flat_account_and_cooldown_then_rebases(self):
        s=equity_drawdown_state({'peak':220.},208.,2,True)
        s=equity_drawdown_state(s,207.,4,False)
        self.assertEqual(s['status'],'PAUSED')
        self.assertEqual(equity_drawdown_state(s,207.,901,False)['status'],'PAUSED')
        s=equity_drawdown_state(s,207.,903,False)
        self.assertEqual((s['status'],s['peak']),( 'ARMED',207.))

    def test_realized_loss_without_open_positions_still_pauses_entries(self):
        s=equity_drawdown_state({'peak':220.},200.,1,False)
        self.assertEqual(s['status'],'PAUSED')

    def test_invalid_values_fail_closed(self):
        for v in (float('nan'),float('inf'),-1):
            with self.assertRaises(ValueError):equity_drawdown_state({},v,1,True)


class EquityIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.saved=copy.deepcopy(app.S)
        app.S.update(mode='PAPER_ONLY',engine_active=True,equity=220.,portfolio_equity_guard={'peak':220.},
                     positions={},pump_positions={},whale_positions={},local_swing_positions={})
    def tearDown(self):
        app.S.clear();app.S.update(self.saved)

    def test_all_four_books_close_and_new_entries_are_blocked(self):
        for key,symbol in [('positions','BTC'),('pump_positions','LINK'),('whale_positions','WIF'),('local_swing_positions','NEAR')]:
            app.S[key]={symbol:dict(entry=100.,notional=250.,side=1,opened=symbol)}
        pg=MagicMock();db=pg.return_value.__enter__.return_value
        with patch.object(app,'pg',pg),patch.object(app.STORE,'fence'),patch.object(app,'journal'), \
             patch.object(app,'close_news_position',return_value={'pnl':-4}) as news, \
             patch.object(app,'pump_close',return_value={'pnl':-4}) as pump, \
             patch.object(app,'whale_liq_close',return_value={'pnl':-4}) as whale, \
             patch.object(app,'local_swing_close',return_value={'pnl':-4}) as local:
            result=app.portfolio_equity_protect(dict(BTC=98.,LINK=98.,WIF=98.,NEAR=98.))
        self.assertEqual(len(result),4)
        for close in (news,pump,whale,local):close.assert_called_once()
        self.assertEqual(app.S['portfolio_equity_guard']['status'],'CLOSING')
        self.assertEqual(app._reserve_shared_entry('NEW')[2],'emergency_profit_cooldown')
        self.assertTrue(any('update portfolio_guard_state' in c.args[0] for c in db.execute.call_args_list))

    def test_missing_mark_does_not_invent_equity_and_blocks_entries(self):
        app.S['pump_positions']={'X':dict(entry=100.,notional=250.,side=1,opened='x')}
        with patch.object(app,'pg') as pg:
            self.assertEqual(app.portfolio_equity_protect({}),[])
        pg.assert_not_called()
        self.assertEqual(app._reserve_shared_entry('NEW')[2],'emergency_profit_cooldown')
