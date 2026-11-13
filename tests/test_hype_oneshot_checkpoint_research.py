"""Standalone regression tests for frozen 285-minute one-shot H1 gate."""
import unittest
from research.hype_terminal_local_strategy.h1_checkpoint_oneshot_research import Candidate, extend, observe

M = 60_000
class TestH1Checkpoint(unittest.TestCase):
    def test_failed_low_cannot_cross_late(self):
        c = Candidate("LOW", 0, 100, 150)
        self.assertEqual(observe(c, 285*M, 101), "FALSE")
        self.assertEqual(observe(c, 286*M, 103), "WAIT")
    def test_low_true_only_once(self):
        c = Candidate("LOW", 0, 100, 150)
        self.assertEqual(observe(c, 285*M, 102), "TRUE")
        self.assertEqual(observe(c, 286*M, 103), "WAIT")
    def test_high_true(self):
        self.assertEqual(observe(Candidate("HIGH",0,100,150),285*M,98),"TRUE")
    def test_extension_resets_candidate(self):
        c=extend(Candidate("LOW",0,100,150),180*M,99,140)
        self.assertEqual(c.lineage,1)
        self.assertEqual(observe(c,285*M,102),"WAIT")
        self.assertEqual(observe(c,465*M,101),"TRUE")
    def test_late_price_observation_rejected(self):
        self.assertEqual(observe(Candidate("LOW",0,100,150),287*M,110),"MISSED")
    def test_future_available_snapshot_rejected(self):
        c=Candidate("LOW",0,100,150)
        self.assertEqual(observe(c,285*M,102,snapshot_available_ts_ms=290*M),"MISSED")
    def test_premature_does_not_consume(self):
        c=Candidate("LOW",0,100,150)
        self.assertEqual(observe(c,284*M,105),"WAIT")
        self.assertEqual(observe(c,285*M,102),"TRUE")
    def test_invalid_price(self):
        self.assertEqual(observe(Candidate("LOW",0,100,150),285*M,0),"MISSED")

if __name__ == "__main__":
    unittest.main()
