#!/usr/bin/env python3
"""Synthetic ledger consistency regressions. Not an exchange replay."""
import unittest
from test_d250_ledger_window import row
from d250_trade_replay_manifest_gate import audit

class LedgerConsistencyTests(unittest.TestCase):
    def test_stop_with_unlisted_opposite_confirmation_blocks(self):
        r=row()
        r["opposite_confirmed_utc"]="2026-07-01T06:00:00Z"
        self.assertIn("OPPOSITE_CONFIRMATION_LEDGER_MISMATCH",audit(r))

    def test_stop_with_disagreeing_first_opposite_blocks(self):
        r=row()
        r["opposite_ledger_first_utc"]="2026-07-01T06:00:00Z"
        r["opposite_confirmed_utc"]="2026-07-01T06:01:00Z"
        self.assertIn("OPPOSITE_CONFIRMATION_LEDGER_MISMATCH",audit(r))

    def test_opposite_confirmation_outside_ledger_blocks(self):
        r=row()
        r["opposite_confirmed_utc"]="2026-07-01T08:00:00Z"
        self.assertIn("OPPOSITE_CONFIRMATION_OUTSIDE_LEDGER_WINDOW",audit(r))

    def test_consistent_opposite_exit_passes(self):
        r=row()
        r["exit_reason"]="OPPOSITE_CONFIRMED"
        r["opposite_ledger_first_utc"]="2026-07-01T06:00:00Z"
        r["opposite_confirmed_utc"]="2026-07-01T06:00:00Z"
        self.assertEqual(audit(r),[])

    def test_short_consistent_opposite_exit_passes(self):
        r=row()
        r["side"]="SHORT";r["local_kind"]="HIGH"
        r["exit_reason"]="OPPOSITE_CONFIRMED"
        r["opposite_ledger_first_utc"]="2026-07-01T06:00:00Z"
        r["opposite_confirmed_utc"]="2026-07-01T06:00:00Z"
        self.assertEqual(audit(r),[])

if __name__=="__main__":
    unittest.main()
