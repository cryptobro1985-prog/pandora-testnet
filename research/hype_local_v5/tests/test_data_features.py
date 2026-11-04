import csv
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from research.hype_local_v5.data import (
    DataError, aggregate_raw_trades, canonical_bar, coverage, join_asof,
    load_bars, load_snapshots, provenance, timestamp_ms,
    replay_raw_frames,
    join_historical_oi,
)
from research.hype_local_v5.features import FeatureBuilder


def bar(start, interval=60_000, price=100, **extra):
    return dict(start_ms=start, interval_ms=interval, ts_ms=start+interval,
                open=price, high=price+1, low=price-1, close=price+.2,
                buy_notional=200, sell_notional=100, **extra)


class DataContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def csv(self, name, rows, zipped=False):
        path = self.root/name
        op = gzip.open if zipped else open
        with op(path, "wt", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_archive_timestamp_is_not_availability(self):
        row = canonical_bar(dict(ts=1_800_000, open=100, high=102, low=99, close=101))
        self.assertEqual(row["start_ms"], 1_800_000)
        self.assertEqual(row["ts_ms"], 1_860_000)
        self.assertIsNone(row["buy_notional"])
        self.assertFalse(row["flow_observed"])
        with self.assertRaises(DataError):
            canonical_bar({**bar(0), "ts_ms": 59_999})

    def test_real_universal_archive_uses_unix_seconds(self):
        source=dict(ts=1791072000,open=100,high=102,low=99,close=101,
                    buy_notional=1000,sell_notional=2000)
        row=canonical_bar(source)
        self.assertEqual(row['start_ms'],1791072000000)
        self.assertEqual(row['ts_ms'],1791072060000)
        row_ms=canonical_bar({**source,'ts':1791072000000})
        self.assertEqual(row_ms['ts_ms'],row['ts_ms'])

    def test_reject_nonfinite_negative_invalid_ohlc_and_timestamp(self):
        for changes in ({"high": float("nan")}, {"close": 999}, {"buy_notional": -1},
                        {"start_ms": -1}, {"start_ms": 1}, {"interval_ms": 0}):
            with self.subTest(changes=changes), self.assertRaises(DataError):
                canonical_bar({**bar(0), **changes})
        for t in (None, "NaN", "Infinity", "x", -1):
            with self.subTest(t=t), self.assertRaises(DataError):
                timestamp_ms(t)

    def test_gzip_merge_gap_and_conflicting_duplicate(self):
        a = self.csv("a.csv.gz", [bar(0), bar(60_000)], zipped=True)
        b = self.csv("b.csv", [bar(60_000), bar(180_000)])
        rows = load_bars([a, b])
        self.assertEqual(len(rows), 3)
        self.assertTrue(rows[-1]["gap_before"])
        self.assertEqual(coverage(rows)["gap_duration_ms"], 60_000)
        self.assertEqual(len(provenance(a)["sha256"]), 64)
        c = self.csv("c.csv", [{**bar(60_000), "buy_notional": 999}])
        with self.assertRaises(DataError):
            load_bars([a, c])
        bad = self.csv("bad.csv", [bar(60_000), bar(0)])
        with self.assertRaises(DataError):
            load_bars(bad)

    def test_raw_order_is_real_and_final_bucket_requires_completeness(self):
        path = self.csv("raw.csv", [
            dict(timestamp="1791072000.123456", side="Buy", price=100, size=2),
            dict(timestamp="1791072000.123457", side="Sell", price=98, size=1),
            dict(timestamp="1791072005.000001", side="Buy", price=99, size=3),
        ])
        rows = list(aggregate_raw_trades(path))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["open"], 100)
        self.assertEqual(rows[0]["close"], 98)
        self.assertEqual(rows[0]["buy_notional"], 200)
        self.assertEqual(rows[0]["sell_notional"], 98)
        self.assertEqual(rows[0]["first_trade_ms"], 1791072000123)
        full = list(aggregate_raw_trades(path, end_ms=1791072010000))
        self.assertEqual(len(full), 2)
        bad = self.csv("reordered.csv", [
            dict(timestamp="1791072005", side="Buy", price=99, size=1),
            dict(timestamp="1791072000", side="Sell", price=100, size=1),
        ])
        with self.assertRaises(DataError):
            list(aggregate_raw_trades(bad))

    def test_asof_never_uses_future_or_stale_snapshots(self):
        bars = [canonical_bar(bar(t, 1000)) for t in (0, 1000, 2000, 3000)]
        samples = [dict(ts_ms=1500, open_interest=10, close=999),
                   dict(ts_ms=4500, open_interest=999)]
        merged = list(join_asof(bars, samples, max_age_ms=1000))
        self.assertNotIn("open_interest", merged[0])
        self.assertEqual(merged[1]["open_interest"], 10)
        self.assertEqual(merged[1]["close"], bars[1]["close"])
        self.assertNotIn("open_interest", merged[2])
        self.assertIsNone(merged[3]["forward_snapshot_ts_ms"])

    def test_forward_jsonl_monotonic(self):
        path = self.root/"snap.jsonl"
        path.write_text('\n'.join(json.dumps(x) for x in [dict(ts_ms=1), dict(ts_ms=1)]))
        with self.assertRaises(DataError):
            load_snapshots(path)

    def test_historical_oi_waits_for_availability_and_cannot_invent_30s_changes(self):
        path = self.csv("oi.csv", [dict(ts_ms=0, open_interest=100),
                                   dict(ts_ms=300_000, open_interest=110),
                                   dict(ts_ms=600_000, open_interest=120)])
        bars = [canonical_bar(bar(i*60_000)) for i in range(16)]
        joined = list(join_historical_oi(bars, path))
        self.assertNotIn("open_interest", joined[3])
        self.assertEqual(joined[4]["open_interest"], 100)
        self.assertTrue(joined[4]["oi_availability_assumed"])
        f = FeatureBuilder()
        features = [f.update(x) for x in joined]
        self.assertIsNone(features[9]["oi_delta_30s"])
        self.assertIsNone(features[9]["oi_delta_60s"])
        self.assertAlmostEqual(features[9]["oi_delta_300s"], .1)
        self.assertEqual(features[9]["oi_effective_end_ms"], 300_000)
        self.assertTrue(features[9]["oi_availability_assumed"])


