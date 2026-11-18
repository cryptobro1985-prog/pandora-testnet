#!/usr/bin/env python3
"""Adversarial synthetic tests for manifest gate; no historical performance claims."""
import unittest
from d250_trade_replay_manifest_gate import audit

def row():
    return dict(trade_id="synthetic",side="LONG",local_kind="LOW",
      local_extreme_utc="2026-07-01T00:00:00Z",
      h1_confirmed_utc="2026-07-01T01:00:00Z",
      d250_signal_utc="2026-07-01T04:20:00Z",
      entry_utc="2026-07-01T04:21:00Z",exit_utc="2026-07-01T07:00:00Z",
      entry_price="100",exit_price="99",exit_reason="STOP",
      rev_atr="3",trade_ratio5="0.4",flow15="0.2",
      rev_atr_asof_utc="2026-07-01T04:19:00Z",
      trade_ratio5_asof_utc="2026-07-01T04:19:00Z",
      flow15_asof_utc="2026-07-01T04:19:00Z",
      m1_coverage="COMPLETE",public_trades_coverage="COMPLETE",
      mark_coverage="COMPLETE",opposite_ledger_coverage="COMPLETE",
      opposite_ledger_first_utc="NONE",
      opposite_ledger_start_utc="2026-07-01T04:20:00Z",
      opposite_ledger_end_utc="2026-07-01T07:01:00Z")

class GateTests(unittest.TestCase):
    def test_complete_window_candidate(self):
        self.assertEqual(audit(row()),[])
    def test_late_start_blocks(self):
        x=row();x["opposite_ledger_start_utc"]="2026-07-01T04:22:00Z"
        self.assertIn("OPPOSITE_LEDGER_WINDOW_INCOMPLETE",audit(x))
    def test_early_end_blocks(self):
        x=row();x["opposite_ledger_end_utc"]="2026-07-01T06:59:00Z"
        self.assertIn("OPPOSITE_LEDGER_WINDOW_INCOMPLETE",audit(x))
    def test_reversed_window_blocks(self):
        x=row();x["opposite_ledger_start_utc"]="2026-07-01T08:00:00Z"
        self.assertIn("OPPOSITE_LEDGER_WINDOW_INCOMPLETE",audit(x))
    def test_ledger_event_outside_window_blocks(self):
        x=row();x["opposite_ledger_first_utc"]="2026-07-01T08:00:00Z"
        self.assertIn("OPPOSITE_LEDGER_EVENT_OUTSIDE_WINDOW",audit(x))
    def test_opposite_before_stop_blocks(self):
        x=row();x["opposite_ledger_first_utc"]="2026-07-01T06:00:00Z"
        self.assertIn("STOP_NOT_PROVEN_BEFORE_LEDGER_OPPOSITE",audit(x))
    def test_missing_window_blocks(self):
        x=row();del x["opposite_ledger_end_utc"]
        self.assertTrue(any("INVALID_OR_MISSING_FIELD" in y for y in audit(x)))
    def test_short_candidate(self):
        x=row();x["side"]="SHORT";x["local_kind"]="HIGH"
        self.assertEqual(audit(x),[])

if __name__=="__main__": unittest.main()
