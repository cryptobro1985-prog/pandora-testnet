import copy
import unittest

import app


class Strategy1H1RuntimeGuardTests(unittest.TestCase):
    def setUp(self):
        with app.LOCK:
            self.saved = copy.deepcopy(app.S.get("_local_h1_runtime_verified", {}))
            app.S["_local_h1_runtime_verified"] = {}

    def tearDown(self):
        with app.LOCK:
            app.S["_local_h1_runtime_verified"] = self.saved

    @staticmethod
    def analysis(side=1, signal=8 * 3_600_000, pivot=7 * 3_600_000):
        return {
            "ready": True,
            "anchor_confirmed": True,
            "h1_direction_anchor": True,
            "entry_side": side,
            "pivot_type": "LOCAL_LOW" if side > 0 else "LOCAL_HIGH",
            "pivot_price": 100.0,
            "signal_candle_time": signal,
            "pivot_candle_time": pivot,
        }

    def test_hydrated_anchor_cannot_create_new_risk_before_runtime_h1_scan(self):
        self.assertFalse(app.strategy1_runtime_h1_verified("GRASS", self.analysis(), 10 * 3600 + 1800))

    def test_matching_runtime_scan_allows_same_anchor(self):
        now_epoch = 10 * 3600 + 1800
        a = self.analysis()
        with app.LOCK:
            app.S["_local_h1_runtime_verified"]["GRASS"] = {
                "verified_at": now_epoch - 2,
                "last_candle_time": 9 * 3_600_000,
                "entry_side": 1,
                "signal_candle_time": a["signal_candle_time"],
                "pivot_candle_time": a["pivot_candle_time"],
            }
        self.assertTrue(app.strategy1_runtime_h1_verified("GRASS", a, now_epoch))

    def test_stale_side_or_signal_is_rejected(self):
        now_epoch = 10 * 3600 + 1800
        a = self.analysis(side=1)
        with app.LOCK:
            app.S["_local_h1_runtime_verified"]["GRASS"] = {
                "verified_at": now_epoch - 2,
                "last_candle_time": 9 * 3_600_000,
                "entry_side": -1,
                "signal_candle_time": a["signal_candle_time"],
                "pivot_candle_time": a["pivot_candle_time"],
            }
        self.assertFalse(app.strategy1_runtime_h1_verified("GRASS", a, now_epoch))

    def test_new_h1_boundary_blocks_entry_until_just_closed_candle_is_scanned(self):
        now_epoch = 10 * 3600 + 2
        a = self.analysis()
        with app.LOCK:
            app.S["_local_h1_runtime_verified"]["GRASS"] = {
                "verified_at": now_epoch - 1,
                "last_candle_time": 8 * 3_600_000,
                "entry_side": 1,
                "signal_candle_time": a["signal_candle_time"],
                "pivot_candle_time": a["pivot_candle_time"],
            }
        self.assertFalse(app.strategy1_runtime_h1_verified("GRASS", a, now_epoch))


if __name__ == "__main__":
    unittest.main()
