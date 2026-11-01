import json
import unittest

from pandora_api import API_VERSION, json_safe, openapi


class MonitorContractTests(unittest.TestCase):
    def test_readonly_openapi_contains_monitor_history_events_and_health(self):
        spec=openapi('https://example.test/')
        self.assertEqual(spec['info']['version'],API_VERSION)
        self.assertEqual(spec['servers'][0]['url'],'https://example.test')
        self.assertIn('/api/pandora',spec['paths'])
        self.assertIn('/api/pandora/history',spec['paths'])
        self.assertTrue(all(set(operations)=={'get'} for operations in spec['paths'].values()))

    def test_nonfinite_history_cannot_break_browser_json_or_become_false_zero(self):
        data={'loss':-12.5,'unknown':float('nan'),'positions':[float('inf'),float('-inf')]}
        result=json.loads(json.dumps(json_safe(data),allow_nan=False))
        self.assertEqual(result['loss'],-12.5)
        self.assertIsNone(result['unknown'])
        self.assertEqual(result['positions'],[None,None])
