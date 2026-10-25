"""Regression tests for failures found in the October 25 PAPER runtime audit."""
import contextlib
import copy
import json
import unittest
from unittest.mock import patch

import app
from source_health import LatencyMetrics, aggregate_delivery


class OneCycleStop:
    def __init__(self):
        self.stopped = False

    def is_set(self):
        return self.stopped

    def wait(self, seconds):
        self.stopped = True


def position(opened="old"):
    return {"entry": 100.0, "side": 1, "leverage": 25.0, "margin": 10.0,
            "notional": 250.0, "opened": opened, "t": 1000.0,
            "headline": "fixture", "event_id": None, "history": [],
            "peak": 100.0, "locked": False, "stop": None}


class DeliveryAuditTests(unittest.TestCase):
    def test_successful_polling_is_not_evidence_of_delivery(self):
        rows = {h: {"ok": True, "last_success_epoch": 1000}
                for h in ("FirstSquawk", "realDonaldTrump", "federalreserve", "SECGov")}
        report = aggregate_delivery(rows)
        self.assertFalse(report["realtime_verified"])
        self.assertEqual(report["realtime_accounts_verified"], 0)
        self.assertEqual(report["realtime_accounts_unverified"], 4)

    def test_one_fast_post_does_not_hide_slow_batch_p95(self):
        metrics = LatencyMetrics()
        metrics.record("X", 1, 1000)
        for latency in range(20, 39):
            metrics.record("X", latency, 1000)
        result = metrics.summary("X", 1000)
        self.assertEqual(result["samples"], 20)
        self.assertGreater(result["p95_seconds"], 30)
        self.assertFalse(result["realtime_verified"])

    def test_all_accounts_need_current_measured_evidence(self):
        metrics = LatencyMetrics(window=60)
        metrics.record("fresh", 2, 1000)
        metrics.record("expired", 2, 900)
        rows = {"a": {"ok": True, "delivery": metrics.summary("fresh", 1000)},
                "b": {"ok": True, "delivery": metrics.summary("expired", 1000)}}
        result = aggregate_delivery(rows)
        self.assertFalse(result["realtime_verified"])
        self.assertEqual(result["realtime_accounts_verified"], 1)

    def test_invalid_clock_and_latency_observations_are_not_evidence(self):
        metrics = LatencyMetrics()
        for latency, stamp in [(-1, 1000), (float("nan"), 1000),
                               (1, float("inf")), (1, 1005)]:
            metrics.record("X", latency, stamp)
        self.assertEqual(metrics.summary("X", 1000)["samples"], 0)


class TimelineAuditTests(unittest.TestCase):
    def test_fifteen_second_signal_cannot_anchor_to_current_or_two_second_price(self):
        rows = [(1000, 100), (998, 100)]
        self.assertIsNone(app._timeline_return(rows, 1000, 15, 101))

    def test_requested_horizon_uses_nearest_valid_historical_observation(self):
        rows = [(1000, 100), (998, 100), (985, 99), (940, 95)]
        self.assertAlmostEqual(app._timeline_return(rows, 1000, 15, 101), 101 / 99 - 1)
        self.assertAlmostEqual(app._timeline_return(rows, 1000, 60, 101), 101 / 95 - 1)


