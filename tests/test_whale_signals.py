import copy
import unittest

from whale_signals import (MIN_NOTIONAL_USD, cluster_positions, significance,
                           summarize_book, update_streaks)


EPOCH = 1_800_000_000.0


def context(mark=100.0):
    return {"epoch": EPOCH, "mark_price": mark, "open_interest": 10_000_000.0,
            "volume_source": "hyperliquid_ws_trades", "trade_data_fresh": True,
            "trade_coverage_seconds": 120.0,
            "buy_volume_60s": 1_000_000.0, "sell_volume_60s": 1_000_000.0}


def position(wallet="0x1", size=30_000_000, level=99.5, **changes):
    result = {"symbol": "BTC", "side": "long", "address": wallet,
              "size_usd": size, "liq_price": level, "scanned_at": EPOCH-2}
    result.update(changes)
    return result


def cluster(**changes):
    result = {"symbol": "BTC", "side": "long", "victim_side": "long",
              "size_usd": 30_000_000.0, "evaluated_at": EPOCH}
    result.update(changes)
    return result


def book(**changes):
    result = {"bid_depth_usd": 10_000_000.0, "ask_depth_usd": 50_000_000.0,
              "bid_depth_complete": True, "ask_depth_complete": True,
              "spread_bps": 2.0, "depth_bps": 10.0, "epoch": EPOCH}
    result.update(changes)
    return result


class ClusterTests(unittest.TestCase):
    def make(self, rows, ctx=None):
        return cluster_positions(rows, {"BTC": 100.0}, {"BTC": ctx or context()}, EPOCH)

    def test_duplicate_wallet_uses_freshest_position_without_double_counting(self):
        rows = [position(size=50_000_000, scanned_at=EPOCH-10),
                position(size=30_000_000, scanned_at=EPOCH-2),
                position(size=30_000_000, scanned_at=EPOCH-2)]
        result = self.make(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["size_usd"], 30_000_000)
        self.assertEqual(result[0]["wallet_count"], 1)
        self.assertEqual(result[0]["trade_side"], -1)

    def test_nearby_distinct_wallets_form_one_cluster(self):
        rows = [position("0x1", size=15_000_000, level=99.50),
                position("0x2", size=20_000_000, level=99.55),
                position("0x3", size=40_000_000, level=99.80)]
        before = copy.deepcopy(rows)
        result = self.make(rows)
        self.assertEqual(rows, before)
        self.assertEqual(sorted(r["size_usd"] for r in result), [35_000_000, 40_000_000])
        combined = next(r for r in result if r["wallet_count"] == 2)
        self.assertAlmostEqual(combined["liq_price"], (15*99.50+20*99.55)/35)

    def test_cluster_does_not_chain_levels_beyond_ten_bps(self):
        result = self.make([position("a", level=99.4), position("b", level=99.47),
                            position("c", level=99.54)])
        self.assertEqual(len(result), 2)
        self.assertEqual(sorted(r["wallet_count"] for r in result), [1, 2])

    def test_cluster_identity_is_stable_under_small_level_changes(self):
        first = self.make([position("a", level=99.5), position("b", level=99.53)])[0]
        second = self.make([position("b", level=99.54), position("a", level=99.51)])[0]
        self.assertEqual(first["cluster_id"], second["cluster_id"])

    def test_short_victim_requires_higher_level_and_long_trade(self):
        result = self.make([position(side="short", level=100.5)])
        self.assertEqual(result[0]["trade_side"], 1)
        self.assertEqual(result[0]["victim_side"], "short")

    def test_stale_future_and_invalid_positions_are_rejected(self):
        bad = [position(scanned_at=EPOCH-181), position(scanned_at=EPOCH+0.01),
               position(size=-1), position(size=float("nan")), position(size=float("inf")),
               position(level=100.0), position(level=101.0), position(address=""),
               position(side="unknown"), position(symbol="DOGE")]
        for row in bad:
            with self.subTest(row=row):
                self.assertEqual(self.make([row]), [])

    def test_scanned_at_milliseconds_is_normalized(self):
        result = self.make([position(scanned_at=(EPOCH-5)*1000)])[0]
        self.assertEqual(result["position_age_seconds"], 5)

    def test_missing_stale_and_future_mark_context_cannot_use_mid_price(self):
        for change in ({"epoch": EPOCH-16}, {"epoch": EPOCH+1}, {"mark_price": None},
                       {"mark_price": float("nan")}):
            ctx = context();ctx.update(change)
            with self.subTest(change=change):
                self.assertEqual(self.make([position()], ctx), [])


