#!/usr/bin/env python3
"""Deterministic, isolated tests for research-only policy state transitions."""
import unittest
from research.hype_unified_intelligence.state_machine import ResearchStateMachine

def sample(t, price=100.0, **kwargs):
    base={
        "ts_ms":t,"data_ts_ms":t,"data_quality_ok":True,"book_valid":True,
        "price":price,"regime":"BEAR","gap_seconds":0,
        "long_score":.80,"short_score":.15,
        "long_net_edge":.004,"short_net_edge":.0001,
        "long_predicted_mfe":.012,"long_predicted_mae":.003,
        "short_predicted_mfe":.002,"short_predicted_mae":.002,
        "own_price_impact":1.0,"opposite_price_impact":.0,
        "realized_volatility_60m":.003
    }
    base.update(kwargs)
    return base

class PolicyTest(unittest.TestCase):
    def test_long_entry_and_research_only(self):
        m=ResearchStateMachine()
        r=m.evaluate(sample(1000000))
        self.assertEqual(r["state"],"LONG")
        self.assertIs(r["real_orders"],False)

    def test_small_correction_keeps_hold(self):
        m=ResearchStateMachine()
        m.evaluate(sample(1000000))
        m.evaluate(sample(1300000,price=102.0))
        r=m.evaluate(sample(1600000,price=101.1,short_score=.40))
        self.assertEqual(r["state"],"HOLD")
        self.assertEqual(r["reason_codes"],["HEALTHY_CORRECTION"])
        self.assertAlmostEqual(r["mfe"],.02)

    def test_no_flip_on_one_tick(self):
        m=ResearchStateMachine(sustained_count=3)
        m.evaluate(sample(1000000))
        m.evaluate(sample(1300000,price=102.0))
        r=m.evaluate(sample(1600000,price=101.0,
            long_score=.24,short_score=.90,short_net_edge=.006,
            short_predicted_mfe=.02,short_predicted_mae=.003,
            own_price_impact=-1,opposite_price_impact=1))
        self.assertEqual(r["state"],"HOLD")
        self.assertEqual(r["opposing_persistence"],1)

    def test_sustained_opposition_flip(self):
        m=ResearchStateMachine(sustained_count=3)
        m.evaluate(sample(1000000))
        m.evaluate(sample(1300000,price=102.0))
        res=None
        for n in range(3):
            res=m.evaluate(sample(1600000+n*60000,price=101-n*.2,
                long_score=.24,short_score=.93,short_net_edge=.006,
                short_predicted_mfe=.02,short_predicted_mae=.003,
                own_price_impact=-1,opposite_price_impact=1))
        self.assertEqual(res["state"],"FLIP")
        self.assertEqual(res["side"],"SHORT")
        self.assertEqual(len(m.events),1)
        self.assertEqual(m.events[0]["exit_reason"],"SUSTAINED_OPPOSITE_TRANSFER_FLIP")

    def test_data_stale_closes(self):
        m=ResearchStateMachine()
        m.evaluate(sample(1000000))
        r=m.evaluate(sample(1600000,price=102.0,data_ts_ms=1580000))
        self.assertEqual(r["state"],"CLOSE")
        self.assertEqual(r["reason_codes"],["DATA_QUALITY_FAIL"])

    def test_no_entry_with_negative_edge(self):
        m=ResearchStateMachine()
        r=m.evaluate(sample(1000000,long_net_edge=-.0001))
        self.assertEqual(r["state"],"FLAT")

    def test_exit_recoil_requires_real_transfer(self):
        m=ResearchStateMachine(sustained_count=2)
        m.evaluate(sample(1000000))
        m.evaluate(sample(1300000,price=104.0))
        r=m.evaluate(sample(1600000,price=100.0,long_score=.80,short_score=.1))
        self.assertEqual(r["state"],"HOLD")
        r=m.evaluate(sample(1660000,price=99.8,long_score=.2,short_score=.82,
                            short_net_edge=0.0,opposite_price_impact=1.0,
                            own_price_impact=-1.0))
        self.assertEqual(r["state"],"HOLD")
        r=m.evaluate(sample(1720000,price=99.7,long_score=.2,short_score=.82,
                            short_net_edge=0.0,opposite_price_impact=1.0,
                            own_price_impact=-1.0))
        self.assertEqual(r["state"],"CLOSE")
        self.assertEqual(r["reason_codes"],["TRANSFER_AND_MFE_OR_EDGE_DECAY"])

    def test_cooldown(self):
        m=ResearchStateMachine()
        m.evaluate(sample(1000000))
        m.evaluate(sample(1001000,data_quality_ok=False))
        r=m.evaluate(sample(1002000))
        self.assertEqual(r["state"],"FLAT")
        self.assertEqual(r["reason_codes"],["ENTRY_COOLDOWN"])

if __name__=="__main__":
    unittest.main()
