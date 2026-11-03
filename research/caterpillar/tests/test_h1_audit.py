"""Independent H1 causality/continuity regressions; no exchange connections."""
import json
from pathlib import Path
import tempfile
import unittest

from caterpillar.engine import ResearchEngine
from caterpillar.h1 import H1Tracker
from caterpillar.model import Config, Local, Trade
from caterpillar.output import Output


BASE = 360000.0  # exactly a UTC hour


def candle(index, low, high):
    start = BASE+index*3600
    return {"open_ts": start, "available_ts": start+3600, "open": (low+high)/2,
            "high": high, "low": low, "close": (low+high)/2, "volume": 100.0}


class H1CausalityAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engines = []

    def tearDown(self):
        for engine in self.engines:
            engine.finish()
        self.tmp.cleanup()

    def engine(self, name="run", config=None):
        cfg = config or Config(block_trades=2, warmup_blocks=2)
        output = Output(self.root/name, cfg, ("ZEC",), "synthetic_h1_audit")
        engine = ResearchEngine(output, cfg, ("ZEC",))
        self.engines.append(engine)
        return engine

    def seed(self, engine, index, low, high):
        c = candle(index, low, high)
        return engine.seed_h1("ZEC", c, as_of=c["available_ts"])

    def prefix(self, engine):
        for i in range(4):
            self.seed(engine, i, 100-i, 110-i)

    def rows(self, engine, name):
        engine.output.flush()
        return [json.loads(line) for line in (engine.output.root/(name+".jsonl")).read_text().splitlines()]

    def confirmed(self, engine):
        return [row for row in self.rows(engine, "locals") if row["stage"] == "CONFIRMED"]

    def test_seed_future_hour_is_rejected_without_future_local(self):
        engine = self.engine()
        c = candle(0, 100, 110)
        with self.assertRaises(ValueError):
            engine.seed_h1("ZEC", c, as_of=c["available_ts"]-.001)
        self.assertEqual(self.confirmed(engine), [])
        self.assertEqual(len(engine.states["ZEC"].h1.history), 0)

    def test_hourly_lower_low_needs_later_closed_higher_low(self):
        engine = self.engine()
        self.prefix(engine)
        self.seed(engine, 4, 95, 106)
        self.assertEqual(self.confirmed(engine), [])
        self.seed(engine, 5, 94, 105)  # a new lower low must update, never confirm 95
        self.assertEqual(self.confirmed(engine), [])
        self.seed(engine, 6, 95, 104)
        lows = [row for row in self.confirmed(engine) if row["local"]["kind"] == "LOW"]
        self.assertEqual(len(lows), 1)
        self.assertEqual(lows[0]["local"]["price"], 94)
        self.assertEqual(lows[0]["local"]["confirmed_ts"], candle(6, 95, 104)["available_ts"])

    def test_ohlcv_cannot_invent_an_exact_intrahour_extreme_time(self):
        engine = self.engine()
        self.prefix(engine)
        self.seed(engine, 4, 95, 106)
        self.seed(engine, 5, 96, 105)
        lows = [row for row in self.confirmed(engine) if row["local"]["kind"] == "LOW"]
        self.assertTrue(lows)
        self.assertIsNone(lows[0]["local"]["extreme_ts"])
        self.assertEqual(lows[0]["local"]["timeframe"], "1h")

    def test_missing_closed_hour_cannot_confirm_previous_candidate(self):
        engine = self.engine()
        self.prefix(engine)
        self.seed(engine, 4, 95, 106)
        # Hour 5 is unavailable. A later higher low does not bridge that missing hour.
        self.seed(engine, 6, 96, 105)
        self.assertEqual(self.confirmed(engine), [])

    def test_tape_gap_preserves_verified_closed_history(self):
        engine = self.engine()
        self.prefix(engine)
        before = list(engine.states["ZEC"].h1.history)
        engine.gap("ZEC", BASE+4*3600+60, "synthetic_transport_gap")
        self.assertEqual(list(engine.states["ZEC"].h1.history), before)

    def test_fast_tick_reversal_inside_hour_cannot_confirm_h1_local(self):
        engine = self.engine()
        self.prefix(engine)
        # 300 tick reversals remain within one forming H1 and cannot become closed-H1 locals.
        start = BASE+4*3600+10
        for i in range(300):
            price = 95+(i % 20 if (i//20) % 2 else 20-i % 20)*.1
            engine.on_trade(Trade("ZEC", start+i, price, 1, 1 if i % 2 else -1, str(i)))
        self.assertEqual(self.confirmed(engine), [])

    def test_delayed_preseed_tick_cannot_use_future_hour(self):
        engine = self.engine()
        self.prefix(engine)
        self.seed(engine, 4, 95, 106)
        self.seed(engine, 5, 96, 105)
        last_close = candle(5, 96, 105)["available_ts"]
        self.assertFalse(engine.on_trade(Trade("ZEC", last_close-.5, 101, 1, 1, "delayed")))
        self.assertEqual(engine.states["ZEC"].seq, 0)

    def test_first_post_gap_hour_is_partial_when_reconnect_misses_its_start(self):
        tracker = H1Tracker()
        tracker.tick(Trade("ZEC", BASE, 100, 1, 1, "first"))
        tracker.tick(Trade("ZEC", BASE+3590, 101, 1, 1, "before-gap"))
        tracker.mark_gap()
        tracker.tick(Trade("ZEC", BASE+3600+30, 102, 1, 1, "after-gap"))
        self.assertFalse(tracker.current_complete)

    def test_closed_h1_availability_cannot_move_backward(self):
        tracker = H1Tracker()
        first = candle(0, 100, 110)
        first["available_ts"] = BASE+3*3600
        tracker.seed(first, as_of=BASE+3*3600)
        second = candle(1, 99, 109)
        with self.assertRaises(ValueError):
            tracker.seed(second, as_of=BASE+3*3600)

    def test_explicit_non_hour_timeframe_cannot_be_seeded_as_h1(self):
        for interval in (1, 15, 120, 1440):
            engine = self.engine("interval-"+str(interval))
            c = candle(0, 100, 110)
            c["interval_minutes"] = interval
            with self.assertRaises(ValueError):
                engine.seed_h1("ZEC", c, as_of=c["available_ts"])

    def test_new_closed_h1_applies_before_pending_entry_fill(self):
        engine = self.engine(config=Config(block_trades=2, warmup_blocks=2, gap_seconds=4000))
        for i in range(4):
            self.seed(engine, i, 100+i, 110+i)
        self.seed(engine, 4, 104, 115)
        start = BASE+5*3600
        for i, (delta, price) in enumerate(((0, 111), (100, 114), (200, 105), (3599.5, 111))):
            engine.on_trade(Trade("ZEC", start+delta, price, 1, 1, "hour/"+str(i)))
        state = engine.states["ZEC"]
        state.locals["LOW"].append(Local(999, "LOW", 90, None, BASE, "CONFIRMED", BASE+3600))
        book = state.books["combined"]
        book.pending = {"action": "OPEN", "ts": start+3599.5, "event_seq": state.seq,
                        "side": 1, "local_id": 999, "local_price": 90, "snapshot": {}, "parent_exit": None}
        engine.on_trade(Trade("ZEC", start+3600.5, 111, 1, 1, "new-hour"))
        self.assertTrue(any(row["local"]["kind"] == "HIGH" for row in self.confirmed(engine)))
        self.assertIsNone(book.position)
        self.assertTrue(any("OPPOSITE_LOCAL_BEFORE_FILL" in row.get("reasons", [])
                            for row in self.rows(engine, "rejected_signals")))

    def test_h1_seed_decisions_are_prefix_invariant(self):
        a, b = self.engine("a"), self.engine("b")
        for engine in (a, b):
            self.prefix(engine)
            self.seed(engine, 4, 95, 106)
            self.seed(engine, 5, 96, 105)
        stop = candle(5, 96, 105)["available_ts"]
        self.seed(b, 6, 97, 107)
        self.seed(b, 7, 98, 108)
        left = self.rows(a, "locals")
        right = [row for row in self.rows(b, "locals") if row["ts"] <= stop]
        self.assertEqual(left, right)

    def test_bootstrap_journal_does_not_backdate_observation_events(self):
        engine = self.engine()
        observed = BASE+10*3600
        for i in range(4):
            engine.seed_h1('ZEC', candle(i, 100-i, 110-i), as_of=observed)
        engine.seed_h1('ZEC', candle(4, 95, 106), as_of=observed)
        engine.seed_h1('ZEC', candle(5, 96, 105), as_of=observed)
        rows = self.rows(engine, 'locals')
        self.assertTrue(all(row['ts'] == observed for row in rows))
        confirmations = [row for row in rows if row['stage'] == 'CONFIRMED']
        self.assertTrue(confirmations)
        self.assertLess(confirmations[0]['local']['confirmed_ts'], observed)


if __name__ == "__main__":
    unittest.main()
