"""Regressions for concrete audit failures; synthetic data, no profit fitting."""
import copy
import unittest
from accounting import paper_pnl,position_pnl
from local_order_flow import pressure_exit,update_watch,reentry_ready
from pandora_win_core import mark_metrics,apply_add,pyramid_decision
from pandora_mobile_monitor import render
from tests.test_control_hysteresis import flow
from tests.test_pandora_restoration import bars,BASE,H
from h1_structure import analyze


class FinalAuditTests(unittest.TestCase):
    def test_structural_break_is_retained_while_counter_timer_confirms(self):
        for side in (-1,1):
            # A failed continuation retest is confirmed once; equal later prices
            # must not erase it before the three-second control timer completes.
            p=dict(side=side,entry=100,features={'pressure_state':dict(
                best=side*100+10,noise=.1,phase='CHECK_CONTINUATION',
                candidate=dict(counter_extreme=side*100+8,retest_best=side*100+9))})
            mark=100+side*7
            self.assertIsNone(pressure_exit(p,None,mark,flow(-side,1000)))
            self.assertTrue(p['features']['pressure_state']['counter_structure_latched'])
            self.assertEqual(pressure_exit(p,None,mark,flow(-side,1003)),'confirmed_counter_move_exit')

    def test_stale_or_own_flow_clears_latched_structural_break(self):
        for interrupted in ({},flow(1,1001)):
            p=dict(side=1,entry=100,features={'pressure_state':dict(best=110,noise=.1,
                candidate=dict(counter_extreme=108,retest_best=109))})
            pressure_exit(p,None,107,flow(-1,1000));pressure_exit(p,None,107,interrupted)
            self.assertIsNone(pressure_exit(p,None,107,flow(-1,1003)))

    def test_reentry_confirmation_expires_on_new_counter_control(self):
        watch=dict(side=1,exit_price=100,context=dict(counter_pressure_seen=True,
            last_opposite_trade_epoch=1000,resumption_confirmed=True,confirmation_epoch=1003))
        self.assertTrue(reentry_ready(1,None,101,watch,flow(1,1004),1004))
        updated=update_watch(watch,99,None,flow(-1,1005),1005)
        self.assertFalse(reentry_ready(1,None,101,updated,flow(1,1006),1006))
        stale=update_watch(watch,99,None,{},1005)
        self.assertFalse(reentry_ready(1,None,101,stale,flow(1,1006),1006))

    def test_pyramid_cannot_add_against_fast_counterflow(self):
        pos=dict(side=1,entry=100,margin=100,notional=1000,features={})
        analysis=dict(anchor_confirmed=True,entry_side=1)
        tape=dict(trade_data_fresh=True,sustained_control_side=1,fast_control_side=-1,
            latest_trade_epoch=1000,windows={'15':dict(buy_volume=1000,volume_velocity=100)})
        allowed,state=pyramid_decision(pos,analysis,tape,110)
        self.assertFalse(allowed);self.assertEqual(state['phase'],'COUNTER_CONTROL_BLOCKS_ADD')

    def test_mfe_and_slippage_are_consistent_across_add_and_pullback(self):
        pos=dict(side=1,entry=100,margin=100,notional=1000,leverage=10,
                 features={'paper_slippage_fraction':.0002})
        before=mark_metrics(pos,110,{},{});peak=before['features']['peak_mfe_usd']
        updated,record=apply_add(before,110,50,{'latest_trade_epoch':1000},{},'now')
        self.assertEqual(record['segment_mfe_before_add'],peak)
        self.assertEqual(updated['features']['segment_mfe_usd'],0)
        for mark in (110,120,105):
            expected=position_pnl(pos,mark)+position_pnl(dict(side=1,entry=110,margin=50,
                notional=500,features=pos['features']),mark)
            self.assertAlmostEqual(position_pnl(updated,mark),expected)
        after=mark_metrics(updated,120,{},{});pulled=mark_metrics(after,105,{},{});
        self.assertEqual(pulled['features']['peak_mfe_usd'],after['features']['peak_mfe_usd'])
        self.assertGreater(pulled['features']['mfe_giveback_usd'],0)
        legacy={**pos,'features':{}}
        self.assertEqual(position_pnl(legacy,110),paper_pnl(1000,100,110,1))

    def test_h1_exposes_separate_last_high_and_low_without_future_bars(self):
        rows=bars();now=BASE+len(rows)*H+1001
        a=analyze(rows,now,'BTC')
        self.assertTrue(a['last_confirmed_high']);self.assertTrue(a['last_confirmed_low'])
        future=dict(t=now+H,T=now+2*H-1,o=100,h=9999,l=1,c=100,v=10)
        self.assertEqual(a,analyze(rows+[future],now,'BTC'))

    def test_mobile_is_readonly_vertical_and_does_not_claim_live_on_empty_state(self):
        page=render({'pandora':{'tokens':[{'symbol':'<script>alert(1)</script>'}]}})
        self.assertNotIn('<button',page);self.assertNotIn('<table',page);self.assertNotIn('LIVE DATA',page)
        self.assertNotIn('<script>alert(1)</script>',page)
        for text in ('DISCOVERY','ОТКРЫТЫЕ СДЕЛКИ','ИСТОРИЯ','WAIT / STALE','location.reload','minmax(0,40fr)'):
            self.assertIn(text,page)

    def test_liquidity_revalidated_during_locked_cohort(self):
        from pandora_scanner import LiveScanner
        from tests.test_incident_scanner import ticker,warm
        scanner=LiveScanner(top=1);warm(scanner)
        self.assertTrue(scanner.entry_liquidity_ready('OLD',1016))
        ticker(scanner,'OLD',1017,111,turnover=9_999_999)
        self.assertFalse(scanner.entry_liquidity_ready('OLD',1017))
        ticker(scanner,'OLD',1018,111,spread=.01)
        self.assertFalse(scanner.entry_liquidity_ready('OLD',1018))
        ticker(scanner,'OLD',1019,111)
        self.assertFalse(scanner.entry_liquidity_ready('OLD',1035))

    def test_pyramid_cannot_add_beyond_newer_same_side_local(self):
        pos=dict(side=1,entry=100,margin=100,notional=1000,features={})
        analysis=dict(anchor_confirmed=True,entry_side=1,pivot_price=115)
        tape=dict(trade_data_fresh=True,sustained_control_side=1,latest_trade_epoch=1000,
                  windows={'15':dict(buy_volume=1000,volume_velocity=100)})
        allowed,state=pyramid_decision(pos,analysis,tape,110)
        self.assertFalse(allowed);self.assertEqual(state['phase'],'LOCAL_REFERENCE_BROKEN_BY_MARK')
