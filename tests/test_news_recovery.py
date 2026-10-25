"""Receipt/processing transaction and retry tests; no production database used."""
import contextlib
import copy
import datetime
import threading
import unittest
from unittest.mock import patch

import app


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class NewsDatabase:
    def __init__(self):
        self.receipts = {}
        self.processing = {}
        self.journals = []
        self.fail_receipt = False
        self.fail_done = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @contextlib.contextmanager
    def transaction(self):
        before = copy.deepcopy((self.receipts, self.processing, self.journals))
        try:
            yield self
        except Exception:
            self.receipts, self.processing, self.journals = before
            raise

    def execute(self, sql, params=()):
        if app.LOCK._is_owned():
            raise AssertionError("database accessed under risk lock")
        normalized = " ".join(sql.lower().split())
        if normalized.startswith("insert into news_events"):
            if self.fail_receipt:
                raise RuntimeError("receipt transaction unavailable")
            ident, ts, source, title, symbol, signal, published_at, source_url = params
            if ident in self.receipts:
                return Result()
            self.receipts[ident] = dict(id=ident, ts=ts, source=source, title=title,
                                       symbol=symbol, signal=signal,
                                       published_at=published_at, source_url=source_url)
            return Result([{"id": ident}])
        if normalized.startswith("insert into news_processing"):
            self.processing[params[0]] = "pending"
            return Result()
        if normalized.startswith("insert into audit_journal"):
            self.journals.append(params)
            return Result()
        if normalized.startswith("select state from news_processing"):
            state = self.processing.get(params[0])
            return Result([{"state": state}]) if state else Result()
        if normalized.startswith("update news_processing"):
            if self.fail_done:
                raise RuntimeError("completion transaction unavailable")
            self.processing[params[1]] = "done"
            return Result()
        if "from news_processing p join news_events n" in normalized:
            cutoff = app.time.time() - float(params[0])
            rows = [row for ident, row in self.receipts.items()
                    if self.processing.get(ident) == "pending"
                    and app.publication_epoch(row["ts"]) >= cutoff]
            return Result(sorted(rows, key=lambda row: (row["ts"], row["id"]))[:20])
        raise AssertionError("unexpected SQL: " + normalized)


class StopAfterCycle:
    def __init__(self):
        self.stopped = False

    def is_set(self):
        return self.stopped

    def wait(self, seconds):
        self.stopped = True


class NewsRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.state = copy.deepcopy(app.S)
        app.S.clear()
        app.S.update(engine_active=True, news_seen=0, sources={}, _prices={"BTC": 100000})
        self.db = NewsDatabase()
        self.pg = patch.object(app, "pg", return_value=self.db)
        self.pg.start()
        self.latency = patch.object(app.LATENCIES, "record")
        self.latency.start()
        self.shutdown = patch.object(app, "SHUTDOWN", threading.Event())
        self.shutdown.start()

    def tearDown(self):
        self.shutdown.stop()
        self.latency.stop()
        self.pg.stop()
        app.S.clear()
        app.S.update(self.state)

    def ingest(self, ident="event", source="XOfficial:FirstSquawk", title="Bitcoin ETF approved", published_at=None):
        return app.ingest_event(ident, source, title, published_at or app.now(), "https://fixture.invalid/story")

    def test_failed_receipt_does_not_poison_memory_dedup(self):
        self.db.fail_receipt = True
        with patch.object(app, "record_event") as decision:
            with self.assertRaises(RuntimeError):
                self.ingest()
            self.assertFalse(self.db.receipts)
            self.assertFalse(app.S.get("_recent_news_keys"))
            self.assertFalse(app.S.get("_news_inflight"))
            self.db.fail_receipt = False
            self.assertTrue(self.ingest())
        decision.assert_called_once()
        self.assertEqual(self.db.processing["event"], "done")

    def test_processor_failure_retries_saved_pending_receipt(self):
        with patch.object(app, "record_event", side_effect=[RuntimeError("analysis unavailable"), 1]) as decision:
            with self.assertRaises(RuntimeError):
                self.ingest()
            self.assertEqual(self.db.processing["event"], "pending")
            self.assertFalse(app.S.get("_recent_news_keys"))
            self.assertTrue(self.ingest())
            self.assertFalse(self.ingest())
        self.assertEqual(decision.call_count, 2)
        self.assertEqual(app.S["news_seen"], 1)
        self.assertEqual(self.db.processing["event"], "done")

    def test_failed_completion_write_leaves_receipt_retryable(self):
        self.db.fail_done = True
        with patch.object(app, "record_event") as decision:
            with self.assertRaises(RuntimeError):
                self.ingest()
            self.assertEqual(self.db.processing["event"], "pending")
            self.assertFalse(app.S.get("_recent_news_keys"))
            self.db.fail_done = False
            self.assertTrue(self.ingest())
        self.assertEqual(decision.call_count, 2)

    def test_legacy_receipt_has_no_pending_record_and_is_not_replayed(self):
        self.db.receipts["event"] = {"id": "event"}
        with patch.object(app, "record_event") as decision:
            self.assertFalse(self.ingest())
        decision.assert_not_called()

    def test_completed_cross_source_headline_is_logged_and_not_traded_twice(self):
        with patch.object(app, "record_event") as decision:
            self.assertTrue(self.ingest("one"))
            self.assertFalse(self.ingest("two", source="PiQDirect"))
        decision.assert_called_once()
        self.assertEqual(self.db.processing, {"one": "done", "two": "done"})
        self.assertEqual(app.S["news_seen"], 2)

    def test_same_event_cannot_run_concurrently(self):
        entered, release = threading.Event(), threading.Event()
        errors = []

        def process(*args):
            entered.set()
            if not release.wait(2):
                raise AssertionError("test synchronization timed out")

        def first():
            try:
                self.ingest()
            except Exception as exc:
                errors.append(exc)

        with patch.object(app, "record_event", side_effect=process) as decision:
            worker = threading.Thread(target=first)
            worker.start()
            self.assertTrue(entered.wait(2))
            try:
                self.assertFalse(self.ingest())
            finally:
                release.set()
                worker.join(3)
        self.assertFalse(errors)
        self.assertFalse(worker.is_alive())
        decision.assert_called_once()

    def test_cross_source_inflight_duplicate_stays_pending_then_completes(self):
        entered, release = threading.Event(), threading.Event()
        errors = []

        def process(*args):
            entered.set()
            release.wait(2)

        def first():
            try:
                self.ingest("one")
            except Exception as exc:
                errors.append(exc)

        with patch.object(app, "record_event", side_effect=process) as decision:
            worker = threading.Thread(target=first)
            worker.start()
            self.assertTrue(entered.wait(2))
            try:
                self.assertFalse(self.ingest("two", source="PiQDirect"))
                self.assertEqual(self.db.processing["two"], "pending")
            finally:
                release.set()
                worker.join(3)
            self.assertFalse(self.ingest("two", source="PiQDirect"))
        self.assertFalse(errors)
        self.assertEqual(self.db.processing["two"], "done")
        decision.assert_called_once()

    def test_filter_only_events_are_marked_complete(self):
        with patch.object(app, "record_event") as decision:
            self.assertTrue(self.ingest("promotion", title="Bitcoin giveaway"))
            with patch.object(app, "save_event_feature"):
                self.assertTrue(self.ingest("liquidations", title="Bitcoin longs liquidated"))
        decision.assert_not_called()
        self.assertEqual(self.db.processing, {"promotion": "done", "liquidations": "done"})

    def test_recovery_rechecks_original_publication_age(self):
        old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)).isoformat()
        with patch.object(app, "record_event", side_effect=RuntimeError("injected failure")):
            with self.assertRaises(RuntimeError):
                self.ingest(published_at=old)
        with patch.object(app, "save_event_feature"), patch.object(app, "open_signal") as opened:
            with patch.object(app, "SHUTDOWN", StopAfterCycle()):
                app.recover_news_processing()
        opened.assert_not_called()
        self.assertEqual(self.db.processing["event"], "done")

    def test_recovery_handles_remaining_events_after_one_processor_failure(self):
        for ident, title in (("one", "Bitcoin ETF approved"), ("two", "Bitcoin hacked")):
            app.save_news_event(ident, app.now(), "PiQDirect", title, "BTC", 1, app.now())
        with patch.object(app, "record_event", side_effect=[RuntimeError("first failed"), -1]) as decision:
            with patch.object(app, "SHUTDOWN", StopAfterCycle()):
                app.recover_news_processing()
        self.assertEqual(decision.call_count, 2)
        self.assertEqual(self.db.processing, {"one": "pending", "two": "done"})
        self.assertFalse(app.S.get("_news_inflight"))


if __name__ == "__main__":
    unittest.main()
