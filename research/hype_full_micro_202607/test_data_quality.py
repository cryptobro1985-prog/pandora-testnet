from __future__ import annotations

import unittest

from research.hype_full_micro_202607.build_full_micro import (
    H,
    book_features,
    liq_features,
)


class FullMicroDataQualityTests(unittest.TestCase):
    def test_crossed_book_is_masked(self):
        state={
            "valid":True,
            "gap_count":0,
            "bids":{100.0:5.0,99.0:4.0},
            "asks":{99.5:3.0,101.0:2.0},
            "events":[],
        }
        f=book_features(state,1_000_000)
        self.assertEqual(f["fullmicro_book_valid"],0.0)
        self.assertEqual(f["fullmicro_book_crossed"],1.0)
        self.assertNotIn("fullmicro_spread_bps",f)
        self.assertFalse(any(k.startswith("fullmicro_book_imbalance_") for k in f))

    def test_normal_book_has_positive_spread(self):
        state={
            "valid":True,
            "gap_count":0,
            "bids":{99.0:5.0,98.5:4.0},
            "asks":{100.0:3.0,100.5:2.0},
            "events":[],
        }
        f=book_features(state,1_000_000)
        self.assertEqual(f["fullmicro_book_valid"],1.0)
        self.assertEqual(f["fullmicro_book_crossed"],0.0)
        self.assertGreater(f["fullmicro_spread_bps"],0.0)
        self.assertLessEqual(f["fullmicro_bid_01_dist_bps"],0.0)
        self.assertGreaterEqual(f["fullmicro_ask_01_dist_bps"],0.0)

    def test_missing_liquidation_hour_is_not_zero(self):
        # 00:02 UTC, 300s window crosses the previous hour.
        t=H+120_000
        events=[(t-30_000,1000.0,"LONG")]
        f=liq_features(events,t,{H})
        self.assertEqual(f["fullmicro_liq_stream_valid_60s"],1.0)
        self.assertEqual(f["fullmicro_liq_count_60s"],1.0)
        self.assertEqual(f["fullmicro_liq_stream_valid_300s"],0.0)
        self.assertNotIn("fullmicro_liq_count_300s",f)

    def test_complete_liquidation_window_can_encode_true_zero(self):
        t=H+120_000
        f=liq_features([],t,{0,H})
        self.assertEqual(f["fullmicro_liq_stream_valid_300s"],1.0)
        self.assertEqual(f["fullmicro_liq_count_300s"],0.0)
        self.assertEqual(f["fullmicro_long_liq_notional_300s"],0)
        self.assertEqual(f["fullmicro_short_liq_notional_300s"],0)


if __name__=="__main__":
    unittest.main()
