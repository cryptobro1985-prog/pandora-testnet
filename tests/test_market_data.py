import concurrent.futures
import math
import unittest

from market_data import RollingMarketData


def trade(epoch, tid=1, side="B", price=100, size=1, symbol="BTC"):
    return {"coin": symbol, "side": side, "px": str(price), "sz": str(size),
            "time": int(epoch * 1000), "tid": tid}


class MarketDataTests(unittest.TestCase):
    def setUp(self):
        self.data = RollingMarketData()
        self.start = 1000.0
        self.data.mark_connected(self.start, ["BTC", "ETH"])

    def feed(self, until, size=1):
        for offset in range(0, int(until), 5):
            epoch = self.start + offset + 1
            self.data.ingest_trades([trade(epoch, tid=offset, size=size)], epoch)

    def test_real_trade_notional_and_taker_direction(self):
        for offset in range(0, 90, 5):
            stamp = self.start + offset + 1
            self.data.ingest_trades([trade(stamp, offset, "B", 100, 2),
                                     trade(stamp, offset + 1, "A", 100, 1)], stamp)
        self.data.heartbeat(1090)
        ctx = self.data.context("BTC", 1090)
        self.assertTrue(ctx["trade_data_fresh"])
        self.assertEqual(ctx["buy_volume_60s"], 2400)
        self.assertEqual(ctx["sell_volume_60s"], 1200)
        self.assertEqual(ctx["cvd_1m"], 1200)
        self.assertAlmostEqual(ctx["flow_imbalance"], 1 / 3)
        self.assertEqual(ctx["volume_rate_usd_per_sec"], 60)
        self.assertEqual(ctx["volume_source"], "hyperliquid_ws_trades")

    def test_duplicates_from_retransmit_do_not_inflate_volume(self):
        row = trade(1001, 123)
        self.assertEqual(self.data.ingest_trades([row, row], 1001), 1)
        self.assertEqual(self.data.ingest_trades([row], 1002), 0)
        self.assertEqual(self.data.stats()["duplicates"], 2)
        self.assertEqual(self.data.stats()["accepted"], 1)

    def test_same_tid_in_different_symbol_or_block_is_not_duplicate(self):
        rows = [trade(1001, 7), trade(1002, 7), trade(1001, 7, symbol="ETH")]
        self.assertEqual(self.data.ingest_trades(rows, 1002), 3)

    def test_old_snapshot_and_future_event_do_not_establish_freshness(self):
        self.assertEqual(self.data.ingest_trades([trade(900), trade(1005)], 1001), 0)
        for epoch in range(1005, 1081, 5):
            self.data.heartbeat(epoch)
        ctx = self.data.context("BTC", 1080)
        self.assertFalse(ctx["trade_data_fresh"])
        self.assertIsNone(ctx["volume_burst_ratio"])
        self.assertEqual(self.data.stats()["stale"], 2)

    def test_initial_snapshot_before_subscription_is_not_replayed(self):
        self.assertEqual(self.data.ingest_trades([trade(999)], 1001), 0)
        self.assertIsNone(self.data.context("BTC", 1001)["latest_trade_age_seconds"])

    def test_malformed_or_nonfinite_values_and_unknown_side_are_rejected(self):
        rows = [trade(1001, 1, price="nan"), trade(1001, 2, price="inf"),
                trade(1001, 3, price=0), trade(1001, 4, size=-1),
                trade(1001, 5, side="LONG"), trade(1001, 6, price=1e300, size=1e300),
                {"coin": "BTC"}, None]
        self.assertEqual(self.data.ingest_trades(rows, 1001), 0)
        self.assertEqual(self.data.stats()["invalid"], len(rows))

    def test_unsubscribed_and_disconnected_messages_are_ignored(self):
        self.assertEqual(self.data.ingest_trades([trade(1001, symbol="SOL")], 1001), 0)
        self.data.mark_disconnected()
        self.assertEqual(self.data.ingest_trades([trade(1001)], 1001), 0)
        self.assertEqual(self.data.stats()["accepted"], 0)

    def test_warmup_never_extrapolates_a_partial_observation(self):
        self.feed(45)
        ctx = self.data.context("BTC", 1045)
        self.assertFalse(ctx["trade_data_fresh"])
        self.assertIsNone(ctx["volume_rate_usd_per_sec"])
        self.assertIsNone(ctx["volume_burst_ratio"])
        self.assertEqual(ctx["trade_coverage_seconds"], 45)

    def test_complete_bucket_window_excludes_current_partial_bucket(self):
        self.feed(90)
        self.data.ingest_trades([trade(1091, 1000, size=1000)], 1091)
        ctx = self.data.context("BTC", 1091)
        self.assertAlmostEqual(ctx["volume_burst_ratio"], 1)
        self.assertEqual(ctx["volume_window_end_epoch"], 1090)
        self.assertEqual(ctx["volume_window_seconds"], 15)

    def test_abnormal_volume_uses_prior_baseline_not_its_own_spike(self):
        self.feed(90)
        for offset in range(90, 105, 5):
            stamp = self.start + offset + 1
            self.data.ingest_trades([trade(stamp, 1000 + offset, size=10)], stamp)
        self.data.heartbeat(1105)
        ctx = self.data.context("BTC", 1105)
        self.assertAlmostEqual(ctx["volume_burst_ratio"], 10)
        self.assertGreater(ctx["volume_rate_z"], 3)
        self.assertEqual(ctx["volume_baseline_samples"], 18)
        self.assertTrue(math.isfinite(ctx["volume_rate_z"]))

    def test_flat_activity_has_zero_z_and_no_false_burst(self):
        self.feed(90)
        self.data.heartbeat(1090)
        ctx = self.data.context("BTC", 1090)
        self.assertAlmostEqual(ctx["volume_burst_ratio"], 1)
        self.assertAlmostEqual(ctx["volume_rate_z"], 0)

    def test_quiet_zero_buckets_require_received_server_heartbeats(self):
        self.feed(60)
        for epoch in range(1060, 1081, 5):
            self.data.heartbeat(epoch)
        self.data.ingest_trades([trade(1081, 999)], 1081)
        ctx = self.data.context("BTC", 1081)
        self.assertTrue(ctx["trade_data_fresh"])
        self.assertEqual(ctx["volume_rate_usd_per_sec"], 0)
        self.assertEqual(ctx["trade_coverage_seconds"], 81)
        self.assertFalse(self.data.context("BTC", 1100)["trade_data_fresh"])

    def test_reconnect_resets_volume_history_but_keeps_oi_observations(self):
        self.feed(90)
        self.data.add_open_interest("BTC", 1000, 100)
        self.data.add_open_interest("BTC", 1060, 101)
        self.data.mark_disconnected(1090)
        self.data.mark_connected(1100, ["BTC"])
        self.data.ingest_trades([trade(1101, 999)], 1101)
        self.assertFalse(self.data.context("BTC", 1101)["trade_data_fresh"])
        self.assertEqual(self.data.context("BTC", 1101)["trade_coverage_seconds"], 1)
        self.assertEqual(self.data.stats()["open_interest_symbols"], 1)

    def test_unreported_silent_transport_gap_resets_coverage(self):
        self.feed(90)
        self.data.ingest_trades([trade(1120, 999)], 1120)
        ctx = self.data.context("BTC", 1120)
        self.assertFalse(ctx["trade_data_fresh"])
        self.assertEqual(ctx["trade_coverage_seconds"], 0)

    def test_new_subscription_does_not_inherit_other_symbols_coverage(self):
        self.feed(90)
        self.data.set_subscriptions(["BTC", "SOL"], 1090)
        self.data.ingest_trades([trade(1091, symbol="SOL")], 1091)
        self.assertFalse(self.data.context("SOL", 1091)["trade_data_fresh"])
        self.assertEqual(self.data.context("SOL", 1091)["trade_coverage_seconds"], 1)
        self.assertFalse(self.data.context("ETH", 1091)["trade_data_fresh"])

    def test_out_of_order_recent_messages_enter_correct_bucket(self):
        self.assertEqual(self.data.ingest_trades([trade(1008, 1), trade(1002, 2)], 1009), 2)
        self.assertEqual(self.data.stats()["buckets"], 2)
        self.assertEqual(self.data.context("BTC", 1009)["latest_trade_age_seconds"], 1)

    def test_oi_delta_is_true_observed_minute_and_not_five_second_extrapolation(self):
        self.data.add_open_interest("BTC", 1000, 100)
        self.data.add_open_interest("BTC", 1055, 110)
        self.data.add_open_interest("BTC", 1060, 111)
        ctx = self.data.context("BTC", 1060)
        self.assertAlmostEqual(ctx["oi_delta_60s"], .11)
        self.assertEqual(ctx["oi_window_seconds"], 60)

    def test_five_second_oi_warmup_has_no_minute_delta(self):
        self.data.add_open_interest("BTC", 1000, 100)
        self.data.add_open_interest("BTC", 1005, 110)
        self.assertIsNone(self.data.context("BTC", 1005)["oi_delta_60s"])

    def test_stale_oi_or_missing_anchor_is_unavailable(self):
        self.data.add_open_interest("BTC", 1000, 100)
        self.data.add_open_interest("BTC", 1060, 110)
        ctx = self.data.context("BTC", 1080)
        self.assertFalse(ctx["oi_data_fresh"])
        self.assertIsNone(ctx["oi_delta_60s"])
        self.data.add_open_interest("ETH", 1000, 100)
        self.data.add_open_interest("ETH", 1075, 110)
        self.assertIsNone(self.data.context("ETH", 1075)["oi_delta_60s"])

    def test_oi_anchor_tolerance_is_bounded_and_not_rescaled(self):
        self.data.add_open_interest("BTC", 1000, 100)
        self.data.add_open_interest("BTC", 1066, 110)
        ctx = self.data.context("BTC", 1066)
        self.assertAlmostEqual(ctx["oi_delta_60s"], .10)
        self.assertEqual(ctx["oi_window_seconds"], 66)

    def test_out_of_order_invalid_and_duplicate_oi_observations(self):
        self.assertTrue(self.data.add_open_interest("BTC", 1000, 100))
        self.assertFalse(self.data.add_open_interest("BTC", 999, 10000))
        self.assertFalse(self.data.add_open_interest("BTC", 1005, "nan"))
        self.assertFalse(self.data.add_open_interest("BTC", 1005, -1))
        self.data.add_open_interest("BTC", 1000, 101)
        self.data.add_open_interest("BTC", 1060, 111)
        self.assertAlmostEqual(self.data.context("BTC", 1060)["oi_delta_60s"], 111 / 101 - 1)

    def test_retention_and_duplicate_cache_are_bounded(self):
        data = RollingMarketData(retention_seconds=90, max_seen_per_symbol=16)
        data.mark_connected(1000, ["BTC"])
        for index in range(200):
            epoch = 1001 + index
            data.ingest_trades([trade(epoch, index)], epoch)
        stats = data.stats()
        self.assertLessEqual(stats["dedup_entries"], 16)
        self.assertLessEqual(stats["buckets"], 20)

    def test_parallel_duplicate_ingestion_is_idempotent(self):
        row = trade(1001, 1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.data.ingest_trades([row], 1001), range(40)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.data.stats()["accepted"], 1)

    def test_dedup_capacity_overflow_invalidates_signal_instead_of_recounting(self):
        data = RollingMarketData(max_seen_per_symbol=2)
        data.mark_connected(1000, ["BTC"])
        rows = [trade(1001, i) for i in range(3)]
        self.assertEqual(data.ingest_trades(rows, 1001), 2)
        self.assertEqual(data.ingest_trades(rows, 1002), 0)
        ctx = data.context("BTC", 1002)
        self.assertFalse(ctx["trade_data_fresh"])
        self.assertIn("dedup_capacity", ctx["trade_data_error"])
        data.heartbeat(1010)
        data.ingest_trades([trade(1014, 99)], 1014)
        self.assertEqual(data.context("BTC", 1014)["trade_coverage_seconds"], 0)
        self.assertFalse(data.context("BTC", 1014)["trade_data_fresh"])


if __name__ == "__main__":
    unittest.main()
