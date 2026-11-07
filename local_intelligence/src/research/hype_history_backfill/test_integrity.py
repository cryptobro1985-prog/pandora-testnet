import gzip
import json
import tempfile
import unittest
from pathlib import Path

from research.hype_history_backfill.run import enrich, last_at
from research.hype_history_backfill.verify import parse_json, verify
from research.hype_local_v5.labels import completed_hours, structural_labels


class HistoricalAvailabilityTests(unittest.TestCase):
    def test_completion_publication_receipt_and_staleness(self):
        rows = [dict(ts_ms=0, close=10), dict(ts_ms=60_000, close=20, received_at_ms=130_000)]
        keys = [0, 60_000]
        self.assertIsNone(last_at(rows, keys, 60_999, True, publication_lag_ms=1000))
        self.assertEqual(last_at(rows, keys, 61_000, True, publication_lag_ms=1000), rows[0])
        self.assertEqual(last_at(rows, keys, 121_000, True, publication_lag_ms=1000), rows[0])
        self.assertEqual(last_at(rows, keys, 130_000, True, publication_lag_ms=1000), rows[1])
        self.assertIsNone(last_at(rows, keys, 240_001, True, max_age_ms=120_000))
        canonical_receipt = [dict(ts_ms=0, close=10, received_ts_ms=120_000)]
        self.assertIsNone(last_at(canonical_receipt, [0], 61_000, True, publication_lag_ms=1000))
        self.assertEqual(last_at(canonical_receipt, [0], 120_000, True, publication_lag_ms=1000), canonical_receipt[0])

    def test_reenrichment_clears_stale_values_and_oi_change_anchors_to_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp)/'in.gz', Path(tmp)/'out.gz'
            snapshots = [dict(side='LOW', extreme_price=100, snapshot_ts_ms=601_000,
                              features={'hist_mark_price_rel': 999, 'hist_funding_rate': 999}),
                         dict(side='LOW', extreme_price=100, snapshot_ts_ms=600_000_000,
                              features={'hist_open_interest_log': 999})]
            with gzip.open(src, 'wt') as stream:
                for row in snapshots:
                    stream.write(json.dumps(row)+'\n')
            oi = [dict(ts_ms=t, open_interest=v) for t,v in [(0,100),(300_000,110),(600_000,121)]]
            counts = enrich(src,out,[],[],oi,[])
            with gzip.open(out,'rt') as stream:
                joined = [json.loads(line) for line in stream]
            first = joined[0]
            self.assertAlmostEqual(first['features']['hist_oi_delta_300s'], .1)
            self.assertEqual(first['historical_gap_sources']['oi_ts_ms'], 600_000)
            self.assertIsNone(first['historical_gap_sources']['oi']['received_at_ms'])
            self.assertTrue(first['historical_gap_sources']['availability_assumed'])
            self.assertNotIn('hist_mark_price_rel', first['features'])
            self.assertNotIn('hist_funding_rate', first['features'])
            self.assertNotIn('hist_open_interest_log', joined[1]['features'])
            self.assertEqual(counts['oi'], 1)

    def test_invalid_source_order_or_lag_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                enrich(Path(tmp)/'in', Path(tmp)/'out', [], [], [dict(ts_ms=2),dict(ts_ms=1)], [])
        with self.assertRaises(ValueError):
            last_at([], [], 0, publication_lag_ms=-1)


