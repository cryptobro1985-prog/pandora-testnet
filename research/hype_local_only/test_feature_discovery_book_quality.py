#!/usr/bin/env python3
"""Live L50 quality guard must fail closed on crossed book."""
import unittest
from types import SimpleNamespace
from research.hype_local_only.feature_discovery import _book_features, _liq_features

def book(bids=None,asks=None):
    return SimpleNamespace(book_bids=bids or {},book_asks=asks or {},
        last_ts_ms=1700000000000,book_ts_ms=1700000000000,book_changes=[])

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
    def test_untimestamped_quote_fails_closed(self):
        q=book({100.0:3},{100.1:2})
        del q.book_ts_ms
        f=_book_features(q,100.05,"LOW")
        self.assertEqual(f,{"book_quality_valid":0.0,"book_quality_timestamp_missing":1.0})
        self.assertNotIn("book_depth_imbalance_5",f)

    def test_timestamped_stale_book_is_masked(self):
        q=book({100.0:3},{100.1:2})
        q.book_ts_ms=q.last_ts_ms-5001
        f=_book_features(q,100.05,"LOW")
        self.assertEqual(f,{"book_quality_valid":0.0,"book_quality_stale":1.0})

    def test_future_timestamped_book_is_masked(self):
        q=book({100.0:3},{100.1:2})
        q.book_ts_ms=q.last_ts_ms+1
        f=_book_features(q,100.05,"LOW")
        self.assertEqual(f,{"book_quality_valid":0.0,"book_quality_future":1.0})

    def test_fresh_timestamped_book_keeps_features(self):
        q=book({100.0:3},{100.1:2})
        q.book_ts_ms=q.last_ts_ms-5000
        f=_book_features(q,100.05,"LOW")
        self.assertEqual(f["book_quality_valid"],1.0)
        self.assertIn("book_spread_bps",f)

    def test_malformed_timestamp_fails_closed(self):
        q=book({100.0:3},{100.1:2})
        q.book_ts_ms=float("nan")
        f=_book_features(q,100.05,"LOW")
        self.assertEqual(f["book_quality_timestamp_invalid"],1.0)
        self.assertNotIn("book_spread_bps",f)

    def test_missing_is_masked_not_zero_filled(self):
        f=_book_features(book({},{}),100.0,"LOW")
        self.assertEqual(f,{"book_quality_valid":0.0})
    def test_malformed_qty_is_masked(self):
        f=_book_features(book({100.0:-1},{100.1:2}),100.0,"HIGH")
        self.assertEqual(f["book_quality_valid"],0.)
        self.assertNotIn("book_spread_bps",f)

class EventWindowCausalityTest(unittest.TestCase):
    def test_future_book_change_excluded(self):
        ts=1700000000000
        state=book({100.:3},{100.1:2})
        state.last_ts_ms=ts
        state.book_changes=[
            (ts-1000,{"bid_add":10.0,"ask_add":0.0}),
            (ts+1000,{"bid_add":0.0,"ask_add":10000.0})]
        f=_book_features(state,100.05,"LOW")
        self.assertEqual(f["book_add_imbalance_15s"],1.0)

    def test_future_only_book_change_not_feature(self):
        ts=1700000000000
        state=book({100.:3},{100.1:2})
        state.last_ts_ms=ts
        state.book_changes=[(ts+1000,{"bid_add":0.0,"ask_add":1.0})]
        f=_book_features(state,100.05,"LOW")
        self.assertNotIn("book_add_imbalance_15s",f)

    def test_future_liquidation_excluded(self):
        ts=1700000000000
        state=SimpleNamespace(last_ts_ms=ts,liqs=[
            {"ts_ms":ts-1000,"notional":100.0,"side":1},
            {"ts_ms":ts+1000,"notional":100000.0,"side":-1}])
        f=_liq_features(state,{},"LOW")
        self.assertEqual(f["liq_events_15s"],1.)
        self.assertEqual(f["liq_side_imbalance_15s"],-1.)

    def test_future_only_liquidation_not_feature(self):
        ts=1700000000000
        state=SimpleNamespace(last_ts_ms=ts,liqs=[
            {"ts_ms":ts+1000,"notional":100000.0,"side":-1}])
        f=_liq_features(state,{},"LOW")
        self.assertNotIn("liq_events_15s",f)

if __name__=="__main__": unittest.main()
