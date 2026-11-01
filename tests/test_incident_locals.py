"""Incident regressions: old H1 bias must not hide a new causal M15 reversal."""
import unittest
import threading
import time

from pandora_locals import live_locals, execution_anchor, entry_structure_valid
from pandora_bootstrap import HistoryBootstrap
from tests.test_pandora_restoration import bars, BASE, H


class IncidentLocalTests(unittest.TestCase):
    @staticmethod
    def context(mirror=False):
        history=bars()[:7]
        start=BASE+6*H
        now=BASE+7*H+31*60_000
        values=[(107,108,106,107),(106,107,105,106),(105,106,104,105),
                (104,105,103,104),(103,104,102,103),(103,105,103,104)]
        m15=[dict(t=start+i*900000,T=start+(i+1)*900000-1,o=o,h=h,l=l,c=c,v=10)
             for i,(o,h,l,c) in enumerate(values)]
        partial=dict(t=BASE+7*H,T=BASE+8*H-1,o=103,h=112,l=102,c=111,v=50,
                     observed_at_ms=now,low_observed_at_ms=BASE+7*H+1000)
        if mirror:
            history=[{**r,'o':200-r['o'],'h':200-r['l'],'l':200-r['h'],'c':200-r['c']} for r in history]
            m15=[{**r,'o':200-r['o'],'h':200-r['l'],'l':200-r['h'],'c':200-r['c']} for r in m15]
            partial={**partial,'o':200-partial['o'],'h':200-partial['l'],
                     'l':200-partial['h'],'c':200-partial['c']}
        return history+[partial],m15,now

    def test_new_m15_higher_low_can_replace_old_short_anchor_inside_pump(self):
        for mirror in (False,True):
            h1,m15,now=self.context(mirror)
            side=-1 if mirror else 1
            detailed=live_locals(h1,m15,now,'BTC')
            self.assertEqual(detailed['entry_side'],-side)
            self.assertTrue(detailed['entry_blocked'])
            self.assertEqual(detailed['m15_confirmed_local']['entry_side'],side)
            promoted=execution_anchor(detailed,dict(trade_data_fresh=True,sustained_control_side=side))
            self.assertEqual(promoted['entry_side'],side)
            self.assertFalse(promoted['entry_blocked'])
            self.assertEqual(promoted['confirmation_source'],'closed_M15_structure_and_executed_control')
            self.assertEqual(promoted['confirmed_local'],detailed['confirmed_local'])
            self.assertEqual(promoted['execution_local']['entry_side'],side)
            self.assertEqual(promoted['execution_local']['interval'],'15m')
            self.assertEqual(promoted['confirmed_local']['entry_side'],-side)
            self.assertGreater(promoted['signal_candle_time'],detailed['signal_candle_time'])
            self.assertTrue(entry_structure_valid(promoted,h1[-1]['c'],side))

    def test_new_m15_local_cannot_change_direction_without_fresh_matching_control(self):
        h1,m15,now=self.context()
        detailed=live_locals(h1,m15,now,'BTC')
        for flow in ({},{'trade_data_fresh':False,'sustained_control_side':1},
                     {'trade_data_fresh':True,'sustained_control_side':0},
                     {'trade_data_fresh':True,'sustained_control_side':-1}):
            result=execution_anchor(detailed,flow)
            self.assertEqual(result['entry_side'],-1)
            self.assertTrue(result['entry_blocked'])
            self.assertEqual(result['execution_local']['interval'],'1h')

    def test_old_reference_cannot_license_short_above_high_or_long_below_low(self):
        for side,pivot in ((-1,.01264),(1,100)):
            analysis=dict(entry_side=side,pivot_price=pivot,live_structure_fresh=True)
            self.assertFalse(entry_structure_valid(analysis,pivot*(1-side*.01),side))
            self.assertFalse(entry_structure_valid(analysis,pivot,side))
            self.assertTrue(entry_structure_valid(analysis,pivot*(1+side*.01),side))
            self.assertFalse(entry_structure_valid({**analysis,'entry_blocked':True},pivot*(1+side*.01),side))

    def test_future_m15_candle_cannot_confirm_reversal_early(self):
        h1,m15,now=self.context()
        earlier=m15[-1]['T']-1000
        result=live_locals(h1,m15,earlier,'BTC')
        prefix=live_locals(h1,m15[:-1],earlier,'BTC')
        self.assertEqual(result,prefix)
        self.assertIsNone(result['m15_confirmed_local'])

    def test_stale_or_gapped_m15_cannot_supply_new_execution_anchor(self):
        h1,m15,now=self.context()
        for rows,stamp in ((m15,now+1_020_000),(m15[:2]+m15[3:],now)):
            detailed=live_locals(h1,rows,stamp,'BTC')
            self.assertIsNone(detailed['m15_confirmed_local'])

    def test_extension_after_confirmation_invalidates_m15_reference(self):
        h1,m15,now=self.context()
        previous=m15[-1]
        broken=dict(t=previous['t']+900000,T=previous['T']+900000,
                    o=104,h=105,l=101,c=102,v=10)
        later=broken['T']+1001
        result=live_locals(h1,m15+[broken],later,'BTC')
        self.assertIsNone(result['m15_confirmed_local'])

    def test_stale_h1_observation_cannot_clear_entry_block_through_m15(self):
        h1,m15,now=self.context()
        h1[-1]['observed_at_ms']=now-16_000
        detailed=live_locals(h1,m15,now,'BTC')
        promoted=execution_anchor(detailed,dict(trade_data_fresh=True,sustained_control_side=1))
        self.assertEqual(promoted['entry_side'],-1)
        self.assertTrue(promoted['entry_blocked'])

    def test_retained_position_history_precedes_new_discovery_entries(self):
        stop=threading.Event();started=[];ready=set()
        def fetch(symbol,interval,limit):
            started.append((symbol,interval))
            return [dict(symbol=symbol,interval=interval)]
        def accept(rows,history=False):
            if rows[0]['interval']=='15m':ready.add(rows[0]['symbol'])
        worker=HistoryBootstrap(stop,fetch,accept,None,lambda *a:None,
            lambda s:s not in ready,lambda:['NEW'],lambda:['HELD'],lambda:[],
            selected_workers=1,background_workers=0,requests_per_second=1000,poll_interval=.01)
        thread=threading.Thread(target=worker.run,daemon=True);thread.start()
        try:
            end=time.monotonic()+2
            while 'NEW' not in ready and time.monotonic()<end:time.sleep(.005)
            self.assertEqual(ready,{'HELD','NEW'})
            self.assertEqual(started[0],('HELD','1h'))
        finally:
            stop.set();thread.join(3)
        self.assertFalse(thread.is_alive())
