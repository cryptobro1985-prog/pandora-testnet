#!/usr/bin/env python3
"""Fast deterministic regression checks for frozen paper risk replay."""
import unittest
import numpy as np
from research.hype_unified_intelligence.paper_risk_replay_v1 import replay,stress

def sample_bar(i,op=100.0,hi=100.1,lo=99.9,cl=100.0,gap=False):
    return {"bar_end_ms":(i+1)*60000,"open":op,"high":hi,"low":lo,
            "close":cl,"gap":gap,"buy_notional":100,"sell_notional":50}

class ReplayTest(unittest.TestCase):
    def _run(self,adjust=None,probs=None):
        rows=[sample_bar(i) for i in range(9)]
        if adjust: adjust(rows)
        dat={"t":np.array([rows[2]["bar_end_ms"]],dtype=np.int64)}
        if probs is None:probs=np.array([[.92,.08]],dtype=float)
        return replay(rows,dat,probs,"fixed")

    def test_next_open_and_take_profit(self):
        def fix(rows):
            rows[3].update(open=100.0,high=100.10,low=99.95,close=100.05)
            rows[4].update(open=100.05,high=100.8,low=100.0,close=100.3)
        tt=self._run(fix)
        self.assertEqual(len(tt),1)
        self.assertEqual(tt[0]["entry"],100.0)
        self.assertAlmostEqual(tt[0]["exit"],100.5,places=5)
        self.assertEqual(tt[0]["reason"],"TAKE_PROFIT")
        self.assertAlmostEqual(tt[0]["net"],.0038,places=5)

    def test_same_bar_stop_has_priority(self):
        def fix(rows):
            rows[3].update(open=100.0,high=101.0,low=99.0,close=100.0)
        tt=self._run(fix)
        self.assertEqual(len(tt),1)
        self.assertEqual(tt[0]["reason"],"HARD_STOP")
        self.assertAlmostEqual(tt[0]["exit"],99.65,places=5)

    def test_gap_open_fills_worse_than_stop(self):
        def fix(rows):
            # The entry is filled at bar 3 OPEN = 100. The next minute
            # then gaps below its 99.65 stop and must fill at 98.
            rows[3].update(open=100.0,high=100.1,low=99.95,close=100.0)
            rows[4].update(open=98.0,high=99.0,low=97.0,close=98.5)
        tt=self._run(fix)
        self.assertEqual(tt[0]["reason"],"HARD_STOP")
        self.assertAlmostEqual(tt[0]["exit"],98.0)
        self.assertTrue(tt[0]["unverified_fill"])

    def test_no_trade_without_score(self):
        self.assertEqual(self._run(probs=np.array([[.55,.45]])),[])

    def test_margin_times_leverage(self):
        t=dict(net=-.01,mae=.02,worst=.02)
        low=stress([t],L=5,margin=.02)
        high=stress([t],L=25,margin=.20)
        self.assertAlmostEqual(low["equity_return_pct"],-.1)
        self.assertAlmostEqual(high["equity_return_pct"],-5.0)
        self.assertEqual(low["approx_liquidations"],0)
        self.assertEqual(high["approx_liquidations"],0)

    def test_approx_liquidation_25x(self):
        t=dict(net=-.01,mae=.045,worst=.045)
        r=stress([t],L=25,margin=.20)
        self.assertEqual(r["approx_liquidations"],1)
        self.assertAlmostEqual(r["equity_return_pct"],-20.)

if __name__=="__main__":unittest.main()
