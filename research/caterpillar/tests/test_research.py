from dataclasses import asdict
from datetime import datetime, timezone
import csv
import gzip
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from caterpillar.engine import ResearchEngine
from caterpillar.model import Config, Local, Position, SYMBOLS, Trade, features, robust_z
from caterpillar.output import Output
from caterpillar.realtime import Ingress, parse_frame
from caterpillar.sources import Archives, SourceError, archive_row, file_sha, historical, parse_symbols, replay


def synthetic(symbol="ZEC", cycles=3):
    """Known synthetic directional changes, not market/profitability evidence."""
    price, ts, counter = 100.0, 1700000000.0, 0
    blocks = [(-1, .85)]*10
    for _ in range(cycles):
        blocks += [(1, x) for x in (.58, .7, .82, .9, .96, .98)]
        blocks += [(-1, x) for x in (.58, .7, .82, .9, .96, .98)]
    for direction, dominance in blocks:
        for i in range(16):
            counter += 1
            ts += .1
            price *= 1+direction*.0002
            side = 1 if i % 2 == 0 else -1
            fraction = dominance if side == direction else 1-dominance
            yield Trade(symbol, ts, price, fraction*20, side, str(counter))


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = Config(block_trades=16, warmup_blocks=8, baseline_blocks=16,
                             local_vol_multiplier=.5, outcome_trades=32, post_exit_trades=48)

    def tearDown(self):
        self.tmp.cleanup()

    def engine(self, name="run", symbols=("ZEC",), config=None, split=None):
        cfg = config or self.config
        out = Output(self.root/name, cfg, symbols, "synthetic_test")
        return ResearchEngine(out, cfg, symbols, split)

    def rows(self, name, stream):
        return [json.loads(x) for x in (self.root/name/(stream+".jsonl")).read_text().splitlines()]

    def test_fixed_universe_and_config_validation(self):
        self.assertEqual(len(SYMBOLS), 10)
        for value in ("BTC", "ZEC,ZEC", ""):
            with self.assertRaises(ValueError): parse_symbols(value)
        for data in ({"fee_bps": math.nan}, {"block_trades": 2.5}, {"gap_seconds": 0}, {"exit_models": ("magic",)}):
            with self.assertRaises(ValueError): Config(**data)

    def test_new_lower_lows_never_confirm_by_themselves(self):
        e = self.engine()
        for t in list(synthetic())[:160]: e.on_trade(t)
        e.finish()
        rows = self.rows("run", "locals")
        self.assertTrue(all(row["stage"] == row["local"]["status"] for row in rows))
        self.assertTrue(any(x["stage"] == "UPDATED" for x in rows))
        self.assertFalse(any(x["stage"] == "CONFIRMED" for x in rows))
        self.assertFalse(self.rows("run", "trades"))

    def test_causal_confirmation_next_tick_fills_and_real_outcomes(self):
        e = self.engine()
        for t in synthetic(): e.on_trade(t)
        e.finish()
        locals_ = [r for r in self.rows("run", "locals") if r["stage"] == "CONFIRMED"]
        self.assertGreater(len(locals_), 1)
        for r in locals_:
            self.assertLess(r["local"]["extreme_ts"], r["flow"]["start_ts"])
            self.assertEqual(r["ts"], r["local"]["confirmed_ts"])
        trades = self.rows("run", "trades")
        opens = [r for r in trades if r["action"] in ("OPEN", "REENTRY")]
        closes = [r for r in trades if r["action"] == "CLOSE"]
        self.assertTrue(opens)
        self.assertTrue(closes)
        for r in opens+closes:
            self.assertGreater(r["ts"], r["signal_ts"])
        for r in closes:
            p = r["position"]
            expected = (r["exit_price"]-p["entry"])*p["side"]*p["quantity"]-r["fees_usd"]
            self.assertAlmostEqual(expected, r["net_usd_before_funding"])
            self.assertGreaterEqual(p["mfe"], p["current"])
            self.assertLessEqual(p["mae"], p["current"])
        self.assertTrue(any(x["status"] == "COMPLETE" for x in self.rows("run", "hypothesis_outcomes")))

    def test_prefix_invariance_no_future_decision_leakage(self):
        data = list(synthetic())
        prefix = data[:360]
        a, b = self.engine("a"), self.engine("b")
        for t in prefix: a.on_trade(t)
        for t in data: b.on_trade(t)
        a.output.flush(); b.output.flush()
        for stream in ("locals", "signals", "rejected_signals", "structure", "flow_events"):
            left = self.rows("a", stream)
            right = [r for r in self.rows("b", stream) if r["ts"] <= prefix[-1].ts]
            self.assertEqual(left, right, stream)
        a.finish(); b.finish()

    def test_mfe_marks_every_tick_between_blocks(self):
        e = self.engine()
        s = e.states["ZEC"]
        p = Position("p", 1, 100, 1, 10, 1, 90, {}, mfe_ts=1)
        s.books["combined"].position = p
        for i, price in enumerate((101, 110, 102)):
            e.on_trade(Trade("ZEC", 100+i, price, 1, 1, str(i)))
        self.assertEqual(p.mfe, 100)
        self.assertEqual(p.current, 20)
        self.assertEqual(p.mfe_ts, 101)
        e.finish()
        self.assertEqual(self.rows("run", "trades")[-1]["action"], "END_MARK")

    def test_dedup_late_invalid_and_gap_censoring(self):
        e = self.engine()
        good = Trade("ZEC", 100, 100, 1, 1, "1")
        self.assertTrue(e.on_trade(good))
        self.assertFalse(e.on_trade(good))
        self.assertFalse(e.on_trade(Trade("ZEC", 99, 100, 1, 1, "2")))
        self.assertFalse(e.on_trade(Trade("ZEC", 101, math.nan, 1, 1, "3")))
        e.states["ZEC"].books["combined"].position = Position("p", 1, 100, 100, 10, 1, 90, {})
        e.on_trade(Trade("ZEC", 200, 110, 1, 1, "4"))
        self.assertIsNone(e.states["ZEC"].books["combined"].position)
        e.finish()
        self.assertTrue(any(r["action"] == "CENSORED" for r in self.rows("run", "trades")))

    def test_non_overlapping_blocks_continue_after_capacity(self):
        e = self.engine()
        for t in synthetic(cycles=5): e.on_trade(t)
        e.finish()
        blocks = self.rows("run", "flow_events")
        self.assertEqual(len(blocks), (10+12*5))
        self.assertTrue(all(a["flow"]["ts"] < b["flow"]["start_ts"] for a, b in zip(blocks, blocks[1:])))
        self.assertLessEqual(len(e.states["ZEC"].history), 16)

    def test_constant_timestamp_stream_is_bounded_and_no_infinite_rates(self):
        e = self.engine()
        for i in range(2048): e.on_trade(Trade("ZEC", 100, 100, 1, 1, str(i)))
        self.assertLessEqual(len(e.states["ZEC"].forecasts), 8)
        e.finish()
        self.assertTrue(all(r["flow"]["trade_intensity"] is None for r in self.rows("run", "flow_events")))

    def test_feature_direction_efficiency_and_stable_robust_scale(self):
        block = [Trade("ZEC", 100+i, 100+i, 2 if i % 2 == 0 else 1, 1 if i % 2 == 0 else -1, str(i)) for i in range(16)]
        c = features(block, [], self.config)
        self.assertGreater(c["move_bps"], 0)
        self.assertGreater(c["buy_response_bps"], 0)
        self.assertLess(c["sell_efficiency_bps_per_10k"], 0)
        self.assertIsNone(c["buy_acceleration"])
        self.assertLessEqual(abs(robust_z(1e9, [1]*20)), 10)

    def test_split_boundary_censors_and_rewarms(self):
        data = list(synthetic())
        split = data[300].ts
        e = self.engine(split=split)
        for t in data[:310]: e.on_trade(t)
        self.assertLess(len(e.states["ZEC"].history), self.config.warmup_blocks)
        e.finish()
        self.assertTrue(any(r["reason"] == "evaluation_boundary" for r in self.rows("run", "data_quality")))
        self.assertFalse(any(r["status"] == "COMPLETE" and r.get("candidate", {}).get("ts", 0) < split < r["ts"] for r in self.rows("run", "hypothesis_outcomes")))

    def test_ohlcv_cannot_create_flow_or_trades(self):
        e = self.engine()
        for i in range(30):
            e.on_candle("ZEC", {"available_ts": 100+i*60, "open": 100, "high": 101+i, "low": 99-i, "close": 100, "volume": 1})
        e.finish()
        self.assertEqual(len(self.rows("run", "candles")), 30)
        self.assertEqual(self.rows("run", "trades"), [])
        self.assertEqual(self.rows("run", "flow_events"), [])

    def test_reports_all_symbols_no_false_research_results(self):
        e = self.engine(symbols=SYMBOLS)
        e.finish()
        profiles = json.loads((self.root/"run/token_profiles.json").read_text())
        self.assertEqual(set(profiles), {s+"_PROFILE" for s in SYMBOLS})
        candidate = json.loads((self.root/"run/caterpillar_24_7_candidates.json").read_text())
        self.assertFalse(candidate["deployment_ready"])
        self.assertEqual(candidate["candidates"], [])
        self.assertTrue((self.root/"run/CATERPILLAR_RESEARCH_REPORT.md").is_file())

    def test_output_refuses_existing_run(self):
        e = self.engine()
        with self.assertRaises(ValueError): self.engine()
        e.finish()

    def test_raw_replay_equivalence(self):
        a = self.engine("a")
        a.record_raw = True
        for t in synthetic(cycles=1): a.on_trade(t)
        a.finish()
        b = self.engine("b")
        replay(b, self.root/"a/raw_trades.jsonl")
        b.finish()
        for stream in ("signals", "trades", "locals", "flow_events"):
            self.assertEqual(self.rows("a", stream), self.rows("b", stream))

    def test_raw_replay_preserves_disconnect_without_timestamp_gap(self):
        a = self.engine("a")
        a.record_raw = True
        data = list(synthetic(cycles=1))
        for i, t in enumerate(data):
            if i == 300: a.gap("ZEC", t.ts, "simulated_disconnect")
            a.on_trade(t)
        a.finish()
        b = self.engine("b")
        replay(b, self.root/"a/raw_trades.jsonl")
        b.finish()
        for stream in ("signals", "trades", "locals", "flow_events"):
            self.assertEqual(self.rows("a", stream), self.rows("b", stream))

    def test_ingress_reorders_and_rejects_stale(self):
        e = self.engine()
        ingress = Ingress(e, reorder_seconds=2, max_lag_seconds=15)
        ingress.push(Trade("ZEC", 100.5, 100, 1, 1, "2"), 101)
        ingress.push(Trade("ZEC", 100, 99, 1, -1, "1"), 101)
        ingress.flush(104)
        self.assertEqual(e.states["ZEC"].seq, 2)
        self.assertEqual(e.states["ZEC"].last_ts, 100.5)
        ingress.push(Trade("ZEC", 50, 100, 1, 1, "old"), 104)
        self.assertEqual(len(e.states["ZEC"].block), 0)
        e.finish()

    def test_false_break_is_not_confirmed_structure_break(self):
        e = self.engine()
        s = e.states["ZEC"]
        s.locals["LOW"].append(Local(1, "LOW", 100, 50, 60, "CONFIRMED", 70))
        e.on_trade(Trade("ZEC", 100, 99, 1, -1, "1"))
        e.on_trade(Trade("ZEC", 101, 101, 1, 1, "2"))
        self.assertFalse(s.locals["LOW"][-1].invalidated)
        e.finish()
        self.assertTrue(any(r.get("event") == "FALSE_BREAK" for r in self.rows("run", "structure")))

    def test_archive_stream_schema_crc_cache_hash_and_chronology(self):
        day = datetime(2024, 1, 1, tzinfo=timezone.utc)
        source = Archives(self.root/"cache")
        name = "ZECUSDT2024-01-01.csv.gz"
        path = source.cache/name
        with gzip.open(path, "wt") as f:
            f.write("timestamp,symbol,side,size,price,trdMatchID\n")
            f.write(f"{day.timestamp()},ZECUSDT,Buy,2,100,a\n")
            f.write(f"{day.timestamp()+1},ZECUSDT,Sell,3,99,b\n")
        meta = {"url": "https://public.bybit.com/trading/ZECUSDT/"+name, "sha256": file_sha(path)}
        (source.cache/(name+".json")).write_text(json.dumps(meta))
        trades, _ = source.trades("ZEC", day)
        rows = list(trades)
        self.assertEqual(rows[0].notional, 200)
        self.assertEqual(rows[1].side, -1)
        path.write_bytes(path.read_bytes()+b"corrupt")
        with self.assertRaises(SourceError): source.obtain("ZEC", day)

    def test_missing_archive_never_synthesizes_flow(self):
        e = self.engine()
        with patch.object(Archives, "trades", side_effect=SourceError("Archive HTTP 404")):
            status = historical(e, self.root/"cache", datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 1, 2, tzinfo=timezone.utc))
        self.assertEqual(status, "incomplete_coverage")
        self.assertEqual(e.profiles["ZEC"].counts.get("accepted_trades", 0), 0)
        e.finish(status)

    def test_bybit_frame_is_strict_and_preserves_exchange_time(self):
        data = {"topic": "publicTrade.ZECUSDT", "data": [{"s": "ZECUSDT", "T": 100000, "p": "100", "v": "2", "S": "Sell", "i": "abc"}]}
        trades, _ = parse_frame(json.dumps(data), ("ZEC",), 101)
        self.assertEqual(trades[0].ts, 100)
        self.assertEqual(trades[0].side, -1)
        data["data"][0]["S"] = "Unknown"
        with self.assertRaises(SourceError): parse_frame(json.dumps(data), ("ZEC",), 101)

    def test_short_costs_mfe_and_mae(self):
        p = Position("short", -1, 100, 1, 10, 1, 110, {})
        p.mark(90, 2, 4.5, 2)
        p.mark(105, 3, 4.5, 2)
        self.assertEqual(p.mfe, 100)
        self.assertEqual(p.mae, -50)
        self.assertEqual(p.mfe_ts, 2)
        self.assertLess(p.net_mfe, p.mfe)

    def test_all_ten_symbols_have_independent_books_and_profiles(self):
        e = self.engine(symbols=SYMBOLS)
        for symbol in SYMBOLS:
            for t in synthetic(symbol, cycles=1): e.on_trade(t)
        e.finish()
        profiles = json.loads((self.root/"run/token_profiles.json").read_text())
        counts = [profiles[s+"_PROFILE"]["counts"]["accepted_trades"] for s in SYMBOLS]
        self.assertEqual(len(set(counts)), 1)
        for symbol in SYMBOLS:
            self.assertGreater(profiles[symbol+"_PROFILE"]["counts"]["combined/closed"], 0)

    def test_reentry_requires_correction_and_original_local(self):
        e = self.engine()
        s = e.states["ZEC"]
        data = list(synthetic(cycles=1))
        for t in data[:10*16]: e.on_trade(t)
        anchor = Local(999, "LOW", 80, 1, 2, "CONFIRMED", 3)
        s.locals["LOW"].append(anchor)
        s.candidate = None
        book = s.books["combined"]
        book.watch = {"side": 1, "local_id": 999, "exit_id": "exit", "exit_price": 50,
                      "correction_seen": False, "expires_seq": s.seq+1000}
        # Price stays above 50: no correction has been observed; re-entry must be forbidden.
        for t in data[10*16:12*16]: e.on_trade(t)
        self.assertIsNone(book.position)
        self.assertIsNone(book.pending)
        e.output.flush()
        rejects = [r for r in self.rows("run", "rejected_signals") if r["model"] == "combined" and r["action"] == "REENTRY"]
        self.assertTrue(any("NO_CORRECTION_OBSERVED" in r["reasons"] for r in rejects))
        anchor.invalidated = True
        for t in data[12*16:13*16]: e.on_trade(t)
        self.assertIsNone(book.watch)
        e.finish()

    def test_control_transfer_requires_multiple_blocks(self):
        e = self.engine()
        s = e.states["ZEC"]
        # Inject a known position and valid structure to isolate exit hysteresis.
        s.locals["LOW"].append(Local(1, "LOW", 50, 1, 2, "CONFIRMED", 3))
        p = Position("p", 1, 100, 3, 10, 1, 50, {})
        s.books["combined"].position = p
        ts, price = 100, 100
        for block in range(2):
            for i in range(16):
                ts += .1; price *= .999
                e.on_trade(Trade("ZEC", ts, price, 2 if i % 2 else .1, -1 if i % 2 else 1, str(block*16+i)))
            self.assertEqual(p.opposite_streak, block+1)
            if block == 0:
                self.assertIsNone(s.books["combined"].pending)
        self.assertIsNotNone(s.books["combined"].pending)
        e.finish()

    def test_successful_reentry_fill_and_good_bad_outcome_label(self):
        e = self.engine()
        s = e.states["ZEC"]
        s.seq = 200
        s.locals["LOW"].append(Local(1, "LOW", 90, 1, 2, "CONFIRMED", 3))
        s.candidate = Local(2, "HIGH", 120, 10, 10)
        block = [Trade("ZEC", 100+i*.1, 100+i*.1, 9 if i % 2 == 0 else 1,
                       1 if i % 2 == 0 else -1, str(i)) for i in range(16)]
        old = features(block, [], self.config)
        old.update(buy_rate=old["buy_rate"]*.5, sell_rate=old["sell_rate"]*2)
        for _ in range(8): s.history.append(old.copy())
        s.block = block
        c = features(block, s.history, self.config)
        book = s.books["combined"]
        book.watch = {"side": 1, "local_id": 1, "exit_id": "previous-exit", "exit_price": 102,
                      "correction_seen": True, "expires_seq": 1000}
        e._evaluate(s, c)
        self.assertEqual(book.pending["action"], "REENTRY")
        s.block.clear()
        e.on_trade(Trade("ZEC", 103, 102, 1, 1, "fill"))
        self.assertTrue(book.position.reentry)
        self.assertEqual(book.position.parent_exit, "previous-exit")
        book.pending = {"action": "CLOSE", "ts": 103, "reasons": ["opposite_flow"], "snapshot": {}}
        e.on_trade(Trade("ZEC", 104, 105, 1, 1, "exit"))
        e.finish()
        self.assertTrue(any(r.get("label") == "GOOD_REENTRY" for r in self.rows("run", "hypothesis_outcomes")))

    def test_ingress_overflow_censors_and_flushes_without_invented_fills(self):
        e = self.engine()
        ingress = Ingress(e, reorder_seconds=2, max_lag_seconds=15, max_buffer=1)
        ingress.push(Trade("ZEC", 100, 100, 1, 1, "a"), 100)
        with self.assertRaises(SourceError): ingress.push(Trade("ZEC", 100.1, 100, 1, 1, "b"), 100.1)
        self.assertEqual(len(ingress.heap), 0)
        self.assertEqual(e.states["ZEC"].seq, 0)
        e.finish()


if __name__ == "__main__":
    unittest.main()
