import unittest
from unittest.mock import patch
from hype_h1_swing import analyze,position_exit,m15_reentry_ready,m15_reentry_after_exit
import app

H=3600000

def history(side=1):
    values=[(100,102,95,99),(99,101,94,98),(98,100,93,97),(97,99,92,96),(96,98,85,89),(89,96,87,95)]
    if side<0:values=[(200-o,200-l,200-h,200-c) for o,h,l,c in values]
    return [dict(t=i*H,T=(i+1)*H-1,o=o,h=h,l=l,c=c,v=100) for i,(o,h,l,c) in enumerate(values)]


class H1DirectionTests(unittest.TestCase):
    def test_confirmed_hourly_low_and_high_define_opposite_sides(self):
        for side in (-1,1):
            rows=history(side);r=analyze(rows,6*H+1001,'HYPE')
            self.assertEqual(r['entry_side'],side)
            self.assertEqual(r['interval'],'1h')
            self.assertTrue(r['h1_direction_anchor'])
            self.assertEqual(r['pivot_candle_time'],4*H)

    def test_unclosed_candidate_does_not_reveal_future_pivot(self):
        rows=history();r=analyze(rows,5*H-2000)
        self.assertFalse(r.get('anchor_confirmed',False))
        self.assertNotEqual(r.get('entry_side'),1)

    def test_bias_survives_new_hour_without_new_extreme(self):
        rows=history();rows.append(dict(t=6*H,T=7*H-1,o=95,h=97,l=94,c=96,v=100))
        r=analyze(rows,7*H+1001)
        self.assertEqual((r['entry_side'],r['signal_candle_time']),(1,4*H))
        self.assertEqual(r['last_candle_time'],6*H)

    def test_init_like_closed_h1_rejection_confirms_low_without_extra_right_hour(self):
        # Mirrors the 2026-10-30 INIT structure: the candidate H1 low closed
        # 4.4% above its own extreme, stronger than the 3.5% capped threshold.
        values=[
            (.21628,.22298,.21447,.21551),
            (.21403,.21475,.20500,.20750),
            (.20810,.20895,.19450,.19578),
            (.19578,.20141,.17849,.18063),
            (.18063,.19855,.17380,.18151),
        ]
        rows=[dict(t=i*H,T=(i+1)*H-1,o=o,h=h,l=l,c=cl,v=100)
              for i,(o,h,l,cl) in enumerate(values)]
        r=analyze(rows,5*H+1001,'INIT')
        self.assertTrue(r['anchor_confirmed'])
        self.assertEqual(r['entry_side'],1)
        self.assertEqual(r['pivot_type'],'LOCAL_LOW')
        self.assertEqual(r['pivot_candle_time'],4*H)
        self.assertEqual(r['signal_candle_time'],4*H)
        self.assertEqual(r['confirmation_bars'],0)
        self.assertGreater(r['confirmation_retrace'],r['required_retrace'])

    def test_opposite_confirmed_h1_pivot_changes_direction(self):
        rows=history();values=[(95,104,94,102),(102,110,101,108),(108,109,100,102)]
        for i,(o,h,l,c) in enumerate(values,6):rows.append(dict(t=i*H,T=(i+1)*H-1,o=o,h=h,l=l,c=c,v=100))
        r=analyze(rows,9*H+1001)
        self.assertEqual(r['entry_side'],-1)
        pos=dict(entry=95.,side=1,signal_candle_time=5*H)
        self.assertEqual(position_exit(pos,r,102.),'opposite_local_high')

    def test_m15_opposite_pressure_cannot_reverse_h1_position(self):
        for side in (-1,1):
            pos=dict(entry=100.,side=side,signal_candle_time=H,features={'mfe_price_move':.02})
            r=dict(ready=True,h1_direction_anchor=True,entry_side=side,signal_candle_time=H,
                   local_high=side<0,local_low=side>0,long_weakening=True,short_weakening=True)
            self.assertIsNone(position_exit(pos,r,100.))
            self.assertFalse(m15_reentry_ready(side,dict(ready=True,recovery_confirmed=False),.5*side))
            self.assertTrue(m15_reentry_ready(side,dict(ready=True,recovery_confirmed=True,recovery_score=4),.5*side))

    def test_entry_mutation_rejects_direction_against_hourly_anchor(self):
        r=dict(ready=True,h1_direction_anchor=True,entry_side=-1)
        with patch.object(app,'current_entry_price') as price:
            self.assertFalse(app.local_swing_open('HYPE',1,r))
        price.assert_not_called()

    def test_reentry_requires_actual_resumption_after_exit_for_both_sides(self):
        recovery=dict(ready=True,recovery_confirmed=True,recovery_score=4)
        for side in (-1,1):
            watch=dict(exit_price=100.)
            self.assertFalse(m15_reentry_after_exit(side,recovery,100.,watch))
            self.assertFalse(m15_reentry_after_exit(side,recovery,100-side*.2,watch))
            self.assertTrue(m15_reentry_after_exit(side,recovery,100+side*.2,watch))

    def test_persisted_anchor_used_when_history_contains_no_new_pivot(self):
        prior=dict(ready=True,h1_direction_anchor=True,entry_side=-1,signal_candle_time=H)
        with patch.dict(app.S,local_h1_direction={'NEAR':prior}):
            with patch.object(app,'analyze_hype_h1',return_value=dict(ready=True,anchor_confirmed=False,last_candle_time=8*H)):
                self.assertEqual(app.local_h1_direction([],0,'NEAR')['entry_side'],-1)
