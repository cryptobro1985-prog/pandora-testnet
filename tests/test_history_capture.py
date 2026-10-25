"""Regression coverage for week-long PAPER history capture."""
import copy
import unittest
from unittest.mock import patch

import app


class FakeCursor:
    def __init__(self, rows=None):
        self._rows = rows or []
    def fetchall(self):
        return list(self._rows)


class FakeDB:
    def __init__(self):
        self.calls = []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return FakeCursor()


class HistoryCaptureTests(unittest.TestCase):
    def setUp(self):
        self.saved = copy.deepcopy(app.S)
        app.S.clear()
        app.S.update({
            "sources": {
                "PumpDumpScanner": {"ok": True, "qualified_candidates": 2},
                "WhaleLiquidationScanner": {"ok": True, "clusters": 3},
                "PiQDirect": {"ok": True, "realtime_verified": False},
            },
            "positions": {},
            "pump_positions": {},
            "whale_positions": {},
        })

    def tearDown(self):
        app.S.clear()
        app.S.update(self.saved)

    def test_module_snapshots_persist_tracked_runtime_state(self):
        db = FakeDB()
        with patch.object(app, "pg", return_value=db):
            count = app.save_module_snapshots()
        self.assertEqual(count, 3)
        inserts = [x for x in db.calls if "insert into module_snapshots" in x[0].lower()]
        self.assertEqual(len(inserts), 3)
        self.assertEqual({x[1][1] for x in inserts},
                         {"PumpDumpScanner", "WhaleLiquidationScanner", "PiQDirect"})

    def test_position_snapshots_cover_all_three_strategies(self):
        base = {
            "side": 1, "entry": 100.0, "notional": 250.0, "margin": 10.0,
            "leverage": 25.0, "opened": "2026-10-25T05:00:00+00:00",
            "peak": 101.0, "last_exit_check": {"reason": None},
        }
        app.S["positions"] = {"BTC": {**base, "headline": "fixture", "event_id": "evt"}}
        app.S["pump_positions"] = {"ETH": {**base, "features": {"score": 91}}}
        app.S["whale_positions"] = {"SOL": {**base, "features": {"score": 88}}}
        db = FakeDB()
        with patch.object(app, "pg", return_value=db):
            count = app.save_position_snapshots({"BTC": 101, "ETH": 102, "SOL": 103})
        self.assertEqual(count, 3)
        inserts = [x for x in db.calls if "insert into position_snapshots" in x[0].lower()]
        self.assertEqual(len(inserts), 3)
        self.assertEqual({x[1][1] for x in inserts}, {"news", "pump_dump", "whale_liquidation"})
        self.assertEqual({x[1][2] for x in inserts}, {"BTC", "ETH", "SOL"})


if __name__ == "__main__":
    unittest.main()
