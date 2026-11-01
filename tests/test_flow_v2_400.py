"""Flow V2 behavior contracts: both directions, event-only confirmation, top5."""
import copy, os, unittest
from unittest.mock import patch

from pandora_flow_v2_live import current_side,entry_candidate,exit_reason,analysis_for_flow
from pandora_scanner import LiveScanner

def control(side,event=1000):
    return dict(trade_data_fresh=True,evidence_ready=True,trade_coverage_seconds=32,
        sustained_control_side=side,fast_control_side=side,context_control_side=side,
        exit_control_side=side,flow_imbalance=.7*side,price_direction=side,
        buy_absorbed=False,sell_absorbed=False,decision_event_epoch=event,
        buy_notional=850 if side>0 else 150,
        sell_notional=150 if side>0 else 850)

class FlowV2Contracts(unittest.TestCase):
    def test_direction_chosen_from_flow_not_prior_pump(self):
        for side in (-1,1):
            c=entry_candidate("HOT",control(side))
            self.assertTrue(c['eligible'])
            self.assertEqual(c['side'],side)
            self.assertEqual(current_side(control(side)),side)

    def test_no_entry_on_stale_or_absorbed_tape(self):
        for side in (-1,1):
            stale=control(side);stale['trade_data_fresh']=False
            self.assertEqual(current_side(stale),0)
            absorbed=control(side);absorbed['buy_absorbed' if side>0 else 'sell_absorbed']=True
            self.assertEqual(current_side(absorbed),0)

    def test_long_microcorrection_holds(self):
        p=dict(entry=100.,side=1,features={})
        for e in range(1000,1007):
            c=control(1,e);c['fast_control_side']=-1
            self.assertIsNone(exit_reason(p,99.99,c))
        self.assertNotEqual(p['features']['exit_control_state']['phase'],'OBSERVING')

    def test_short_microbounce_holds(self):
        p=dict(entry=100.,side=-1,features={})
        for e in range(1000,1007):
            c=control(-1,e);c['fast_control_side']=1
            self.assertIsNone(exit_reason(p,100.01,c))

    def test_real_counter_takeover_exits_after_distinct_executions(self):
        for side in (-1,1):
            p=dict(entry=100.,side=side,features={})
            for i in range(2):
                self.assertIsNone(exit_reason(p,100-side*.5,control(-side,1000+i)))
            self.assertEqual(exit_reason(p,100-side*.5,control(-side,1002)),
                'confirmed_counter_move_exit')

    def test_repoll_same_exchange_event_does_not_exit(self):
        p=dict(entry=100.,side=1,features={})
        for _ in range(100):
            self.assertIsNone(exit_reason(p,99.,control(-1,1000)))
        self.assertEqual(p['features']['exit_control_state']['new_trade_count'],1)

    def test_exit_no_h1_local_requirement(self):
        state=analysis_for_flow(1,control(1),100.)
        self.assertIsNone(state['pivot_price'])
        self.assertFalse(state['h1_direction_anchor'])
        self.assertEqual(state['confirmation_source'],'EXECUTED_PUBLIC_TRADES_ONLY')

    def test_new_entry_must_follow_last_exit_execution(self):
        self.assertFalse(entry_candidate('HOT',control(-1,1000),last_exit_event=1000)['eligible'])
        self.assertTrue(entry_candidate('HOT',control(-1,1001),last_exit_event=1000)['eligible'])

    def test_hourly_selection_and_minimum_turnover(self):
        with patch.dict(os.environ,{'PANDORA_FLOW_V2':'1'}):
            sc=LiveScanner()
            instruments={s:{} for s in ['A','B','C','D','E','F','G','LOW']}
            def feed(epoch,change):
                for i,s in enumerate(instruments):
                    sc.ingest(dict(symbol=s+'USDT',lastPrice='1',turnover24h='900000' if s=='LOW' else '2000000',
                        price24hPcnt=str(change.get(s,.01))),int(epoch*1000),received=epoch)
            feed(1000,{s:.06-i*.01 for i,s in enumerate(instruments)})
            a=sc.rank(instruments,lambda *_:{},(),1000)
            self.assertEqual(len(a['selected_symbols']),5)
            self.assertNotIn('LOW',a['selected_symbols'])
            self.assertEqual(a['next_refresh_at'],4600)
            old=a['selected_symbols']
            feed(1010,{'G':.99,'F':.98})
            b=sc.rank(instruments,lambda *_:{},(),1010)
            self.assertEqual(b['selected_symbols'],old)
            feed(4601,{'G':.99,'F':.98})
            c=sc.rank(instruments,lambda *_:{},(old[0],),4601)
            self.assertIn('G',c['selected_symbols'])
            self.assertEqual(c['selected_at'],4601)
            self.assertEqual(c['next_refresh_at'],8201)
            self.assertEqual(c['retained_open_positions'],
                sorted(set([old[0]])-set(c['selected_symbols'])))

    def test_hourly_restart_persists_universe(self):
        with patch.dict(os.environ,{'PANDORA_FLOW_V2':'1'}):
            a=LiveScanner()
            a.restore(dict(selected_symbols=['A','B','C','D','E'],selected_at=1000,
               next_refresh_at=4600,experiment='PANDORA_FLOW_V2_400',selected=[]))
            result=a.rank({},lambda *_:{},(),1200)
            self.assertEqual(result['selected_symbols'],['A','B','C','D','E'])
            self.assertEqual(result['next_refresh_at'],4600)

if __name__=='__main__':unittest.main()