class TeacherChronologyTests(unittest.TestCase):
    @staticmethod
    def hour(i, price=100):
        return dict(start_ms=i*3_600_000, bar_end_ms=(i+1)*3_600_000,
                    ts_ms=(i+1)*3_600_000, open=price, high=price+1,
                    low=price-1, close=price)

    def test_teacher_waits_for_delayed_final_future_hour(self):
        rows = [self.hour(i, p) for i,p in enumerate([100,102,101,100,101])]
        rows[3]['ts_ms'] += 7000
        labels, _ = structural_labels(rows, lookback=1, lookahead=2)
        self.assertEqual(labels[0]['side'], 'HIGH')
        self.assertEqual(labels[0]['label_available_ms'], rows[3]['ts_ms'])
        self.assertIsNone(labels[-1]['reference_finalized_ms'])
        self.assertFalse(labels[-1]['reference_finalized'])

    def test_incomplete_or_overlapping_hours_cannot_create_teacher(self):
        row = self.hour(0)
        partial = {**row, 'bar_end_ms': 3_000_000}
        self.assertEqual(completed_hours([partial]), [])
        self.assertEqual(completed_hours([row,row]), [])
        bad = {**row, 'ts_ms': row['bar_end_ms']-1}
        with self.assertRaises(ValueError): completed_hours([bad])
        with self.assertRaises(ValueError): structural_labels([row], lookback=0)

    def test_hour_input_order_does_not_change_extreme_interval(self):
        rows = [dict(start_ms=i*60_000, ts_ms=(i+1)*60_000,
                     open=100, high=101+(i==5), low=99, close=100) for i in range(60)]
        self.assertEqual(completed_hours(rows), completed_hours(list(reversed(rows))))

    def test_finalization_cannot_predate_late_receipt_of_own_pivot_window(self):
        prices = [100,110,105,104,103,102,101,100,99,98,90,95,96]
        rows = [self.hour(i,p) for i,p in enumerate(prices)]
        rows[0]['ts_ms'] = 25*3_600_000
        labels, _ = structural_labels(rows, lookback=1, lookahead=1)
        self.assertEqual(labels[0]['side'], 'HIGH')
        self.assertEqual(labels[0]['label_available_ms'], 25*3_600_000)
        self.assertEqual(labels[0]['reference_finalized_ms'], 25*3_600_000)


class OfflineVerificationTests(unittest.TestCase):
    def test_truncated_gzip_and_invalid_float_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'bad.json').write_text('{"value":1e999}', encoding='utf-8')
            compressed = gzip.compress(b'{"value":1}\n')
            (root/'bad.jsonl.gz').write_bytes(compressed[:-4])
            report = verify(root)
            self.assertFalse(report['valid'])
            self.assertEqual(report['files_checked'], 2)
            self.assertEqual(len(report['errors']), 2)
        for raw in ('{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}'):
            with self.assertRaises(ValueError):parse_json(raw)

    def test_manifest_tampering_fails_without_loading_pickle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'data.json').write_text('{}', encoding='utf-8')
            (root/'model.pkl').write_bytes(b'not a pickle and must never be opened')
            (root/'manifest.json').write_text(json.dumps({'files':{
                'data.json':{'sha256':'0'*64,'bytes':2}}}), encoding='utf-8')
            report = verify(root)
            self.assertFalse(report['valid'])
            self.assertEqual(report['manifest_entries_checked'], 1)
            self.assertEqual(len(report['serialization']), 2)

    def test_manifest_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'manifest.json').write_text(json.dumps({'files':{
                '../../unrelated.json':{'sha256':'0'*64}}}), encoding='utf-8')
            report = verify(root)
            self.assertFalse(report['valid'])
            self.assertIn('unsafe declared path', report['errors'][0])

    def test_nonobject_manifest_is_a_schema_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for value in ([],None,1):
                (root/'manifest.json').write_text(json.dumps(value), encoding='utf-8')
                report = verify(root)
                self.assertFalse(report['valid'])
                self.assertIn('manifest must be an object', report['errors'][0])

    def test_malformed_declared_entries_cannot_silently_disappear(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'manifest.json').write_text('{"files":[]}', encoding='utf-8')
            (root/'artifact_manifest.json').write_text('{"missing.json":{}}', encoding='utf-8')
            report = verify(root)
            self.assertFalse(report['valid'])
            self.assertEqual(len(report['errors']), 2)


if __name__ == '__main__':
    unittest.main()
