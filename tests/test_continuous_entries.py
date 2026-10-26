import copy
import unittest
from unittest.mock import patch
import app


class ContinuousEntryTests(unittest.TestCase):
    def setUp(self):
        self.saved=copy.deepcopy(app.S)
        stamp=app.time.time()
        app.S.update(mode='PAPER_ONLY',orders_enabled=False,engine_active=True,equity=100.,
                     positions={},pump_positions={},whale_positions={},local_swing_positions={},
                     _entry_reservations={},_prices={'HYPE':100.},_last_poll_epoch=stamp,last_checkpoint=app.now(),
                     _emergency_until=stamp+900,portfolio_equity_guard={'status':'PAUSED','blocked_until':stamp+900})
    def tearDown(self):
        app.S.clear();app.S.update(self.saved)

    def test_old_pause_state_does_not_block_fresh_entry_price(self):
        self.assertEqual(app.current_entry_price('HYPE'),100.)

    def test_all_strategy_reservations_ignore_timer_but_keep_margin_budget(self):
        for strategy in ('shared','pump_dump','whale_liquidation','local_swing'):
            reserved,margin,reason,free=app._reserve_shared_entry('HYPE',.1,strategy)
            self.assertTrue(reserved,(strategy,reason))
            app._release_shared_entry('HYPE',strategy)
        app.S['pump_positions']={'OTHER':dict(margin=100.,notional=2500.,leverage=25.)}
        self.assertEqual(app._reserve_shared_entry('HYPE',.1,'pump_dump')[2],'insufficient_free_margin')

    def test_stale_prices_still_cannot_create_entry(self):
        app.S['_last_poll_epoch']=app.time.time()-60
        self.assertIsNone(app.current_entry_price('HYPE'))
