"""Regressions for source integrity and realtime lifecycle found in the second audit."""
from datetime import datetime, timezone, timedelta
import gzip
import json
import math
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from caterpillar.engine import ResearchEngine
from caterpillar.model import Config, Position, Trade
from caterpillar.output import Output
from caterpillar.realtime import Ingress, parse_frame, realtime
from caterpillar.sources import Archives, SourceError, bootstrap_h1, candles, closed_h1, file_sha, historical, replay


class DataAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        cfg = Config()
        self.engine = ResearchEngine(Output(self.root/'out', cfg, ('ZEC',), 'audit_test'), cfg, ('ZEC',))
        self.bootstrap_patch = patch('caterpillar.realtime.bootstrap_h1', return_value=True)
        self.bootstrap_patch.start()

    def tearDown(self):
        self.engine.finish('test_completed')
        self.bootstrap_patch.stop()
        self.temp.cleanup()

    def cached_archive(self, rows):
        source = Archives(self.root/'cache')
        day = datetime(2024, 1, 1, tzinfo=timezone.utc)
        name = 'ZECUSDT2024-01-01.csv.gz'
        path = source.cache/name
        with gzip.open(path, 'wt') as f:
            f.write('timestamp,symbol,side,size,price,trdMatchID\n')
            for row in rows:
                f.write(','.join(str(x) for x in row)+'\n')
        (source.cache/(name+'.json')).write_text(json.dumps({
            'url': 'https://public.bybit.com/trading/ZECUSDT/'+name,
            'sha256': file_sha(path)}))
        return source, day

    def test_whole_archive_is_preflighted_before_first_trade(self):
        stamp = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
        source, day = self.cached_archive([
            (stamp+2, 'ZECUSDT', 'Buy', 1, 100, 'a'),
            (stamp+1, 'ZECUSDT', 'Sell', 1, 99, 'b')])
        with self.assertRaisesRegex(SourceError, 'Unordered archive'):
            source.trades('ZEC', day)
        self.assertEqual(self.engine.states['ZEC'].seq, 0)

    def test_schema_failure_late_in_archive_does_not_supply_a_partial_day(self):
        stamp = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
        source, day = self.cached_archive([
            (stamp+1, 'ZECUSDT', 'Buy', 1, 100, 'a'),
            (stamp+2, 'ZECUSDT', 'Unknown', 1, 99, 'b')])
        with self.assertRaises(SourceError): source.trades('ZEC', day)
        self.assertEqual(self.engine.states['ZEC'].seq, 0)

    def test_invalid_cache_manifest_has_a_source_error(self):
        source, day = self.cached_archive([(1704067200, 'ZECUSDT', 'Buy', 1, 100, 'a')])
        next(source.cache.glob('*.json')).write_text('{broken')
        with self.assertRaisesRegex(SourceError, 'Invalid cached archive/manifest'):
            source.obtain('ZEC', day)

    def test_replay_rejects_invalid_or_non_object_rows(self):
        path = self.root/'replay.jsonl'
        for row in ([], {'symbol': 'ZEC', 'ts': 100, 'price': -1, 'quantity': 1, 'side': 1, 'trade_id': 'x'},
                    {'event': 'GAP', 'symbol': 'ZEC', 'ts': float('nan'), 'reason': 'bad'},
                    {'event': 'GAP', 'symbol': 'BTC', 'ts': 100, 'reason': 'bad'},
                    {'event': 'UNKNOWN'}):
            path.write_text(json.dumps(row)+'\n')
            with self.assertRaisesRegex(SourceError, 'Malformed replay line 1'):
                replay(self.engine, path)

    def test_ohlcv_missing_interval_is_not_contiguous_coverage(self):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        t = int(start.timestamp()*1000)
        response = {'retCode': 0, 'result': {'list': [[str(t+60000), '100', '101', '99', '100', '1', '100']]}}
        with patch('caterpillar.sources.read_url', return_value=response):
            with self.assertRaisesRegex(SourceError, 'OHLCV coverage gap'):
                list(candles('ZEC', start, start+timedelta(minutes=2)))

    def test_ohlcv_reversed_rows_recover_closed_bar_order(self):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        t = int(start.timestamp()*1000)
        response = {'retCode': 0, 'result': {'list': [
            [str(t+60000), '100', '101', '99', '100', '1', '100'],
            [str(t), '100', '101', '99', '100', '1', '100']]}}
        with patch('caterpillar.sources.read_url', return_value=response), patch('caterpillar.sources.time.sleep'):
            result = list(candles('ZEC', start, start+timedelta(minutes=2)))
        self.assertEqual([r['available_ts'] for r in result], [t/1000+60, t/1000+120])

    def test_malformed_ohlcv_row_fails_as_source_error(self):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        response = {'retCode': 0, 'result': {'list': [['1704067200000', '100']]}}
        with patch('caterpillar.sources.read_url', return_value=response):
            with self.assertRaises(SourceError): list(candles('ZEC', start, start+timedelta(minutes=1)))

    def test_finite_ingress_configuration_is_required(self):
        for kwargs in ({'reorder_seconds': math.nan}, {'max_lag_seconds': math.inf}, {'max_buffer': 1.5}):
            with self.assertRaises(ValueError): Ingress(self.engine, **kwargs)

    def test_silent_symbol_censors_position_without_needing_a_new_trade(self):
        ingress = Ingress(self.engine, reorder_seconds=0)
        ingress.push(Trade('ZEC', 100, 100, 1, 1, 'a'), 100)
        self.engine.states['ZEC'].books['combined'].position = Position('p', 1, 100, 100, 10, 1, 90, {})
        ingress.check_silence(131)
        self.assertIsNone(self.engine.states['ZEC'].books['combined'].position)
        self.assertEqual(ingress.silence_events, 1)
        ingress.check_silence(132)
        self.assertEqual(ingress.silence_events, 1)
        ingress.push(Trade('ZEC', 133, 100, 1, 1, 'b'), 133)
        self.assertNotIn('ZEC', ingress.silent)

    def test_invalid_topic_is_a_source_error(self):
        with self.assertRaises(SourceError): parse_frame('{"topic":42}', ('ZEC',), 100)

    def test_old_duplicate_is_benign_not_missing_late_tape(self):
        ingress = Ingress(self.engine, reorder_seconds=0)
        a = Trade('ZEC', 100, 100, 1, 1, 'a')
        ingress.push(a, 100)
        ingress.push(Trade('ZEC', 101, 101, 1, 1, 'b'), 101)
        ingress.push(a, 102)
        self.assertEqual(ingress.late_events, 0)
        self.assertEqual(self.engine.states['ZEC'].seq, 2)

    def test_receive_timestamp_is_measured_after_blocking_recv(self):
        import websocket
        clock = {'wall': 100.0, 'mono': 0.0}
        class Socket:
            def __init__(self): self.n = 0
            def send(self, _): pass
            def settimeout(self, _): pass
            def close(self): pass
            def recv(self):
                self.n += 1
                if self.n == 1:
                    clock['mono'] = .01
                    return '{"op":"subscribe","success":true}'
                if self.n == 2:
                    clock.update(wall=102.0, mono=.02)
                    return json.dumps({'topic': 'publicTrade.ZECUSDT', 'data': [
                        {'s': 'ZECUSDT', 'T': 102000, 'p': '100', 'v': '1', 'S': 'Buy', 'i': 'a'}]})
                clock['mono'] = .04
                raise websocket.WebSocketTimeoutException()
        with patch('websocket.create_connection', return_value=Socket()), \
             patch('caterpillar.realtime.proxy_options', return_value={}), \
             patch('caterpillar.realtime.time.time', side_effect=lambda: clock['wall']), \
             patch('caterpillar.realtime.time.monotonic', side_effect=lambda: clock['mono']):
            result = realtime(self.engine, duration=.03, reorder_seconds=0)
        self.assertEqual(result, 'completed')
        self.assertEqual(self.engine.states['ZEC'].seq, 1)

    def test_data_before_ack_is_not_used(self):
        import websocket
        class Socket:
            def send(self, _): pass
            def settimeout(self, _): pass
            def close(self): pass
            def recv(self):
                return json.dumps({'topic': 'publicTrade.ZECUSDT', 'data': [
                    {'s': 'ZECUSDT', 'T': 100000, 'p': '100', 'v': '1', 'S': 'Buy', 'i': 'a'}]})
        with patch('websocket.create_connection', return_value=Socket()), patch('caterpillar.realtime.proxy_options', return_value={}):
            result = realtime(self.engine, duration=.01)
        self.assertEqual(result, 'incomplete_coverage')
        self.assertEqual(self.engine.states['ZEC'].seq, 0)

    def test_h1_bootstrap_excludes_current_hour_and_requires_contiguous_closed_bars(self):
        as_of = datetime(2024, 1, 2, 12, 37, tzinfo=timezone.utc).timestamp()
        end = datetime(2024, 1, 2, 12, tzinfo=timezone.utc).timestamp()
        rows = [{'open_ts': end-(24-i)*3600, 'available_ts': end-(23-i)*3600,
                 'open': 100, 'high': 101, 'low': 99, 'close': 100, 'volume': 1,
                 'interval_minutes': 60} for i in range(24)]
        with patch('caterpillar.sources.candles', return_value=iter(rows)) as fetch:
            actual = closed_h1('ZEC', as_of)
        self.assertEqual(len(actual), 24)
        self.assertEqual(fetch.call_args.args[1].timestamp(), end-24*3600)
        self.assertEqual(fetch.call_args.args[2].timestamp(), end)
        self.assertEqual(fetch.call_args.kwargs['interval'], 60)
        self.assertLessEqual(actual[-1]['available_ts'], as_of)
        with patch('caterpillar.sources.candles', return_value=iter(rows[:-1])):
            with self.assertRaises(SourceError): closed_h1('ZEC', as_of)
        future = [dict(row) for row in rows]
        future[-1]['available_ts'] = as_of+1
        with patch('caterpillar.sources.candles', return_value=iter(future)):
            with self.assertRaises(SourceError): closed_h1('ZEC', as_of)

    def test_h1_bootstrap_seeds_structure_without_supplying_flow(self):
        as_of = 1704153600.0
        rows = [{'open_ts': as_of-3600, 'available_ts': as_of,
                 'open': 100, 'high': 101, 'low': 99, 'close': 100}]
        calls = []
        fake = SimpleNamespace(states={'ZEC': None, 'HYPE': None}, coverage=[],
                               seed_h1=lambda symbol, candle, as_of: calls.append((symbol, candle, as_of)),
                               quality=lambda *args, **kwargs: None)
        with patch('caterpillar.sources.closed_h1', return_value=rows):
            self.assertTrue(bootstrap_h1(fake, as_of, hours=1))
        self.assertEqual([c[0] for c in calls], ['ZEC', 'HYPE'])
        self.assertTrue(all(not c['flow_available'] for c in fake.coverage))
        self.assertTrue(all(c[2] == as_of for c in calls))

    def test_h1_bootstrap_failure_is_explicit_and_does_not_seed_failed_symbol(self):
        calls = []
        fake = SimpleNamespace(states={'ZEC': None}, coverage=[],
                               seed_h1=lambda *args, **kwargs: calls.append(args),
                               quality=lambda *args, **kwargs: None)
        with patch('caterpillar.sources.closed_h1', side_effect=SourceError('unavailable')):
            self.assertFalse(bootstrap_h1(fake, 1704153600.0))
        self.assertEqual(calls, [])
        self.assertEqual(fake.coverage[0]['status'], 'unavailable')

    def test_replay_dispatches_h1_seed_as_of_without_treating_candle_as_trade(self):
        calls = []
        fake = SimpleNamespace(states={'ZEC': None},
                               seed_h1=lambda symbol, candle, as_of: calls.append((symbol, candle, as_of)))
        path = self.root/'seed.jsonl'
        candle = {'open_ts': 1704150000.0, 'available_ts': 1704153600.0,
                  'open': 100, 'high': 101, 'low': 99, 'close': 100, 'interval_minutes': 60}
        path.write_text(json.dumps({'event': 'H1_SEED', 'symbol': 'ZEC', 'candle': candle, 'as_of': 1704153601.0})+'\n')
        replay(fake, path)
        self.assertEqual(calls, [('ZEC', candle, 1704153601.0)])

    def test_archive_fallback_uses_closed_h1_structure_without_flow(self):
        day = datetime(2024, 1, 1, tzinfo=timezone.utc)
        candle = {'open_ts': day.timestamp(), 'available_ts': day.timestamp()+3600,
                  'open': 100, 'high': 101, 'low': 99, 'close': 100, 'interval_minutes': 60}
        seeds, observations = [], []
        fake = SimpleNamespace(states={'ZEC': SimpleNamespace(last_ts=None)}, coverage=[],
                               seed_h1=lambda symbol, row, as_of: seeds.append((symbol, row, as_of)),
                               on_candle=lambda symbol, row: observations.append((symbol, row)),
                               gap=lambda *args, **kwargs: None,
                               output=SimpleNamespace(flush=lambda: None))
        with patch.object(Archives, 'trades', side_effect=SourceError('missing')), \
             patch('caterpillar.sources.candles', return_value=iter([candle])) as fetch:
            status = historical(fake, self.root/'fallback', day, day+timedelta(days=1), allow_ohlcv=True)
        self.assertEqual(status, 'incomplete_coverage')
        self.assertEqual(fetch.call_args.kwargs['interval'], 60)
        self.assertEqual(seeds[0][2], candle['available_ts'])
        self.assertEqual(observations, [('ZEC', candle)])
        self.assertFalse(fake.coverage[0]['ohlcv_fallback']['flow_available'])


if __name__ == '__main__': unittest.main()
