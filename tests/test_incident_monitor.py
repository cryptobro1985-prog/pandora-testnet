"""Reported monitor precision, first-mark race and historical-local growth."""
import re
import unittest

from pandora_monitor import render


def token_price(mark):
    page=render({'pandora':{'tokens':[{'symbol':'ESPORTS','price':mark}]},'health':{}})
    section=page.split('<div id="tokens"',1)[1].split('<details',1)[0]
    return re.search(r'data-field="price"[^>]*>(.*?)</span>',section).group(1)


class IncidentMonitorTests(unittest.TestCase):
    def test_real_small_token_price_changes_are_visible_without_rounding_freeze(self):
        self.assertNotEqual(token_price(.012691),token_price(.012692))
        self.assertNotEqual(token_price(.000000012691),token_price(.000000012692))
        self.assertEqual(token_price(100),'100.0000')

    def test_selected_market_without_first_mark_is_labeled_as_waiting(self):
        page=render({'pandora':{'tokens':[{'symbol':'AIXBT','price':None,'mark_fresh':False,'scanner_price':.1234567,'scanner_price_age_seconds':.5,
            'confirmed_local':{'pivot_type':'LOCAL_HIGH','pivot_price':.13},
            'execution_local':{'pivot_type':'LOCAL_LOW','pivot_price':.12,'confirmation_source':'closed_m15_after_observed_extreme'}}]},'health':{}})
        self.assertIn('WAIT FIRST MARK',page)
        self.assertIn('Исторический confirmed H1',page)
        self.assertIn('Активный local H1/M15',page)
        self.assertIn('LOCAL_LOW · 0.120000 · closed_m15_after_observed_extreme',page)
        self.assertIn('0.123457 · 0.5 s',page)
        self.assertRegex(page, r'data-field="price"[^>]*>—</span>')
        self.assertNotIn('>0.0000</span>',page)

    def test_stale_mark_and_fresh_mark_are_not_confused_with_fresh_flow(self):
        page=render({'pandora':{'tokens':[{'symbol':'ZRO','price':1.8,'mark_fresh':False,
            'price_age_seconds':32,'flow_state':{'trade_data_fresh':True}}]},'health':{}})
        self.assertIn('STALE · 32.0 s',page)
        page=render({'pandora':{'tokens':[{'symbol':'ZRO','price':1.8,'mark_fresh':True,
            'price_age_seconds':1.2,'flow_state':{'trade_data_fresh':False}}]},'health':{}})
        self.assertIn('FRESH · 1.2 s',page)

    def test_archived_rotated_locals_do_not_create_unbounded_hidden_dom(self):
        durable={f'OLD{i}':{'pivot_type':'LOCAL_HIGH','pivot_price':i+1} for i in range(400)}
        page=render({'pandora_symbols':['ZRO'],'pandora':{'h1_durable':durable,
            'engine':{'details':{'ZRO':{'h1_local':{'pivot_type':'LOCAL_LOW','pivot_price':1.8}}}},
            'open_positions':[{'symbol':'HELD','opened':'fixture','side':-1}]},'health':{}})
        locals_section=page.split('<div id="locals"',1)[1].split('</details>',1)[0]
        self.assertNotIn('OLD399',locals_section)
        self.assertIn('data-key="HELD"',locals_section)
        self.assertIn('data-key="ZRO"',locals_section)