class BookTests(unittest.TestCase):
    def test_depth_uses_price_band_not_fixed_number_of_levels(self):
        raw = {"time": EPOCH*1000, "levels": [
            [{"px": 99.99, "sz": 10}, {"px": 99.95, "sz": 20},
             {"px": 99.80, "sz": 1_000_000}],
            [{"px": 100.01, "sz": 10}, {"px": 100.05, "sz": 10},
             {"px": 100.20, "sz": 1_000_000}]]}
        result = summarize_book(raw)
        self.assertAlmostEqual(result["bid_depth_usd"], 99.99*10+99.95*20)
        self.assertAlmostEqual(result["ask_depth_usd"], 100.01*10+100.05*10)
        self.assertTrue(result["bid_depth_complete"])
        self.assertTrue(result["ask_depth_complete"])
        self.assertEqual(result["epoch"], EPOCH)

    def test_truncated_ladder_explicitly_reports_incomplete_coverage(self):
        raw = {"time": EPOCH*1000, "levels": [[{"px": 99.99, "sz": 1}],
                                                  [{"px": 100.01, "sz": 1}]]}
        result = summarize_book(raw)
        self.assertFalse(result["bid_depth_complete"])
        self.assertFalse(result["ask_depth_complete"])

    def test_crossed_empty_nonfinite_orderbooks_are_rejected(self):
        for raw in ({}, {"levels": [[], []]}, {"levels": [[{"px": 101, "sz": 1}],
                                                              [{"px": 100, "sz": 1}]]},
                    {"levels": [[{"px": float("nan"), "sz": 1}],
                                 [{"px": 100, "sz": 1}]]}):
            with self.subTest(raw=raw):
                self.assertIsNone(summarize_book(raw))


class SignificanceTests(unittest.TestCase):
    def test_existing_two_to_five_million_levels_do_not_qualify_for_btc_eth(self):
        for symbol, size in (("BTC", 5_000_000), ("ETH", 3_000_000), ("SOL", 2_000_000)):
            with self.subTest(symbol=symbol):
                result = significance(cluster(symbol=symbol, size_usd=size), book(), context())
                self.assertFalse(result["allowed"])
                self.assertEqual(result["reason"], "insignificant_cluster_notional")
                self.assertEqual(result["floor_notional_usd"], MIN_NOTIONAL_USD[symbol])

    def test_material_cluster_needs_both_notional_and_depth_impact(self):
        result = significance(cluster(), book(), context())
        self.assertTrue(result["allowed"])
        self.assertEqual(result["minimum_notional_usd"], 25_000_000)
        self.assertEqual(result["forced_flow_first_slice_usd"], 6_000_000)
        self.assertAlmostEqual(result["liquidation_flow_to_depth"], 0.6)
        result = significance(cluster(), book(bid_depth_usd=30_000_000), context())
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "insignificant_liquidation_impact")

    def test_oi_relative_floor_can_be_higher_than_absolute_floor(self):
        ctx = context();ctx["open_interest_usd"] = 20_000_000_000
        result = significance(cluster(), book(), ctx)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["minimum_notional_usd"], 50_000_000)

    def test_actual_minute_volume_can_raise_notional_threshold(self):
        ctx = context();ctx.update(buy_volume_60s=15_000_000, sell_volume_60s=10_000_000)
        result = significance(cluster(), book(), ctx)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["minimum_notional_usd"], 50_000_000)

    def test_victim_side_selects_correct_opposing_ladder(self):
        self.assertTrue(significance(cluster(), book(), context())["allowed"])
        result = significance(cluster(side="short", victim_side="short"), book(), context())
        self.assertFalse(result["allowed"])
        self.assertAlmostEqual(result["liquidation_flow_to_depth"], 0.12)

    def test_missing_or_proxy_trade_flow_cannot_qualify(self):
        for change in ({"volume_source": "rolling_24h_difference"}, {"trade_data_fresh": False},
                       {"trade_coverage_seconds": 59.9}, {"buy_volume_60s": None},
                       {"sell_volume_60s": -1}):
            ctx = context();ctx.update(change)
            with self.subTest(change=change):
                result = significance(cluster(), book(), ctx)
                self.assertFalse(result["allowed"])
                self.assertEqual(result["reason"], "missing_observed_trade_flow")

    def test_missing_oi_incomplete_depth_or_stale_book_is_rejected(self):
        ctx = context();ctx["open_interest"] = None
        self.assertEqual(significance(cluster(), book(), ctx)["reason"], "missing_open_interest")
        for change, reason in (({"bid_depth_complete": False}, "insufficient_book_depth_coverage"),
                               ({"epoch": EPOCH-6}, "stale_or_missing_orderbook_time"),
                               ({"epoch": EPOCH+1}, "stale_or_missing_orderbook_time"),
                               ({"spread_bps": 13}, "invalid_or_wide_orderbook")):
            with self.subTest(change=change):
                self.assertEqual(significance(cluster(), book(**change), context())["reason"], reason)


class StreakTests(unittest.TestCase):
    def test_duplicate_positions_in_one_scan_are_only_one_confirmation(self):
        rows = [{"cluster_id": "a"}, {"cluster_id": "a"}]
        state = update_streaks(rows, {}, "scan1")
        self.assertEqual([r["confirmation_streak"] for r in rows], [1, 1])
        state = update_streaks(rows, state, "scan1")
        self.assertEqual(state["a"]["count"], 1)
        state = update_streaks(rows, state, "scan2")
        self.assertEqual(state["a"]["count"], 2)

    def test_absent_clusters_reset_and_new_cluster_starts_at_one(self):
        state = update_streaks([{"cluster_id": "a"}], {}, 1)
        state = update_streaks([], state, 2)
        state = update_streaks([{"cluster_id": "a"}], state, 3)
        self.assertEqual(state["a"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
