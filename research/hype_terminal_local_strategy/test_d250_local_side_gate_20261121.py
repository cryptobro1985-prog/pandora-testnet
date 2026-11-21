#!/usr/bin/env python3
"""Regression tests for H1 terminal local direction binding (synthetic, not historical replay)."""
import unittest
from datetime import datetime, timedelta, timezone
from d250_raw_m1_preentry_gate_20261121 import audit

T=datetime(2026,7,12,0,0,tzinfo=timezone.utc)
def iso(t): return t.isoformat()
def case(side,local_type):
    trade={"trade_id":"synthetic","side":side,"local_type":local_type,
           "local_extreme_utc":iso(T),"local_extreme_price":"100",
           "h1_confirmed_utc":iso(T+timedelta(hours=2)),
           "d250_signal_utc":iso(T+timedelta(minutes=250)),
           "entry_utc":iso(T+timedelta(minutes=251))}
    bars=[{"utc":iso(T+timedelta(minutes=i)),
           "closed_utc":iso(T+timedelta(minutes=i+1)),
           "high":"100","low":"100"} for i in range(1,251)]
    return audit(trade,bars)
class DirectionBinding(unittest.TestCase):
    def test_long_low(self): self.assertEqual(case("LONG","LOW"),[])
    def test_short_high(self): self.assertEqual(case("SHORT","HIGH"),[])
    def test_long_high_rejected(self): self.assertIn("LOCAL_SIDE_MISMATCH",case("LONG","HIGH"))
    def test_short_low_rejected(self): self.assertIn("LOCAL_SIDE_MISMATCH",case("SHORT","LOW"))
    def test_unknown_local_rejected(self): self.assertIn("INVALID_LOCAL_TYPE",case("LONG","OTHER"))
if __name__=="__main__": unittest.main()
