"""Concrete profit-retention/churn regressions; no historical optimization."""
import unittest
from tests.test_flow_v2_strategy import Tape


class FlowProfitAuditTests(unittest.TestCase):
    def test_initial_micro_drift_cannot_open_below_round_trip_cost(self):
        for side in (-1,1):
            tape=Tape(side)
            for offset in (0,.001,.002,.003):
                result=tape.trade(100+side*offset,side)
                self.assertEqual(result['action'],'WAIT')
            result=tape.trade(100+side*.5,side)
            self.assertEqual(result['action'],'OPEN')

    def test_spread_bounces_do_not_pay_for_reversal_without_net_progress(self):
        for side in (-1,1):
            tape=Tape(side).established();price=tape.price;tape.close()
            for offset,control,size in ((-1,-side,1000),(0,side,1),(-.8,-side,1000),(.1,side,1),(-1.001,-side,1000)):
                result=tape.trade(price+side*offset,control,size)
            self.assertGreater(result['flow']['sell_price_response' if side>0 else 'buy_price_response'],.0019)
            self.assertEqual(result['action'],'WAIT')

    def test_recent_defended_noise_replaces_obsolete_large_noise_for_both_sides(self):
        for side in (-1,1):
            tape=Tape(side).established();price=tape.price
            state=tape.strategy.tokens['PUMP']['pressure_state']
            state.update(best=side*price,noise=5.,candidate={'counter_extreme':side*price-.2,'retest_best':None})
            tape.trade(price+side*.5,side)
            self.assertAlmostEqual(tape.strategy.tokens['PUMP']['pressure_state']['noise'],.2)
            for offset in (.2,-.1,-.4):result=tape.trade(price+side*offset,-side,1000)
            self.assertEqual(result['action'],'CLOSE')