class CausalFeatures(unittest.TestCase):
    def test_prefix_invariance_with_future_poison(self):
        rows = [bar(i*60_000, price=100+i*.01) for i in range(365)]
        a = FeatureBuilder()
        prefix = [a.update(x) for x in rows[:200]]
        b = FeatureBuilder()
        full = [b.update(x) for x in rows]
        self.assertEqual(prefix, full[:200])

    def test_partial_and_gappy_hours_do_not_enter_context(self):
        f = FeatureBuilder()
        for i in range(59):
            out = f.update(bar(i*60_000))
        self.assertEqual(out["completed_h1_count"], 0)
        self.assertIsNone(out["atr_h1"])
        out = f.update(bar(59*60_000))
        self.assertEqual(out["completed_h1_count"], 1)
        self.assertEqual(out["atr_h1"], 2)
        # Missing one minute makes the second hour ineligible.
        for i in range(60, 120):
            if i != 75:
                out = f.update(bar(i*60_000))
        self.assertEqual(out["completed_h1_count"], 1)
        # A full following hour is accepted without inventing the missing bar.
        for i in range(120, 180):
            out = f.update(bar(i*60_000))
        self.assertEqual(out["completed_h1_count"], 2)
        self.assertIsNone(out["directional_move_3h"])

    def test_flow_window_requires_coverage_and_does_not_make_subminute_path(self):
        f = FeatureBuilder()
        first = f.update(bar(0))
        self.assertEqual(first["buy_notional_60s"], 200)
        self.assertIsNone(first["buy_notional_300s"])
        self.assertAlmostEqual(first["flow_imbalance_60s"], 1/3)
        self.assertAlmostEqual(first["buy_efficiency_60s"], .2/200)
        missing = {**bar(60_000), "buy_notional": None}
        out = f.update(missing)
        self.assertIsNone(out["flow_imbalance_60s"])
        self.assertEqual(out["flow_coverage_seconds"], 0)
        out = f.update(bar(180_000))
        self.assertTrue(out["gap_before"])
        self.assertEqual(out["flow_coverage_seconds"], 60)

    def test_oi_horizons_freshness_and_no_synthetic_backfill(self):
        f = FeatureBuilder(oi_max_age_ms=1000, oi_horizon_tolerance_ms=1000)
        out = f.update(bar(0, 1000, open_interest=100, oi_ts_ms=1000))
        self.assertIsNone(out["oi_delta_30s"])
        for i in range(1, 31):
            out = f.update(bar(i*1000, 1000, open_interest=100+i, oi_ts_ms=(i+1)*1000))
        self.assertAlmostEqual(out["oi_delta_30s"], .3)
        out = f.update(bar(31_000, 1000))
        self.assertEqual(out["open_interest"], 130)
        out = f.update(bar(32_000, 1000))
        self.assertIsNone(out["open_interest"])
        self.assertIsNone(out["oi_delta_30s"])
        g = FeatureBuilder()
        self.assertIsNone(g.update(bar(0, open_interest=100))["open_interest"])
        with self.assertRaises(DataError):
            g.update(bar(60_000, open_interest=100, oi_ts_ms=999_999))

    def test_book_cancellations_are_not_executed_consumption(self):
        f = FeatureBuilder()
        out = f.update(bar(0, ask_add_notional=100, ask_cancel_notional=50))
        self.assertIsNone(out["ask_replenishment_ratio_60s"])
        out = f.update(bar(60_000, ask_restored_notional_60s=100, ask_consumed_notional_60s=50))
        self.assertEqual(out["ask_replenishment_ratio_60s"], 2)


