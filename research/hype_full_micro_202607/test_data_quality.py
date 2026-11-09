from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import polars as pl

from research.hype_full_micro_202607.build_full_micro import (
    H,
    book_features,
    book_replay,
    enrich,
    liq_features,
    liquidation_events,
    scalar_snapshots,
)


BUILDER = "research.hype_full_micro_202607.build_full_micro"
T0 = 1_783_875_600_000


def book_tape(messages):
    return pl.DataFrame([
        dict(received_time=T0+seconds*1000, event_type=kind, final_update_id=sequence,
             side=side, price=price, quantity=quantity)
        for seconds, kind, sequence, levels in messages
        for side, price, quantity in levels
    ])


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

    def test_unreadable_liquidation_partition_stays_unavailable_in_enrichment(self):
        hour = datetime.fromtimestamp(T0/1000, tz=timezone.utc)
        src = Mock(missing=[], downloads=1, bytes=100)
        src.path.return_value = "invalid-liq.parquet"
        records = [{"snapshot_ts_ms":T0+30_000, "features":{}}]
        with (TemporaryDirectory() as tmp, patch(f"{BUILDER}.START", hour),
              patch(f"{BUILDER}.END", hour+timedelta(hours=1)),
              patch(f"{BUILDER}.read_parquet", return_value=None), patch("builtins.print")):
            bad = Path(tmp)/"invalid-liq.parquet"
            src.get.side_effect = lambda dt, kind: bad if dt == hour and kind == "liquidations" else None
            f = enrich(src, records, {})[0]["features"]
        self.assertEqual(f["fullmicro_liq_stream_valid_5s"], 0.0)
        self.assertNotIn("fullmicro_liq_count_5s", f)
        self.assertIn("invalid-liq.parquet", src.missing)

    def test_liquidation_decoder_distinguishes_empty_from_invalid_schema_or_side(self):
        schema = {"event_time":pl.Int64, "price":pl.Float64,
                  "quantity":pl.Float64, "side":pl.String}
        empty = pl.DataFrame(schema=schema)
        self.assertEqual(liquidation_events(empty), ([], list(schema)))
        self.assertEqual(liquidation_events(empty.drop("side")), ([], []))
        valid = pl.DataFrame([(T0, 10.0, 2.0, "Sell"), (T0+1, 10.0, 3.0, "Buy")],
                             schema=schema, orient="row")
        self.assertEqual(liquidation_events(valid)[0], [(T0, 20.0, "LONG"), (T0+1, 30.0, "SHORT")])
        self.assertEqual(liquidation_events(valid.with_columns(pl.lit("?").alias("side"))), ([], []))

    def test_liquidations_and_oi_are_unavailable_until_received(self):
        row = pl.DataFrame({"event_time":[T0], "received_time":[T0+1000],
                            "price":[10.0], "quantity":[2.0], "side":["Sell"],
                            "sum_open_interest":[123.0]})
        events,_ = liquidation_events(row)
        covered = {T0-H,T0}
        self.assertEqual(liq_features(events,T0+500,covered)["fullmicro_liq_count_5s"],0.0)
        self.assertEqual(liq_features(events,T0+1000,covered)["fullmicro_liq_count_5s"],1.0)
        snaps,carry,_ = scalar_snapshots(row, [T0+500,T0+1000])
        self.assertNotIn("sum_open_interest", snaps[T0+500])
        self.assertEqual(snaps[T0+1000]["_ts_ms"],T0+1000)
        before_receipt,_,_ = scalar_snapshots(None, [T0+500], carry)
        self.assertNotIn("sum_open_interest", before_receipt[T0+500])

    def test_book_gap_and_resnapshot_restart_rolling_windows(self):
        base = [("bid",99,1),("ask",100,1)]
        tape = book_tape([
            (0,"snapshot",10,base), (20,"delta",11,[("bid",99,3)]),
            (70,"delta",13,[("bid",99,4)]), (75,"snapshot",20,base),
            (80,"delta",21,[("bid",99,2)]),
        ])
        times = [T0+s*1000 for s in (65,72,90,136)]
        with patch(f"{BUILDER}.read_parquet", return_value=tape):
            snaps,_,_ = book_replay(Path("unused"), times)
        good, gap, restored, warmed = (snaps[t] for t in times)
        self.assertEqual(good["fullmicro_bid_replenish_notional_60s"],198.0)
        self.assertEqual(gap["fullmicro_book_valid"],0.0)
        self.assertEqual(restored["fullmicro_book_valid"],1.0)
        self.assertEqual(restored["fullmicro_book_window_valid_60s"],0.0)
        self.assertNotIn("fullmicro_bid_replenish_notional_60s",restored)
        self.assertEqual(warmed["fullmicro_book_window_valid_60s"],1.0)
        self.assertEqual(warmed["fullmicro_bid_replenish_notional_60s"],99.0)

    def test_crossed_book_between_decisions_resets_rolling_window(self):
        tape = book_tape([
            (0,"snapshot",10,[("bid",99,1),("ask",100,1)]),
            (10,"delta",11,[("bid",101,1)]), (12,"delta",12,[("bid",101,0)]),
        ])
        times = [T0+s*1000 for s in (11,65,73)]
        with patch(f"{BUILDER}.read_parquet", return_value=tape):
            snaps,_,_ = book_replay(Path("unused"), times)
        crossed, restored, warmed = (snaps[t] for t in times)
        self.assertEqual(crossed["fullmicro_book_crossed"],1.0)
        self.assertEqual(restored["fullmicro_book_valid"],1.0)
        self.assertEqual(restored["fullmicro_book_window_valid_60s"],0.0)
        self.assertEqual(warmed["fullmicro_book_window_valid_60s"],1.0)

    def test_book_time_regression_invalidates_and_future_state_is_masked(self):
        tape = book_tape([
            (0,"snapshot",10,[("bid",99,1),("ask",100,1)]),
            (20,"delta",11,[("bid",99,2)]), (10,"delta",12,[("bid",99,3)]),
        ])
        with patch(f"{BUILDER}.read_parquet", return_value=tape):
            snaps, state, _ = book_replay(Path("unused"), [T0+15_000,T0+30_000])
        self.assertEqual(snaps[T0+15_000]["fullmicro_book_valid"],1.0)
        self.assertEqual(snaps[T0+30_000]["fullmicro_book_valid"],0.0)
        self.assertEqual(book_features(dict(state, valid=True),T0+19_000)["fullmicro_book_valid"],0.0)


if __name__=="__main__":
    unittest.main()
