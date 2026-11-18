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
        public_trades_coverage="COMPLETE",mark_coverage="COMPLETE",
        opposite_ledger_coverage="COMPLETE",
        opposite_ledger_first_utc=opposite if opposite else "NONE",
        opposite_ledger_start_utc=iso(249),opposite_ledger_end_utc=iso(501))
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
    def test_opposite_at_entry_is_invalid(self):
        r=row("OPPOSITE_CONFIRMED",iso(251))
        self.assertIn("OPPOSITE_PRECEDES_SIGNAL",audit(r))
    def test_opposite_exit_same_timestamp_is_invalid(self):
        r=row("OPPOSITE_CONFIRMED",iso(310))
        self.assertIn("EXIT_BEFORE_OPPOSITE_CONFIRMATION",audit(r))
    def test_opposite_exit_after_confirmation_is_valid(self):
        r=row("OPPOSITE_CONFIRMED",iso(309))
        self.assertEqual(audit(r),[])
    def test_stop_after_known_opposite_is_invalid(self):
        r=row(opposite=iso(300))
        self.assertIn("STOP_NOT_PROVEN_BEFORE_OPPOSITE_CONFIRMATION",audit(r))
    def test_stop_with_opposite_before_entry_is_invalid(self):
        r=row(opposite=iso(250))
        self.assertIn("OPPOSITE_PRECEDES_SIGNAL",audit(r))
    def test_stop_before_opposite_is_valid(self):
        self.assertEqual(audit(row(opposite=iso(500))),[])
    def test_stop_same_timestamp_as_opposite_is_blocked(self):
        r=row(opposite=iso(310))
        self.assertIn("STOP_NOT_PROVEN_BEFORE_LEDGER_OPPOSITE",audit(r))
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