class RuntimeAuditTests(unittest.TestCase):
    def setUp(self):
        self.saved = copy.deepcopy(app.S)
        app.S.update(engine_active=True, mode="PAPER_ONLY", orders_enabled=False,
                     positions={}, pump_positions={}, whale_positions={},
                     _prices={"BTC": 100}, _last_poll_epoch=app.time.time(),
                     last_checkpoint=app.now(), equity=100.0, realized_pnl=0.0,
                     trades=0, sources={})

    def tearDown(self):
        app.S.clear()
        app.S.update(self.saved)

    def test_explicit_rejection_overrides_legacy_positive_word_count(self):
        with patch.object(app, "save_event_feature"), patch.object(app, "journal"), \
                patch.object(app, "open_signal") as opened:
            side = app.record_event("fixture", "XOfficial:FirstSquawk",
                                    "SEC rejects Bitcoin ETF approval", "BTC", 1,
                                    {"BTC": 100}, app.now())
        self.assertEqual(side, -1)
        self.assertEqual(opened.call_args.args[1], -1)

    def test_conditional_news_does_not_fall_back_to_legacy_direction(self):
        with patch.object(app, "save_event_feature"), patch.object(app, "journal"), \
                patch.object(app, "open_signal") as opened:
            side = app.record_event("fixture", "XOfficial:FirstSquawk",
                                    "Bitcoin ETF may be approved next week", "BTC", 1,
                                    {"BTC": 100}, app.now())
        self.assertEqual(side, 0)
        opened.assert_not_called()

    def test_diagnostics_database_reads_do_not_own_global_state_lock(self):
        ownership = []
        def stats():
            ownership.append(app.LOCK._is_owned())
            return {}
        with patch.object(app, "SHUTDOWN", OneCycleStop()), \
                patch.object(app, "daily_audit_stats", side_effect=stats), \
                patch.object(app, "health_state", return_value={"risk_ready": True}), \
                patch("builtins.print") as output:
            app.operations_diagnostics()
        self.assertEqual(ownership, [False])
        self.assertFalse(any("diagnostics_error" in str(call) for call in output.call_args_list))

    def test_market_network_and_risk_checkpoints_do_not_own_global_state_lock(self):
        app.S["positions"] = {"BTC": position()}
        ownership = []
        def market_get(*args):
            ownership.append(("network", app.LOCK._is_owned()))
            return json.dumps({"BTC": "100.1"})
        def save(*args):
            ownership.append(("checkpoint", app.LOCK._is_owned()))
            return True
        with patch.object(app, "SHUTDOWN", OneCycleStop()), \
                patch.object(app, "get", side_effect=market_get), \
                patch.object(app.STORE, "save", side_effect=save), \
                patch.object(app, "pump_mark_positions"), patch.object(app, "whale_liq_mark_positions"):
            app.market()
        self.assertIn(("network", False), ownership)
        self.assertIn(("checkpoint", False), ownership)
        self.assertTrue(all(not owned for _, owned in ownership))

    def test_close_completion_does_not_erase_a_different_position_identity(self):
        old, replacement = position("old"), position("replacement")
        app.S["positions"] = {"BTC": old}
        def committed_close(*args):
            app.S["positions"]["BTC"] = replacement
            return {"equity": 101, "realized_pnl": 1, "pnl": 1}
        with patch.object(app.STORE, "close", side_effect=committed_close):
            app.close_news_position("BTC", old, 101, "fixture")
        self.assertEqual(app.S["positions"]["BTC"]["opened"], "replacement")

    def test_checkpoint_failure_does_not_erase_replacement_position(self):
        app.S["positions"] = {"BTC": position("old")}
        def failed_checkpoint(*args):
            app.S["positions"]["BTC"] = position("replacement")
            return False
        with patch.object(app, "SHUTDOWN", OneCycleStop()), \
                patch.object(app, "get", return_value=json.dumps({"BTC": "100.1"})), \
                patch.object(app.STORE, "save", side_effect=failed_checkpoint), \
                patch.object(app, "pump_mark_positions"), patch.object(app, "whale_liq_mark_positions"):
            app.market()
        self.assertEqual(app.S["positions"]["BTC"]["opened"], "replacement")

    def test_pump_and_whale_entries_block_stale_market_before_reserving_capital(self):
        app.S["_last_poll_epoch"] = app.time.time() - 30
        for opener in (app.pump_open, app.whale_liq_open):
            with self.subTest(strategy=opener.__name__), \
                    patch.object(app, "journal"), \
                    patch.object(app, "_reserve_shared_entry", return_value=(False, 0, "fixture", 0)) as reserve:
                self.assertFalse(opener("BTC", 1, 100, 99, {}))
            reserve.assert_not_called()

    def test_hard_test_allocator_defaults(self):
        self.assertEqual(app.TARGET_OPEN_POSITIONS, 10)
        self.assertEqual(app.MAX_OPEN_POSITIONS, 30)
        self.assertEqual(app.PUMP_MAX_POSITIONS, 20)
        self.assertAlmostEqual(app.TRADE_MARGIN_FRACTION, 0.05)
        self.assertAlmostEqual(app.PUMP_SECONDARY_MARGIN_FRACTION, 0.025)
        self.assertAlmostEqual(app.POSITION_MARGIN_MAX, 0.20)

    def test_liquidity_ranked_sizing_scales_with_book(self):
        tiny={"book_depth_usd":20_000,"day_volume_usd":100_000,"score":90}
        mid={"book_depth_usd":2_000_000,"day_volume_usd":50_000_000,"score":90}
        deep={"book_depth_usd":60_000_000,"day_volume_usd":1_000_000_000,"score":95}
        self.assertLess(app.liquidity_margin_fraction("ALT",tiny), app.liquidity_margin_fraction("ALT",mid))
        self.assertLess(app.liquidity_margin_fraction("ALT",mid), app.liquidity_margin_fraction("BTC",deep))
        self.assertLessEqual(app.liquidity_margin_fraction("BTC",deep),0.20)

    def test_pump_book_respects_hard_test_cap(self):
        app.S["pump_positions"] = {f"P{i}": position(str(i)) for i in range(app.PUMP_MAX_POSITIONS)}
        with patch.object(app, "_reserve_shared_entry") as reserve:
            self.assertFalse(app.pump_open("BTC", 1, 100, 99, {}))
        reserve.assert_not_called()

    def test_shared_portfolio_cap_blocks_entry_above_hard_cap(self):
        app.S["positions"] = {f"N{i}": position(str(i)) for i in range(app.MAX_OPEN_POSITIONS)}
        ok, margin, reason, free = app._reserve_shared_entry("NEW")
        self.assertFalse(ok)
        self.assertEqual(margin, 0.0)
        self.assertEqual(reason, "portfolio_position_cap")

    def test_manual_close_does_not_fabricate_fill_from_old_entry_price(self):
        app.S["positions"] = {"BTC": position()}
        app.S["_prices"] = {}
        app.S["_last_poll_epoch"] = 0
        with patch.object(app.STORE, "close", return_value={"equity": 99, "realized_pnl": -1, "pnl": -1}) as close:
            result = app.manual_close("BTC")
        self.assertFalse(result["ok"])
        close.assert_not_called()
        self.assertIn("BTC", app.S["positions"])

    def test_first_receipt_failure_retries_even_if_source_seen_cursor_advanced(self):
        stop=unittest.mock.Mock()
        stop.is_set.return_value=False
        with patch.object(app,"SHUTDOWN",stop), \
                patch.object(app,"ingest_event",side_effect=[RuntimeError("temporary database failure"),True]) as ingest:
            result=app.ingest_with_retry("post","XOfficial:FirstSquawk","Bitcoin ETF approved",app.now())
        self.assertTrue(result)
        self.assertEqual(ingest.call_count,2)
        stop.wait.assert_called_once_with(.5)

    def test_first_receipt_failure_cannot_extend_publication_freshness(self):
        stop=unittest.mock.Mock()
        stop.is_set.return_value=False
        with patch.object(app,"SHUTDOWN",stop), \
                patch.object(app,"ingest_event",side_effect=RuntimeError("database unavailable")) as ingest:
            with self.assertRaises(RuntimeError):
                app.ingest_with_retry("post","XOfficial:FirstSquawk","Bitcoin ETF approved","2025-01-01T00:00:00Z")
        self.assertEqual(ingest.call_count,1)
        stop.wait.assert_not_called()


class DuplicateNewsAuditTests(unittest.TestCase):
    class Cursor:
        def __init__(self, row):
            self.row = row
        def fetchone(self):
            return self.row

    class DuplicateConnection:
        def __init__(self):
            self.statements = []
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def transaction(self):
            return contextlib.nullcontext()
        def execute(self, sql, params=None):
            self.statements.append(sql.lower())
            if "insert into news_events" in sql.lower() and "on conflict" not in sql.lower():
                raise RuntimeError("duplicate key: concurrent source already inserted this post")
            return DuplicateNewsAuditTests.Cursor(None)

    def test_concurrent_duplicate_is_an_atomic_skip_without_duplicate_journal(self):
        db = self.DuplicateConnection()
        with patch.object(app, "pg", return_value=db):
            result = app.save_news_event("existing-id", app.now(), "fixture", "headline", "BTC", 1)
        self.assertFalse(result)
        self.assertEqual(sum("insert into news_events" in q for q in db.statements), 1)
        self.assertFalse(any("insert into audit_journal" in q for q in db.statements))


if __name__ == "__main__":
    unittest.main()
