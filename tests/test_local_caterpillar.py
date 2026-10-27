import unittest
from local_caterpillar import pressure_exit, update_watch, reentry_ready, protective_breakeven


def flow(value, fresh=True):
    return dict(flow_imbalance=value, trade_data_fresh=fresh, latest_trade_age_seconds=1.)


class CaterpillarTests(unittest.TestCase):
    def m15(self, side, adverse=False):
        return dict(ready=True, side=side, strong_adverse_pressure=adverse, adverse_score=4 if adverse else 0,
                    return_15m=-side*.003 if adverse else side*.003,
                    recovery_confirmed=not adverse, recovery_score=0 if adverse else 4, median_range_move=.008,
                    close_location=.9 if side>0 else .1)

    def test_exit_requires_weakened_m15_and_opposite_actual_flow_and_recoil(self):
        for side in (-1, 1):
            pos=dict(side=side,entry=100.,features=dict(mfe_price_move=.01))
            mark=100.+side*.7
            self.assertEqual(pressure_exit(pos,self.m15(side,True),mark,flow(-side*.5)),'m15_pressure_reversal_profit_only')
            self.assertIsNone(pressure_exit(pos,self.m15(side,True),mark,flow(side*.5)))
            self.assertIsNone(pressure_exit(pos,self.m15(side,True),mark,flow(-side*.5,False)))
            self.assertIsNone(pressure_exit(pos,self.m15(side),mark,flow(-side*.5)))

    def test_no_exit_for_small_pullback_while_original_pressure_continues(self):
        pos=dict(side=-1,entry=100.,features=dict(mfe_price_move=.02))
        self.assertIsNone(pressure_exit(pos,self.m15(-1,True),98.5,flow(-.4)))

    def test_both_directions_reenter_at_a_better_price_after_real_pullback(self):
        for side in (-1, 1):
            watch=dict(side=side,exit_price=100.,exit_at='1970-01-01T00:01:40+00:00',context={})
            # Short exits at 100, rebounds to 101, resumes selling at 100.8.
            # Long mirrors this and resumes buying below the prior sale price.
            watch=update_watch(watch,100.-side,self.m15(side,True),flow(-side*.5),110.)
            self.assertEqual(watch['context']['phase'],'WAIT_RESUMPTION')
            mark=100.-side*.8
            watch=update_watch(watch,mark,self.m15(side),flow(side*.5),112.)
            self.assertTrue(reentry_ready(side,self.m15(side),mark,watch,flow(side*.5),112.))
            self.assertFalse(reentry_ready(side,self.m15(side),mark,watch,flow(side*.5,False),112.))

    def test_unchanged_pre_exit_signal_cannot_reopen_without_pullback(self):
        for side in (-1, 1):
            watch=dict(side=side,exit_price=100.,exit_at='1970-01-01T00:01:40+00:00')
            watch=update_watch(watch,100.,self.m15(side),flow(side*.5),110.)
            self.assertFalse(reentry_ready(side,self.m15(side),100.,watch,flow(side*.5),110.))

    def test_no_reentry_while_pullback_is_still_driven_by_opposite_flow(self):
        for side in (-1, 1):
            watch=dict(side=side,exit_price=100.,exit_at='1970-01-01T00:01:40+00:00')
            watch=update_watch(watch,100.-side,self.m15(side,True),flow(-side*.5),110.)
            self.assertFalse(reentry_ready(side,self.m15(side),100.-side*.8,watch,flow(-side*.5),112.))

    def test_fixed_safety_floor_does_not_trail_fifty_percent_of_peak(self):
        for side in (-1,1):
            pos=dict(side=side,entry=100.,features=dict(mfe_price_move=.02,estimated_round_trip_cost_move=.0013))
            self.assertIsNone(protective_breakeven(pos,100.+side*.7))
            self.assertIsNone(protective_breakeven(pos,100.+side*.1))

    def test_sparse_flow_does_not_trigger_exit(self):
        pos=dict(side=-1,entry=100.,features=dict(mfe_price_move=.01))
        sparse=dict(flow(.5),trade_count_60s=2,observed_notional_60s=46.)
        self.assertIsNone(pressure_exit(pos,self.m15(-1,True),99.7,sparse))

    def test_routine_m15_weakening_does_not_crystallize_a_loss(self):
        pos=dict(side=1,entry=100.,features=dict(mfe_price_move=0.,estimated_round_trip_cost_move=.001))
        self.assertIsNone(pressure_exit(pos,self.m15(1,True),99.7,flow(-.4)))

if __name__=='__main__':unittest.main()
