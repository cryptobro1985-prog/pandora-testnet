"""Regression tests for Caterpillar research v2: hypothesis breadth, progress and resume."""
from __future__ import annotations

from collections import deque
import json
from pathlib import Path
import tempfile
import unittest

from caterpillar.engine import ResearchEngine
from caterpillar.h1 import H1Bar
from caterpillar.model import Config, Local, Trade
from caterpillar.output import Output, Profile
from caterpillar.realtime import parse_context
from caterpillar.reporting import persist_status, render_hourly_report
from caterpillar.research_layer import MultiLocalResearch, dual_side_entry_research, local_flow_evidence


class V2ResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def bar(self, index, low, high, close=None):
        start = 360000 + index*3600
        return H1Bar(start, start+3600, start+3600, (low+high)/2,
                     high, low, close if close is not None else (low+high)/2, 100)

    def test_multi_local_hypotheses_never_confirm_on_the_extreme_bar(self):
        tracker = MultiLocalResearch("ZEC")
        profile = Profile()
        rows = []
        emit = lambda stream, ts, **data: rows.append({"stream": stream, "ts": ts, **data})
        for i in range(10):
            tracker.on_closed_bar(self.bar(i, 100-i*.1, 110-i*.1),
                                  360000+(i+1)*3600, None, emit, profile, "evaluation", seeded=False)
        extreme = self.bar(10, 90, 105, 92)
        tracker.on_closed_bar(extreme, extreme.available_ts, None, emit, profile, "evaluation", seeded=False)
        confirmed_at_extreme = [x for x in rows if x.get("stage") == "CONFIRMED" and x["ts"] == extreme.available_ts]
        self.assertEqual(confirmed_at_extreme, [])
        retreat = self.bar(11, 91, 104, 93)
        tracker.on_closed_bar(retreat, retreat.available_ts, None, emit, profile, "evaluation", seeded=False)
        confirmed = [x for x in rows if x.get("stage") == "CONFIRMED" and x["local"]["kind"] == "LOW"]
        self.assertTrue(confirmed)
        self.assertTrue(all(x["local"]["confirmed_ts"] > extreme.available_ts for x in confirmed))

    def test_local_flow_evidence_is_tagged_without_becoming_a_gate(self):
        low = local_flow_evidence("LOW", {
            "imbalance": -0.4, "move_bps": 8.0, "price_scale_bps": 5.0,
            "sell_absorption": True, "buy_absorption": False,
            "sell_deceleration": 0.3, "buy_deceleration": 0.0,
            "large_trade_count": 2, "notional_z": 3.0,
        })
        self.assertIn("SELL_ABSORPTION_AT_LOW", low)
        self.assertIn("DOMINANT_FLOW_DECELERATION", low)
        self.assertIn("DOMINANT_FLOW_FAILED_TO_MOVE_PRICE", low)
        self.assertIn("STRONG_REVERSAL_PRICE_RESPONSE", low)
        self.assertIn("LARGE_TRADE_CONTEXT", low)

    def test_dual_side_research_records_long_and_short_same_block(self):
        cfg = Config(block_trades=2, baseline_blocks=8, warmup_blocks=2)
        out = Output(self.root/"dual", cfg, ("ZEC",), "test")
        engine = ResearchEngine(out, cfg, ("ZEC",))
        state = engine.states["ZEC"]
        state.locals["LOW"].append(Local(1, "LOW", 90, None, 1, "CONFIRMED", 2))
        state.locals["HIGH"].append(Local(2, "HIGH", 110, None, 1, "CONFIRMED", 2))
        state.trend = "DOWNTREND"
        state.history.extend([{"price": 100}, {"price": 100}])
        flow = {
            "ts": 100.0, "price": 100.0, "move_bps": -20.0, "price_scale_bps": 5.0,
            "imbalance": -0.4, "buy_acceleration": -0.1, "sell_acceleration": 0.5,
            "buy_absorption": False, "sell_absorption": False,
        }
        forward = {-1: {"tags": []}, 1: {"tags": []}}
        dual_side_entry_research(engine, state, flow, {"flow": flow}, forward)
        out.flush()
        rows = [json.loads(x) for x in (out.root/"entry_hypotheses.jsonl").read_text().splitlines()]
        self.assertEqual({x["direction"] for x in rows}, {"LONG", "SHORT"})
        self.assertTrue(any(x["direction"] == "SHORT" and x["hypothesis"] == "CONTINUATION" and x["accepted"] for x in rows))
        self.assertTrue(any(x["direction"] == "LONG" for x in rows))
        engine.finish("test")

    def test_checkpoint_resume_truncates_uncheckpointed_tail_and_restores_state(self):
        cfg = Config(block_trades=2, baseline_blocks=8, warmup_blocks=2)
        run = self.root/"resume"
        out = Output(run, cfg, ("ZEC",), "historical_research")
        engine = ResearchEngine(out, cfg, ("ZEC",))
        engine.on_trade(Trade("ZEC", 100, 100, 1, 1, "a"))
        engine.checkpoint("test")
        seq = engine.states["ZEC"].seq
        offsets = json.loads((run/"checkpoint.json").read_text())["output_offsets"]
        for handle in out.handles.values():
            handle.close()
        out.lock_handle.close()
        with (run/"signals.jsonl").open("a") as handle:
            handle.write('{"garbage":true}\n')
        self.assertGreater((run/"signals.jsonl").stat().st_size, offsets["signals"])

        out2 = Output(run, cfg, ("ZEC",), "historical_research", resume=True)
        engine2 = ResearchEngine(out2, cfg, ("ZEC",))
        engine2.restore_checkpoint()
        self.assertEqual(engine2.states["ZEC"].seq, seq)
        self.assertEqual((run/"signals.jsonl").stat().st_size, offsets["signals"])
        engine2.finish("test")

    def test_hourly_status_contains_all_requested_fields_and_renders(self):
        cfg = Config(block_trades=2, baseline_blocks=8, warmup_blocks=2)
        out = Output(self.root/"hourly", cfg, ("ZEC",), "realtime_audit")
        engine = ResearchEngine(out, cfg, ("ZEC",))
        engine.on_trade(Trade("ZEC", 100, 100, 1, 1, "a"))
        row = persist_status(engine, 101, reason="hourly", hourly=True)
        token = row["tokens"]["ZEC"]
        self.assertIn("h1", token)
        self.assertIn("structure", token)
        self.assertIn("recent_flow", token)
        self.assertIn("paper", token)
        self.assertTrue((out.root/"research_status.json").is_file())
        text = render_hourly_report(out.root)
        self.assertIn("ZEC", text)
        self.assertIn("WHAT IS NOT PROVEN YET", text)
        engine.finish("test")

    def test_optional_market_context_parses_l1_and_liquidation(self):
        ob = {
            "topic": "orderbook.1.ZECUSDT", "ts": 100000, "cts": 99999,
            "data": {"s": "ZECUSDT", "b": [["99", "2"]], "a": [["101", "3"]], "u": 5, "seq": 7},
        }
        rows = parse_context(ob, ("ZEC",), 100.1)
        self.assertEqual(rows[0]["kind"], "orderbook_l1")
        self.assertGreater(rows[0]["spread_bps"], 0)
        liq = {
            "topic": "allLiquidation.ZECUSDT", "ts": 100000,
            "data": [{"T": 99999, "s": "ZECUSDT", "S": "Sell", "v": "4", "p": "100"}],
        }
        rows = parse_context(liq, ("ZEC",), 100.1)
        self.assertEqual(rows[0]["kind"], "liquidation")
        self.assertEqual(rows[0]["notional"], 400)


if __name__ == "__main__":
    unittest.main()
