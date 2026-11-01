"""Read-only monitor semantics: honest PnL units, safe data and stable updates."""
import json
import re
import unittest

from strategy1_monitor import render, render_history


class MonitorAuditTests(unittest.TestCase):
    def test_account_percent_and_position_percent_have_explicit_different_bases(self):
        page=render({'strategy1_primary':{'starting_equity':500,'total_equity':550,
            'realized_pnl':30,'unrealized_pnl':20,'open_positions':[{
                'symbol':'BTC','side':1,'opened':'2026-11-01T00:00:00Z',
                'entry':100,'mark':101,'margin_usd':20,'unrealized_pnl':5,'features':{}}]},'health':{}})
        self.assertIn('+50.0000 USDT',page)
        self.assertIn('+10.00%',page)
        self.assertIn('+25.00%',page)
        self.assertIn('PnL позиции и сделки в процентах — от её маржи',page)

    def test_negative_trade_result_is_visible_in_usdt_and_percent(self):
        page=render_history({'account':'strategy1','trades':[{'id':1,'symbol':'BTC','side':1,
            'pnl':-1,'margin':10,'reason':'risk_stop','features':{}}],'next_before_id':1})
        self.assertIn('-1.0000 USDT',page)
        self.assertIn('-10.00%',page)
        self.assertIn('negative',page)
        self.assertIn('before=1',page)

    def test_untrusted_values_are_escaped_in_markup_and_json(self):
        malicious='</script><img src=x onerror=alert(1)>'
        page=render({'strategy1_primary':{'tokens':[{'symbol':malicious,'action_reason':malicious}]},'health':{}})
        self.assertNotIn('<img src=x',page)
        bootstrap=re.search(r'<script type="application/json" id="initial-state">(.*?)</script>',page,re.S).group(1)
        self.assertNotIn('</script',bootstrap)
        self.assertEqual(json.loads(bootstrap)['strategy1_primary']['tokens'][0]['symbol'],malicious)

    def test_missing_or_non_finite_results_are_not_success_or_zero(self):
        page=render({'strategy1_primary':{'total_equity':float('nan'),'realized_pnl':None,
                                        'unrealized_pnl':None},'health':{}})
        self.assertIn('НЕ ГОТОВ',page)
        self.assertIn('нулевой PnL не подставляется',page)
        self.assertNotIn('>+0.0000 USDT<',page)
        bootstrap=re.search(r'<script type="application/json" id="initial-state">(.*?)</script>',page,re.S).group(1)
        self.assertIsNone(json.loads(bootstrap)['strategy1_primary']['total_equity'])
        self.assertNotIn('NaN',bootstrap)

    def test_updates_use_json_and_keyed_nodes_with_preserved_navigation(self):
        page=render({'strategy1_primary':{},'health':{}})
        self.assertIn("fetch('/api/pandora'",page)
        self.assertIn('function syncList(',page)
        self.assertIn("sessionStorage.setItem('pandora-tab'",page)
        self.assertIn('keep.node.isConnected',page)
        self.assertNotIn('DOMParser',page)
        self.assertNotIn('.innerHTML',page)
        self.assertNotIn('.replaceWith(',page)
        self.assertIn('prefers-reduced-motion',page)
        self.assertIn('grid-template-columns:minmax(0,1fr)',page)

    def test_risk_failure_is_not_hidden_behind_healthy_http(self):
        page=render({'strategy1_primary':{'risk':{'reason':'DAILY_LOSS_LIMIT'}},
                     'health':{'healthy':True,'risk_ready':False}})
        self.assertIn('DAILY_LOSS_LIMIT',page)
        self.assertIn('НЕ ГОТОВ',page)
