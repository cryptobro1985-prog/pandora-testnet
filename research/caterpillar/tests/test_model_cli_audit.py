"""Regression tests for numeric configuration, flow accounting and executable CLI behavior."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from caterpillar.__main__ import main
from caterpillar.model import Config, Position, Trade, features


class ModelAuditTests(unittest.TestCase):
    def test_bad_costs_and_numeric_types_fail_before_fills(self):
        for kwargs in ({'slippage_bps': 10000}, {'slippage_bps': 20000}, {'fee_bps': 10000},
                       {'fee_bps': True}, {'control_imbalance': True}, {'control_imbalance': math.nan},
                       {'notional': 10**400},
                       {'local_floor_bps': '5'}, {'gap_seconds': math.inf}, {'min_evidence_days': 1},
                       {'exit_models': {'combined'}}, {'exit_models': [True]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Config(**kwargs)

    def test_frozen_config_cannot_change_through_exit_model_list(self):
        caller = ['combined']
        config = Config(exit_models=caller)
        digest = config.digest
        caller.append('flow_weakening')
        self.assertEqual(config.exit_models, ('combined',))
        self.assertEqual(config.digest, digest)

    def test_trade_notional_underflow_and_oversized_json_numbers_are_invalid(self):
        self.assertFalse(Trade('ZEC', 100, 1e-300, 1e-300, 1, 'x').valid())
        self.assertFalse(Trade('ZEC', 100, 10**400, 1, 1, 'x').valid())

    def test_unrepresentable_mark_fails_without_poisoning_position(self):
        position = Position('p', 1, 100, 1, 1e308, 1, 90, {})
        with self.assertRaises(ValueError):
            position.mark(1e308, 2, 4.5, 2)
        self.assertEqual(position.current, 0)
        self.assertEqual(position.mfe, 0)

    def test_boundary_move_and_first_trade_response_are_not_lost(self):
        cfg = Config()
        initial = features([Trade('ZEC', 100+i, 100, 1, 1, str(i)) for i in range(8)], [], cfg)
        block = [Trade('ZEC', 108, 110, 1, 1, '8'), Trade('ZEC', 109, 109, 1, -1, '9')]
        result = features(block, [initial], cfg)
        self.assertLess(result['internal_move_bps'], 0)
        self.assertGreater(result['move_bps'], 0)
        self.assertAlmostEqual(result['move_bps'], 900)
        self.assertAlmostEqual(result['buy_response_bps'], 1000)
        self.assertEqual(result['reference_price'], 100)
        self.assertEqual(result['duration'], 2)
        self.assertLess(result['sell_response_bps'], 0)

    def test_large_trade_reference_preserves_individual_size_variance(self):
        cfg = Config()
        previous = features([Trade('ZEC', 100+i, 100, (i+1)/10, 1, str(i)) for i in range(10)], [], cfg)
        # Past individual USD sizes are 10..100; block mean is 55 with zero variation across blocks.
        result = features([Trade('ZEC', 110+i, 100, 1.1, 1, 'new'+str(i)) for i in range(10)], [previous]*8, cfg)
        self.assertEqual(result['large_trade_count'], 0)
        self.assertEqual(len(result['trade_sizes_usd']), 10)


class CLIAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.input = self.root/'input.jsonl'
        self.input.write_text(json.dumps(asdict(Trade('ZEC', 100, 100, 1, 1, 'a')))+'\n')

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, args):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main(args)

    def test_default_universe_replay_reports_missing_symbols(self):
        dest = self.root/'run'
        self.assertEqual(self.call(['replay', '--input', str(self.input), '--output', str(dest)]), 2)
        summary = json.loads((dest/'research_summary.json').read_text())
        self.assertEqual(len(summary['coverage']), 10)
        self.assertEqual(sum(x['status'] == 'unavailable_or_partial' for x in summary['coverage']), 9)

    def test_explicit_single_symbol_replay_can_complete(self):
        self.assertEqual(self.call(['replay', '--symbols', 'ZEC', '--input', str(self.input), '--output', str(self.root/'run')]), 0)

    def test_replay_preserves_incomplete_status_for_recorded_disconnect(self):
        with self.input.open('a') as handle:
            handle.write(json.dumps({'symbol': 'ZEC', 'event': 'GAP', 'ts': 101, 'reason': 'disconnect'})+'\n')
            handle.write(json.dumps(asdict(Trade('ZEC', 102, 100, 1, 1, 'b')))+'\n')
        self.assertEqual(self.call(['replay', '--symbols', 'ZEC', '--input', str(self.input), '--output', str(self.root/'run')]), 2)

    def test_invalid_realtime_limits_fail_without_creating_run(self):
        for option, value in (('--duration-seconds', 'nan'), ('--reorder-seconds', 'nan'), ('--max-lag-seconds', 'inf')):
            dest = self.root/option
            with self.subTest(option=option), self.assertRaises(SystemExit) as exc:
                self.call(['realtime_audit', '--output', str(dest), option, value])
            self.assertEqual(exc.exception.code, 2)
            self.assertFalse(dest.exists())

    def test_realtime_cli_marks_frozen_run_as_evaluation(self):
        phases = []
        def fake_feed(engine, *args):
            phases.append(engine.phase(100))
            return 'incomplete_coverage'
        with patch('caterpillar.realtime.realtime', side_effect=fake_feed):
            self.assertEqual(self.call(['realtime_audit', '--output', str(self.root/'run')]), 2)
        self.assertEqual(phases, ['evaluation'])

    def test_raw_replay_restores_source_config_and_evaluation_phase(self):
        raw = self.root/'raw_trades.jsonl'
        raw.write_bytes(self.input.read_bytes())
        source_config = asdict(Config(fee_bps=1.5))
        (self.root/'run_manifest.json').write_text(json.dumps({'config': source_config, 'mode': 'realtime_audit',
                                                             'metadata': {'split_ts': 0}, 'schema_version': 2}))
        dest = self.root/'run'
        self.assertEqual(self.call(['replay', '--symbols', 'ZEC', '--input', str(raw), '--output', str(dest)]), 0)
        manifest = json.loads((dest/'run_manifest.json').read_text())
        summary = json.loads((dest/'research_summary.json').read_text())
        self.assertEqual(manifest['config']['fee_bps'], 1.5)
        self.assertEqual(summary['split_ts'], 0)
        self.assertFalse(manifest['metadata']['source_manifest']['config_overridden'])

    def test_irrelevant_mode_flags_are_not_silently_ignored(self):
        with self.assertRaises(SystemExit):
            self.call(['replay', '--input', str(self.input), '--output', str(self.root/'run'), '--start-date', '2026-01-01'])
        self.assertFalse((self.root/'run').exists())

    def test_future_historical_end_rejected_before_network_or_output(self):
        with self.assertRaises(SystemExit):
            self.call(['historical_research', '--end-date', '2999-01-01', '--output', str(self.root/'run')])
        self.assertFalse((self.root/'run').exists())
