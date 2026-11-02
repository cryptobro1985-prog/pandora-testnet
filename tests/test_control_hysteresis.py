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

    def test_strong_counterflow_with_price_response_exits_immediately(self):
        for side in (-1,1):
            p=position(side)
            self.assertEqual(pressure_exit(p,None,100+side*8,flow(-side,1000)),
                             'confirmed_counter_move_exit')
            self.assertTrue(p['features']['exit_decision']['counter_control_ready'])

    def test_weak_counterflow_never_closes(self):
        for side in (-1,1):
            p=position(side)
            for epoch in range(1000,1010):
                self.assertIsNone(pressure_exit(p,None,100+side*8,flow(-side,epoch,.501)))

    def test_confirmed_opposite_local_bypasses_flow_confirmation(self):
        for side in (-1,1):
            p=position(side)
            self.assertEqual(pressure_exit(p,None,100+side*8,{},opposite_local_confirmed=True),
                             'opposite_confirmed_h1_local')

    def test_numerically_flat_auction_does_not_fake_opposite_price_control(self):
        rows=[(980,100,1,'A'),(981,100,1,'B'),
              (996,100.0,30,'A'),(997,100.2,70,'B'),
              (998,99.6,30,'A'),(999,100.0,70,'B')]
        result=summarize(rows,1000,20)
        self.assertGreater(result['windows']['5']['imbalance'],.2)
        self.assertAlmostEqual(result['windows']['5']['price_return'],0.,places=12)
        self.assertEqual(result['fast_control_side'],1)

    def test_absorbed_notional_majority_yields_control_to_price_impact(self):
        for side in (-1,1):
            own='B' if side>0 else 'A';other='A' if side>0 else 'B'
            rows=[(980,100,1,'B'),(981,100,1,'A'),
                  (996,100,30,other),(997,100+side*.1,70,own),
                  (998,100+side*.05,70,own),(999,100-side*.2,30,other)]
            result=summarize(rows,1000,20)
            self.assertEqual(result['fast_control_side'],-side)
