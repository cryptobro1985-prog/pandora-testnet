"""Regressions for the causal structure/position audit (no market performance claims)."""
from collections import deque
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from caterpillar.engine import ResearchEngine
from caterpillar.model import Config, Local, Position, Trade, features
from caterpillar.output import Metric, Output


class EngineAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = Config(block_trades=2, baseline_blocks=8, warmup_blocks=2,
                          confirmation_blocks=2, transfer_blocks=2, outcome_trades=4)
        self.output = Output(Path(self.tmp.name)/'run', self.cfg, ('ZEC',), 'audit_test')
        self.engine = ResearchEngine(self.output, self.cfg, ('ZEC',))
        self.addCleanup(self.engine.finish)
        self.s = self.engine.states['ZEC']

    def c(self, ts, price=100, side=1):
        previous = Trade('ZEC', ts-.1, price*(1-side*.001), 1, side, str(ts)+'a')
        current = Trade('ZEC', ts, price, 2, side, str(ts)+'b')
        self.s.block = [previous, current]
        row = features(self.s.block, (), self.cfg)
        row.update(buy_acceleration=1 if side == 1 else -.5,
                   sell_acceleration=1 if side == -1 else -.5,
                   buy_absorption=False, sell_absorption=False)
        return row

    def seed(self):
        self.s.locals['LOW'].append(Local(1, 'LOW', 90, 1, 2, 'CONFIRMED', 3))
        self.s.candidate = Local(2, 'HIGH', 120, 4, 4)
        self.s.history.extend([self.c(5), self.c(6)])

    def rows(self, stream):
        import json
        self.output.flush()
        return [json.loads(line) for line in (self.output.root/(stream+'.jsonl')).read_text().splitlines()]

    def test_structure_break_exit_uses_position_anchor_not_latest_symbol_anchor(self):
        self.seed()
        # A later symbol local is below the position anchor, so it has not broken
        # even though the position's own 90 anchor is persistently breached.
        self.s.locals['LOW'].append(Local(3, 'LOW', 80, 7, 8, 'CONFIRMED', 9))
        book = self.s.books['structure_break']
        book.position = Position('older-anchor', 1, 100, 3, 10, 1, 90, {})
        for ts in (20, 21):
            self.s.seq += 2
            self.engine._evaluate(self.s, self.c(ts, 89, -1))
        self.assertFalse(self.s.locals['LOW'][-1].invalidated)
        self.assertTrue(book.anchor_invalidated)
        self.assertEqual(book.pending['action'], 'CLOSE')
        self.assertIn('structure_break', book.pending['reasons'])

    def test_invalidated_own_anchor_does_not_become_valid_again_after_rebound(self):
        self.seed()
        book = self.s.books['local_invalidation']
        book.position = Position('p', 1, 100, 3, 10, 1, 90, {})
        book.anchor_invalidated = True
        self.engine._evaluate(self.s, self.c(20, 100, 1))
        self.assertEqual(book.pending['action'], 'CLOSE')
        self.assertIn('local_invalidation', book.pending['reasons'])

    def test_evaluation_reset_has_consistent_invalidation_status_and_boolean(self):
        self.seed()
        self.engine.gap('ZEC', 10, 'evaluation_boundary')
        rows = self.rows('locals')
        self.assertTrue(rows)
        for row in rows:
            if row['stage'] == 'INVALIDATED':
                self.assertTrue(row['local']['invalidated'])
                self.assertEqual(row['local']['status'], 'INVALIDATED')

    def test_expired_same_timestamp_entry_cannot_fill_after_many_new_events(self):
        self.seed()
        self.engine._evaluate(self.s, self.c(20, 100, 1))
        forecast = next(row for row in self.s.forecasts if row['side'] == 1)
        self.s.seq = 10
        self.s.last_ts = 100
        self.s.last_price = 100
        book = self.s.books['combined']
        book.pending = {'action': 'OPEN', 'ts': 100, 'event_seq': 1,
                        'side': 1, 'local_id': 1, 'local_price': 90, 'snapshot': {}, 'parent_exit': None}
        self.engine.on_trade(Trade('ZEC', 100.1, 100, 1, 1, 'later'))
        self.assertIsNone(book.position)
        self.assertIsNone(book.pending)
        self.assertTrue(any('SIGNAL_EXPIRED_BEFORE_FILL' in row.get('reasons', []) for row in self.rows('rejected_signals')))
        self.assertFalse(any(tag.startswith('filled_') for tag in forecast['tags']))

    def test_reentry_is_forbidden_after_newer_opposite_confirmed_local(self):
        self.seed()
        self.s.locals['HIGH'].append(Local(3, 'HIGH', 110, 7, 8, 'CONFIRMED', 9))
        book = self.s.books['combined']
        book.watch = {'side': 1, 'local_id': 1, 'exit_id': 'exit', 'exit_price': 102,
                      'correction_seen': True, 'expires_seq': 10000}
        self.engine._evaluate(self.s, self.c(20, 100, 1))
        self.assertIsNone(book.pending)
        self.assertIsNone(book.watch)
        rows = self.rows('rejected_signals')
        self.assertTrue(any(row['model'] == 'combined' and 'OPPOSITE_LOCAL_CONFIRMED' in row.get('reasons', []) for row in rows))

    def test_newer_opposite_local_cancels_pending_entry_before_fill(self):
        self.seed()
        self.s.locals['HIGH'].append(Local(3, 'HIGH', 110, 7, 8, 'CONFIRMED', 9))
        book = self.s.books['combined']
        book.pending = {'action': 'OPEN', 'ts': 10, 'side': 1, 'local_id': 1,
                        'local_price': 90, 'snapshot': {}, 'parent_exit': None}
        self.engine._fill(self.s, 'combined', book, Trade('ZEC', 11, 100, 1, 1, 'fill'))
        self.assertIsNone(book.position)
        self.assertIn('OPPOSITE_LOCAL_BEFORE_FILL', self.rows('rejected_signals')[-1]['reasons'])

    def test_sweep_from_old_anchor_is_not_a_false_break_of_new_anchor(self):
        self.seed()
        self.s.sweeps['LOW'] = {'local_id': 1, 'ts': 8, 'price': 89}
        self.s.locals['LOW'].append(Local(3, 'LOW', 95, 9, 10, 'CONFIRMED', 11))
        self.engine.on_trade(Trade('ZEC', 12, 100, 1, 1, 'next'))
        self.assertFalse(any(row.get('event') == 'FALSE_BREAK' for row in self.rows('structure')))
        self.assertNotIn('LOW', self.s.sweeps)

    def test_broken_latest_low_cannot_keep_uptrend_veto_active(self):
        self.seed()
        self.s.locals['LOW'].append(Local(3, 'LOW', 95, 7, 8, 'INVALIDATED', 9, invalidated=True))
        self.s.locals['HIGH'].extend([Local(4, 'HIGH', 110, 10, 11, 'CONFIRMED', 12),
                                     Local(5, 'HIGH', 115, 13, 14, 'CONFIRMED', 15)])
        self.s.trend = 'UPTREND'
        self.engine._local_structure(self.s, self.c(20, 100, -1))
        self.assertEqual(self.s.trend, 'RANGE')

    def test_late_omitted_tick_censors_existing_position(self):
        self.engine.on_trade(Trade('ZEC', 100, 100, 1, 1, 'first'))
        self.s.books['combined'].position = Position('p', 1, 100, 100, 10, 1, 90, {})
        self.engine.on_trade(Trade('ZEC', 99, 98, 1, -1, 'late'))
        self.assertIsNone(self.s.books['combined'].position)
        self.assertTrue(any(row.get('action') == 'CENSORED' and row.get('reason') == 'late_trade_gap' for row in self.rows('trades')))

    def test_gap_clears_ohlcv_context(self):
        self.engine.on_candle('ZEC', {'available_ts': 100, 'low': 90, 'high': 110, 'close': 100})
        self.engine.gap('ZEC', 1000, 'missing_day')
        self.engine.on_candle('ZEC', {'available_ts': 2000, 'low': 80, 'high': 120, 'close': 100})
        self.assertEqual(self.rows('candles')[-1]['structure_observations'], [])

    def test_actual_entry_conjunctions_are_quarantined_in_forward_labels(self):
        self.seed()
        c = self.c(20, 100, 1)
        self.engine._evaluate(self.s, c)
        rows = list(self.s.forecasts)
        positive = next(row for row in rows if row['side'] == 1)
        self.assertIn('open_combined', positive['tags'])
        self.assertEqual(len(positive['tags']), len(set(positive['tags'])))
        self.assertEqual(positive['snapshot']['flow'], c)
        self.assertIsNone(positive['entry'])

    def test_successful_open_adds_filled_tag_to_matching_forward_observation(self):
        self.seed()
        self.engine._evaluate(self.s, self.c(20, 100, 1))
        observation = next(row for row in self.s.forecasts if row['side'] == 1)
        self.assertIn('open_combined', observation['tags'])
        self.assertNotIn('filled_open_combined', observation['tags'])
        self.engine._fill(self.s, 'combined', self.s.books['combined'], Trade('ZEC', 21, 100, 1, 1, 'filled'))
        self.assertIn('filled_open_combined', observation['tags'])
        self.assertIn('open_combined', observation['tags'])

    def test_successful_reentry_adds_filled_reentry_tag(self):
        self.seed()
        book = self.s.books['combined']
        book.watch = {'side': 1, 'local_id': 1, 'exit_id': 'exit', 'exit_price': 102,
                      'correction_seen': True, 'expires_seq': 10000}
        self.engine._evaluate(self.s, self.c(20, 100, 1))
        observation = next(row for row in self.s.forecasts if row['side'] == 1)
        self.assertIn('reentry_combined', observation['tags'])
        self.engine._fill(self.s, 'combined', book, Trade('ZEC', 21, 100, 1, 1, 'reentry-filled'))
        self.assertIn('filled_reentry_combined', observation['tags'])

    def test_rejected_fill_cannot_gain_an_executable_entry_tag(self):
        self.seed()
        self.engine._evaluate(self.s, self.c(20, 100, 1))
        observation = next(row for row in self.s.forecasts if row['side'] == 1)
        self.s.locals['LOW'][-1].invalidated = True
        self.engine._fill(self.s, 'combined', self.s.books['combined'], Trade('ZEC', 21, 100, 1, 1, 'rejected'))
        self.assertIsNone(self.s.books['combined'].position)
        self.assertNotIn('filled_open_combined', observation['tags'])

    def test_forbidden_reentry_fill_does_not_become_a_missed_profitable_entry(self):
        self.seed()
        book = self.s.books['combined']
        book.watch = {'side': 1, 'local_id': 1, 'exit_id': 'exit', 'exit_price': 102,
                      'correction_seen': True, 'expires_seq': 10000}
        observation = {'exit_id': 'exit', 'model': 'combined', 'side': 1, 'price': 100,
                       'exit_seq': 0, 'exit_ts': 1, 'max_continuation_bps': 0,
                       'max_adverse_bps': 0, 'reentered': False, 'eligible_reentry_seen': False,
                       'eligible_signal_ts': None, 'eligible_fill_price': None, 'eligible_max_net_bps': None}
        self.s.post_exits.append(observation)
        self.engine._evaluate(self.s, self.c(20, 100, 1))
        self.assertTrue(observation['eligible_reentry_seen'])
        self.s.locals['LOW'][-1].invalidated = True
        self.engine._fill(self.s, 'combined', book, Trade('ZEC', 21, 100, 1, 1, 'forbidden'))
        self.assertFalse(observation['eligible_reentry_seen'])
        self.s.seq = self.cfg.post_exit_trades
        self.engine._future_labels(self.s, Trade('ZEC', 22, 120, 1, 1, 'later-rally'))
        row = self.rows('post_exit')[-1]
        self.assertFalse(row['missed_reentry_candidate'])
        self.assertEqual(row['eligible_forbidden_reason'], 'LOCAL_INVALID_BEFORE_FILL')

    def test_positive_notional_that_underflows_quantity_is_not_an_open(self):
        cfg = Config(notional=5e-324, block_trades=2, baseline_blocks=8, warmup_blocks=2)
        self.engine.config = cfg
        self.seed()
        book = self.s.books['combined']
        book.pending = {'action': 'OPEN', 'ts': 10, 'side': 1, 'local_id': 1,
                        'local_price': 90, 'snapshot': {}, 'parent_exit': None}
        self.engine._fill(self.s, 'combined', book, Trade('ZEC', 11, 1000, 1, 1, 'fill'))
        self.assertIsNone(book.position)
        self.assertIn('UNREPRESENTABLE_FILL', self.rows('rejected_signals')[-1]['reasons'])

    def test_nonrepresentable_mark_is_censored_without_infinite_json(self):
        self.engine.on_trade(Trade('ZEC', 100, 1, 1, 1, 'first'))
        self.s.books['combined'].position = Position('p', 1, 1, 100, 1e308, 1, .5, {})
        self.engine.on_trade(Trade('ZEC', 101, 10, 1, 1, 'mark'))
        self.assertIsNone(self.s.books['combined'].position)
        self.assertTrue(any(row.get('reason') == 'numerical_position_error' for row in self.rows('trades')))

    def test_pre_eligibility_peak_is_not_a_missed_reentry(self):
        self.s.post_exits.append({'exit_id': 'exit', 'model': 'combined', 'side': 1, 'price': 100,
                                 'exit_seq': 0, 'exit_ts': 1, 'max_continuation_bps': 1000,
                                 'max_adverse_bps': 0, 'reentered': False, 'eligible_reentry_seen': True,
                                 'eligible_signal_ts': 100, 'eligible_fill_price': None, 'eligible_max_net_bps': None})
        self.s.seq = self.cfg.post_exit_trades
        self.engine._future_labels(self.s, Trade('ZEC', 101, 100, 1, 1, 'later'))
        row = self.rows('post_exit')[-1]
        self.assertFalse(row['missed_reentry_candidate'])
        self.assertLess(row['eligible_max_net_bps'], 0)

    def test_aggregate_overflow_is_explicit_unknown_not_invalid_json(self):
        import json
        metric = Metric()
        metric.n, metric.mean = 2, 1e308
        self.engine.profiles['ZEC'].metrics['combined/net_usd'] = metric
        self.engine.finish()
        row = json.loads((self.output.root/'research_summary.json').read_text())['aggregate_exit_books']['combined']
        self.assertEqual(row['financial_total_status'], 'unrepresentable')
        self.assertIsNone(row['net_usd_before_funding'])


if __name__ == '__main__': unittest.main()
