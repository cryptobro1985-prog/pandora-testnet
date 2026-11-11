#!/usr/bin/env python3
"""Fast fail-closed quote quality test. No market or broker access."""
import unittest
from research.hype_unified_intelligence.fullmicro_quote_audit_v1 import (
    book_reject_reasons,FAMILIES
)
class FullMicroQualityTest(unittest.TestCase):
    def test_crossed_is_invalid_even_when_flag_is_valid(self):
        f={"fullmicro_book_valid":1,"fullmicro_book_gap_count":0,
           "fullmicro_spread_bps":-98.8467}
        self.assertIn("NEGATIVE_CROSSED_BOOK_SPREAD",book_reject_reasons(f))
    def test_normal_book(self):
        f={"fullmicro_book_valid":1,"fullmicro_book_gap_count":0,
           "fullmicro_spread_bps":.17}
        self.assertEqual(book_reject_reasons(f),[])
    def test_last_trade_can_be_outside_book(self):
        f={"fullmicro_book_valid":1,"fullmicro_book_gap_count":0,
           "fullmicro_spread_bps":.17,
           "fullmicro_bid_01_dist_bps":20.0,
           "fullmicro_ask_01_dist_bps":20.17}
        self.assertEqual(book_reject_reasons(f),[])
    def test_absent_quote_invalid(self):
        f={"fullmicro_book_valid":1,"fullmicro_book_gap_count":0}
        self.assertIn("MISSING_OR_NONFINITE_SPREAD",book_reject_reasons(f))
    def test_book_gap_invalid(self):
        f={"fullmicro_book_valid":1,"fullmicro_book_gap_count":1,
           "fullmicro_spread_bps":.2}
        self.assertIn("BOOK_GAP",book_reject_reasons(f))
    def test_invalid_source_flag(self):
        f={"fullmicro_book_valid":0,"fullmicro_book_gap_count":0,
           "fullmicro_spread_bps":.2}
        self.assertIn("SOURCE_BOOK_INVALID",book_reject_reasons(f))
    def test_model_features_exclude_future_label_fields(self):
        names=[z for a in FAMILIES.values() for z in a]
        self.assertTrue(names)
        self.assertFalse(any(("strict" in z or "label" in z or
            "target" in z or "future" in z or "timestamp" in z)
            for z in names))

if __name__=="__main__":
    unittest.main()