class CollectorContracts(unittest.TestCase):
    def state(self):
        from research.hype_local_v5.research import LiveState
        self.now = 100.0
        return LiveState(clock=lambda: self.now)

    def test_unchanged_oi_refreshes_actual_observation(self):
        s = self.state()
        msg = dict(ts=100000, data=dict(openInterest="10"))
        s.on_ticker(msg)
        self.assertEqual(s.snapshot()["oi_ts_ms"], 100000)
        self.now = 105.0
        s.on_ticker(msg)
        self.assertEqual(s.snapshot()["oi_ts_ms"], 105000)
        self.now = 116.0
        self.assertIsNone(s.snapshot()["open_interest"])

    def test_missing_subscribed_coverage_is_not_zero_liquidations(self):
        s = self.state()
        self.assertIsNone(s.snapshot()["long_liq_notional_60s"])
        s.on_subscription(dict(op="subscribe", success=True))
        self.now += 60
        self.assertEqual(s.snapshot()["long_liq_notional_60s"], 0)
        s.on_liq(dict(data=[dict(S="Buy", p="100", v="2", T=160000)]))
        self.assertEqual(s.snapshot()["long_liq_notional_60s"], 200)
        self.assertEqual(s.snapshot()["short_liq_notional_60s"], 0)

    def test_book_needs_snapshot_and_rejects_regression_and_staleness(self):
        s = self.state()
        delta = dict(type="delta", ts=100000, data=dict(u=2, seq=2, b=[["99", "1"]], a=[["101", "1"]]))
        s.on_book(delta)
        self.assertFalse(s.snapshot()["book_valid"])
        snap = {**delta, "type": "snapshot"}
        s.on_book(snap)
        self.assertTrue(s.snapshot()["book_valid"])
        s.on_book(delta)
        self.assertFalse(s.snapshot()["book_valid"])
        s.on_book(snap)
        self.now += 3
        self.assertIsNone(s.snapshot()["mid"])
        s.on_book({**delta, "data": {**delta["data"], "u": 3, "seq": 3}})
        self.assertFalse(s.snapshot()["book_valid"])

    def test_raw_forward_replay_uses_receipt_order_and_rejects_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"frames.jsonl"
            events = [dict(op="subscribe", success=True), dict(topic="tickers.HYPEUSDT", data=dict(openInterest="10")),
                      dict(topic="tickers.HYPEUSDT", data=dict(openInterest="11"))]
            envelopes = [dict(received_ts_ms=100000+i*1000, receipt_sequence=i+1, raw_text=json.dumps(x)) for i, x in enumerate(events)]
            path.write_text('\n'.join(json.dumps(x) for x in envelopes))
            rows = list(replay_raw_frames(path))
            self.assertIsNone(rows[0]["open_interest"])
            self.assertEqual(rows[1]["open_interest"], 10)
            self.assertEqual(rows[2]["open_interest"], 11)
            self.assertEqual(rows[2]["oi_ts_ms"], 102000)
            envelopes[-1]["receipt_sequence"] = 9
            path.write_text('\n'.join(json.dumps(x) for x in envelopes))
            with self.assertRaises(DataError):
                list(replay_raw_frames(path))


if __name__ == "__main__":
    unittest.main()
