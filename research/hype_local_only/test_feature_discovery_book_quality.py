#!/usr/bin/env python3
"""Live L50 quality guard must fail closed on crossed book."""
import unittest
from types import SimpleNamespace
from research.hype_local_only.feature_discovery import _book_features

def book(bids=None,asks=None):
    return SimpleNamespace(book_bids=bids or {},book_asks=asks or {},
        last_ts_ms=1700000000000,book_changes=[])

class LiveBookQualityTest(unittest.TestCase):
    def test_crossed_is_not_zero_spread(self):
        f=_book_features(book({100.2:3,100.1:2},{100.0:4,100.3:2}),100.1,"LOW")
        self.assertEqual(f["book_quality_valid"],0.)
        self.assertEqual(f["book_quality_crossed_or_locked"],1.)
        self.assertNotIn("book_spread_bps",f)
        self.assertFalse(any(k.startswith("book_depth_") for k in f))
    def test_locked_is_invalid(self):
        f=_book_features(book({100.0:3},{100.0:2}),100.0,"HIGH")
        self.assertEqual(f["book_quality_valid"],0.)
    def test_uncrossed_book_remains_usable(self):
        f=_book_features(book({100.0:3},{100.02:2}),100.01,"LOW")
        self.assertEqual(f["book_quality_valid"],1.)
        self.assertGreater(f["book_spread_bps"],0)
        self.assertIn("book_microprice_dist_bps",f)
    def test_stale_last_trade_outside_book_not_crossed(self):
        f=_book_features(book({100.2:3},{100.3:2}),100.0,"LOW")
        self.assertEqual(f["book_quality_valid"],1.)
    def test_missing_is_masked_not_zero_filled(self):
        f=_book_features(book({},{}),100.0,"LOW")
        self.assertEqual(f,{"book_quality_valid":0.0})
    def test_malformed_qty_is_masked(self):
        f=_book_features(book({100.0:-1},{100.1:2}),100.0,"HIGH")
        self.assertEqual(f["book_quality_valid"],0.)
        self.assertNotIn("book_spread_bps",f)

if __name__=="__main__": unittest.main()
