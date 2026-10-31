"""Causal counter-movement behavior, including same-millisecond executions."""
import unittest
from local_order_flow import advance_structure
from market_data import RollingMarketData

class PressureStructureTests(unittest.TestCase):
    def test_fresh_extreme_absorbs_bounce_without_exit(self):
        for side in (-1,1):
            state={'best':side*100,'noise':0.}
            for n,(offset,control) in enumerate(((1,side),(.9,-side),(1.3,side)),1):
                state,exit_=advance_structure(state,side,100+side*offset,control,n)
                self.assertFalse(exit_)
            self.assertEqual(state['phase'],'HOLDING')
            self.assertAlmostEqual(state['noise'],.1)

    def test_failed_continuation_retest_confirms_exit_without_baseline(self):
        for side in (-1,1):
            state={'best':side*100,'noise':0.}
            for n,(offset,control,expected) in enumerate(((-.4,-side,False),(-.2,side,False),(-.5,-side,True)),1):
                state,exit_=advance_structure(state,side,100+side*offset,control,n)
                self.assertEqual(exit_,expected)
            self.assertEqual(state['confirmation_basis'],'failed_continuation_retest')

    def test_price_break_without_counter_executions_does_not_confirm(self):
        state={'best':100.,'noise':.1,'barrier':99.9}
        state,exit_=advance_structure(state,1,99,0,1)
        self.assertFalse(exit_)
        state,exit_=advance_structure(state,1,99,-1,2)
        self.assertTrue(exit_)

    def test_stale_event_cannot_rewrite_structure(self):
        state={'best':100.,'noise':.1,'barrier':99.9,'last_event_epoch':5}
        self.assertEqual(advance_structure(state,1,98,-1,4),(state,False))

    def test_equal_exchange_timestamp_distinct_trades_both_accepted(self):
        obs=RollingMarketData();obs.mark_connected(1000,['BTC'],owner='test')
        def row(price,ident):return dict(coin='BTC',px=str(price),sz='1',time=1001000,side='B',tid=ident)
        rows=[row(100,'a'),row(101,'b')];accepted=[]
        self.assertEqual(obs.ingest_trades(rows,1001.01,owner='test',accepted_rows=accepted),2)
        self.assertEqual(accepted,rows)
        self.assertEqual(obs.flow_context('BTC',1001.02)['last_price'],101)
        self.assertEqual(obs.ingest_trades(rows,1001.02,owner='test'),0)
