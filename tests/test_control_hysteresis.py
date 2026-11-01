"""Weak/brief pullbacks hold; observed strong structural transfers still exit."""
import copy
import unittest

from local_order_flow import initial_entry_candidate, pressure_exit
from pandora_flow import summarize


def tape(side, share=.7):
    own='B' if side>0 else 'A';other='A' if side>0 else 'B'
    return [(980,100,1,'B'),(981,100,1,'A'),
            (996,100,100*(1-share),other),
            (997,100+side*.1,100*share,own),
            (998,100+side*.05,100*(1-share),other),
            (999,100+side*.2,100*share,own)]


def flow(side,epoch,share=.7):
    return dict(trade_data_fresh=True,latest_trade_age_seconds=0,
                latest_trade_epoch=epoch,decision_event_epoch=epoch,
                buy_notional=100*share if side>0 else 100*(1-share),
                sell_notional=100*share if side<0 else 100*(1-share),
                price_direction=side)


def position(side):
    return dict(entry=100,side=side,features={'pressure_state':{
        'best':side*100+10,'noise':.5,'barrier':side*100+9}})


class ControlHysteresisTests(unittest.TestCase):
    def test_bare_majority_in_both_windows_is_not_control(self):
        for side in (-1,1):
            for share in (.501,.55,.599):
                result=summarize(tape(side,share),1000,20)
                self.assertEqual(result['fast_control_side'],0)
                self.assertEqual(result['sustained_control_side'],0)
            result=summarize(tape(side,.7),1000,20)
            self.assertEqual(result['fast_control_side'],side)
            self.assertEqual(result['sustained_control_side'],side)

    def test_strong_five_second_burst_cannot_override_weak_fifteen_seconds(self):
        for side in (-1,1):
            rows=tape(side,.7)
            rows.insert(2,(990,100,70,'A' if side>0 else 'B'))
            result=summarize(rows,1000,20)
            self.assertGreater(result['windows']['5']['imbalance']*side,.2)
            self.assertLess(result['windows']['15']['imbalance']*side,.2)
            self.assertEqual(result['fast_control_side'],0)

    def test_large_absorbed_volume_without_price_response_is_not_control(self):
        for side in (-1,1):
            rows=[(t,100,volume,aggressor) for t,price,volume,aggressor in tape(side)]
            self.assertEqual(summarize(rows,1000,20)['fast_control_side'],0)

    def test_bare_volume_majority_cannot_open(self):
        for side in (-1,1):
            analysis=dict(ready=True,anchor_confirmed=True,h1_direction_anchor=True,entry_side=side)
            self.assertFalse(initial_entry_candidate('BTC',analysis,None,flow(side,1000,.501),1000)['eligible'])

    def test_small_pullback_inside_observed_noise_holds_under_strong_counterflow(self):
        for side in (-1,1):
            p=position(side)
            for epoch in (1000,1001,1003,1004):
                self.assertIsNone(pressure_exit(p,None,100+side*9.8,flow(-side,epoch)))

    def test_weak_counterflow_never_closes_even_after_a_price_break(self):
        for side in (-1,1):
            p=position(side)
            for epoch in range(1000,1010):
                self.assertIsNone(pressure_exit(p,None,100+side*8,flow(-side,epoch,.501)))

    def test_strong_structural_transfer_requires_three_seconds_of_new_executions(self):
        for side in (-1,1):
            p=position(side);mark=100+side*8
            for epoch in (1000,1001,1002.9):
                self.assertIsNone(pressure_exit(p,None,mark,flow(-side,epoch)))
            p=copy.deepcopy(p)  # Features survive a normal state checkpoint.
            self.assertEqual(pressure_exit(p,None,mark,flow(-side,1003)),'confirmed_counter_move_exit')

    def test_repolling_the_same_execution_cannot_confirm_takeover(self):
        for side in (-1,1):
            p=position(side)
            for _ in range(20):
                self.assertIsNone(pressure_exit(p,None,100+side*8,flow(-side,1000)))
            self.assertEqual(p['features']['exit_control_state']['observed_seconds'],0)

    def test_neutral_own_side_stale_and_gapped_observations_reset_confirmation(self):
        for side in (-1,1):
            for interruption in (flow(-side,1002,.501),flow(side,1002),{},flow(-side,1007)):
                p=position(side);mark=100+side*8
                self.assertIsNone(pressure_exit(p,None,mark,flow(-side,1000)))
                self.assertIsNone(pressure_exit(p,None,mark,interruption))
                self.assertIsNone(pressure_exit(p,None,mark,flow(-side,1008)))

    def test_favorable_extreme_cancels_the_previous_takeover_timer(self):
        for side in (-1,1):
            p=position(side)
            self.assertIsNone(pressure_exit(p,None,100+side*8,flow(-side,1000)))
            self.assertIsNone(pressure_exit(p,None,100+side*11,flow(-side,1003),opposite_local_confirmed=True))
            self.assertEqual(p['features']['exit_control_state']['observed_seconds'],0)

    def test_confirmed_opposite_local_cannot_bypass_counterflow_confirmation(self):
        for side in (-1,1):
            p=position(side);mark=100+side*8
            self.assertIsNone(pressure_exit(p,None,mark,flow(-side,1000),opposite_local_confirmed=True))
            self.assertIsNone(pressure_exit(p,None,mark,flow(-side,1001,.501),opposite_local_confirmed=True))
            self.assertIsNone(pressure_exit(p,None,mark,flow(-side,1002),opposite_local_confirmed=True))
            self.assertEqual(pressure_exit(p,None,mark,flow(-side,1005),opposite_local_confirmed=True),
                             'opposite_confirmed_h1_local')

    def test_sustained_opposite_flow_without_structural_transfer_still_holds(self):
        for side in (-1,1):
            p=position(side);p['features']['pressure_state'].pop('barrier')
            for epoch in (1000,1001,1003):
                self.assertIsNone(pressure_exit(p,None,100+side*8,flow(-side,epoch)))
