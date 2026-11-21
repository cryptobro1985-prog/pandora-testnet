"""Regression tests for frozen D250 raw M1 pre-entry gate; synthetic only."""
import unittest
from datetime import datetime,timedelta,timezone
from d250_raw_m1_preentry_gate_20261121 import audit
T=datetime(2026,11,1,12,tzinfo=timezone.utc)
def iso(t): return t.isoformat()
def trade(side="LONG"):
    return dict(side=side,local_type="LOW" if side=="LONG" else "HIGH",
      local_extreme_utc=iso(T),local_extreme_price="100",
      h1_confirmed_utc=iso(T+timedelta(hours=2)),
      d250_signal_utc=iso(T+timedelta(minutes=250)),
      entry_utc=iso(T+timedelta(minutes=251)))
def bars(side="LONG"):
    return [dict(utc=iso(T+timedelta(minutes=i)),
      closed_utc=iso(T+timedelta(minutes=i+1)),
      low="100",high="100") for i in range(251)]
class TestM1(unittest.TestCase):
    def test_complete_long(self): self.assertEqual(audit(trade(),bars()),[])
    def test_complete_short(self): self.assertEqual(audit(trade("SHORT"),bars("SHORT")),[])
    def test_out_of_order_normalized(self):
        b=bars();b[1],b[2]=b[2],b[1]
        self.assertEqual(audit(trade(),b),[])
    def test_anchor_ambiguity_long(self):
        b=bars();b[0]["low"]="99.5"
        self.assertIn("INDETERMINATE_ANCHOR_TICK_ORDER",audit(trade(),b))
    def test_anchor_ambiguity_short(self):
        b=bars();b[0]["high"]="101"
        self.assertIn("INDETERMINATE_ANCHOR_TICK_ORDER",audit(trade("SHORT"),b))
    def test_later_extension(self):
        b=bars();b[100]["low"]="99"
        self.assertIn("LOW_EXTENDED_BEFORE_ENTRY",audit(trade(),b))
    def test_duplicate(self):
        b=bars();b.append(dict(b[100]))
        self.assertIn("M1_GAP_OR_DUPLICATE",audit(trade(),b))
    def test_gap(self):
        b=bars();b.pop(100)
        self.assertIn("M1_GAP_OR_DUPLICATE",audit(trade(),b))
    def test_intraminute(self):
        t=trade();t["entry_utc"]=iso(T+timedelta(minutes=250,seconds=30))
        self.assertIn("INTRAMINUTE_ENTRY_NEEDS_TICKS",audit(t,bars()))
if __name__=="__main__": unittest.main()
