#!/usr/bin/env python3
"""Synthetic chronology regression tests, NOT market-event replay."""
import unittest
from datetime import datetime, timedelta, timezone
from d250_trade_replay_manifest_gate import audit

BASE=datetime(2026,7,12,tzinfo=timezone.utc)
def iso(minutes): return (BASE+timedelta(minutes=minutes)).isoformat()
def row(reason="STOP",opposite=""):
    return dict(trade_id="synthetic-1",side="LONG",local_kind="LOW",
        local_extreme_utc=iso(0),h1_confirmed_utc=iso(60),
        d250_signal_utc=iso(250),entry_utc=iso(251),
        entry_price="100",exit_utc=iso(310),exit_price="99",
        exit_reason=reason,opposite_confirmed_utc=opposite,
        rev_atr="2.2",trade_ratio5="0.3",flow15="0.4",
        rev_atr_asof_utc=iso(250),trade_ratio5_asof_utc=iso(250),
        flow15_asof_utc=iso(250),m1_coverage="COMPLETE",
        public_trades_coverage="COMPLETE",mark_coverage="COMPLETE")
class GateTests(unittest.TestCase):
    def test_stop_no_future_opposite(self):
        self.assertEqual(audit(row()),[])
    def test_stop_before_future_opposite(self):
        self.assertEqual(audit(row(opposite=iso(500))),[])
    def test_opposite_missing(self):
        self.assertIn("MISSING_OPPOSITE_CONFIRMATION",audit(row("OPPOSITE_CONFIRMED")))
    def test_opposite_early_exit(self):
        self.assertIn("EXIT_BEFORE_OPPOSITE_CONFIRMATION",audit(row("OPPOSITE_CONFIRMED",iso(500))))
    def test_opposite_confirmed(self):
        self.assertEqual(audit(row("OPPOSITE_CONFIRMED",iso(300))),[])
    def test_opposite_before_entry_is_invalid(self):
        r=row("OPPOSITE_CONFIRMED",iso(250))
        self.assertIn("OPPOSITE_PRECEDES_SIGNAL",audit(r))
    def test_opposite_at_entry_is_valid(self):
        r=row("OPPOSITE_CONFIRMED",iso(251))
        self.assertEqual(audit(r),[])
    def test_stop_before_entry(self):
        r=row();r["exit_utc"]=iso(249)
        self.assertIn("NONCAUSAL_SEQUENCE",audit(r))
    def test_future_feature(self):
        r=row();r["flow15_asof_utc"]=iso(251)
        self.assertIn("FUTURE_FEATURE_FLOW15",audit(r))
    def test_side_mismatch(self):
        r=row();r["side"]="SHORT"
        self.assertIn("SIDE_LOCAL_MISMATCH",audit(r))
if __name__=="__main__": unittest.main()
