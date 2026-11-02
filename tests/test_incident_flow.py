"""Regressions for aggregate control lost to last-tick noise and neutral resets."""
import unittest

from local_order_flow import flow_profile, initial_entry_candidate, pressure_exit
from pandora_flow import summarize
from tests.test_control_hysteresis import flow, position, tape


def observed(rows,epoch,coverage):
    result=summarize(rows,epoch,coverage)
    result.update(trade_data_fresh=True,latest_trade_age_seconds=0,
        latest_trade_epoch=epoch,decision_event_epoch=epoch,
        buy_notional=result['windows']['60']['buy_volume'],
        sell_notional=result['windows']['60']['sell_volume'],
        price_direction=1 if rows[-1][1]>rows[-2][1] else -1)
    return result


class IncidentFlowTests(unittest.TestCase):
    def test_one_small_counter_print_does_not_erase_window_control(self):
        for side in (-1,1):
            rows=tape(side,.8)+[(999.5,100+side*.19,.01,'A' if side>0 else 'B')]
            result=observed(rows,1000,20)
            self.assertEqual(result['fast_control_side'],side)
            self.assertEqual(result['sustained_control_side'],side)
            self.assertEqual(result['price_direction'],-side)

    def medium_rows(self,side):
        buy='B' if side>0 else 'A';sell='A' if side>0 else 'B'
        return [(1000,100,1,buy),(1012,100+side*.1,100,buy),
                (1015,100+side*.2,100,buy),(1028,100+side*.3,100,buy),
                (1032,100+side*.4,100,buy),(1038,100+side*.5,50,buy),
                (1039,100+side*.45,50,sell)]

    def test_neutral_fast_window_does_not_veto_corroborated_medium_exit(self):
        for side in (-1,1):
            result=observed(self.medium_rows(side),1040,40)
            self.assertEqual(result['fast_control_side'],0)
            self.assertEqual(result['exit_control_side'],side)
            self.assertEqual(result['exit_control_basis'],'confirmed_15_30')
            self.assertTrue(flow_profile(result,-side)['counter_takeover'])
            analysis=dict(ready=True,anchor_confirmed=True,h1_direction_anchor=True,entry_side=side)
            self.assertFalse(initial_entry_candidate('BTC',analysis,None,result,1040)['eligible'])

    def test_medium_volume_without_net_price_response_cannot_claim_control(self):
        for side in (-1,1):
            rows=[(t,100,volume,aggressor) for t,price,volume,aggressor in self.medium_rows(side)]
            result=observed(rows,1040,40)
            self.assertEqual(result['exit_control_side'],0)

    def test_confirmed_counter_control_is_not_delayed_by_timer_or_structure_gate(self):
        for side in (-1,1):
            p=position(side);mark=100+side*8
            self.assertEqual(pressure_exit(p,None,mark,flow(-side,1000)),
                             'confirmed_counter_move_exit')
            self.assertEqual(p['features']['exit_control_state']['phase'],'CONFIRMED')

    def test_stale_flow_is_unknown_and_cannot_trigger_exit(self):
        for side in (-1,1):
            p=position(side);mark=100+side*8
            self.assertIsNone(pressure_exit(p,None,mark,{}))
            self.assertEqual(p['features']['exit_control_state']['phase'],'UNKNOWN')
