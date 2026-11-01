"""Entry provenance and current PnL remain separate after adds and live updates."""
import re
import unittest

from strategy1_monitor import SCRIPT, render


def field(markup,name):
    match=re.search(r'<span data-field="'+name+r'"[^>]*>(.*?)</span>',markup,re.S)
    return match.group(1) if match else None


class PositionMonitorTests(unittest.TestCase):
    def position(self):
        return dict(symbol='BTC',side=1,opened='legacy-opened',entry_time='2026-11-01T09:10:00+04:00',
            entry=105,entry_price=100,average_entry=105,mark=106,margin_usd=50,
            unrealized_pnl=999,pnl_usdt=12,pnl_percent=24,
            entry_local={'pivot_type':'LOCAL_LOW','pivot_price':98},
            current_local={'confirmed_local':{'pivot_type':'LOCAL_LOW','pivot_price':103},
                           'forming_local':{'pivot_type':'LOCAL_HIGH','pivot_price':108}},
            features={'original_entry':100,'pyramid_level':1})

    def positions_markup(self,position):
        page=render({'strategy1_primary':{'open_positions':[position]},'health':{}})
        return page.split('<section id="panel-positions"',1)[1].split('</section>',1)[0]

    def test_original_entry_and_entry_local_do_not_move_to_average_or_current_local(self):
        markup=self.positions_markup(self.position())
        self.assertEqual(field(markup,'original_entry'),'100.0000')
        self.assertEqual(field(markup,'entry'),'105.0000')
        self.assertEqual(field(markup,'entry_time'),'2026-11-01T09:10:00+04:00')
        self.assertEqual(field(markup,'entry_local'),'LOCAL_LOW · 98.0000')
        self.assertEqual(field(markup,'current_confirmed'),'LOCAL_LOW · 103.0000')
        self.assertEqual(field(markup,'current_forming'),'LOCAL_HIGH · 108.0000')
        self.assertEqual(field(markup,'pnl'),'+12.0000 USDT')
        self.assertEqual(field(markup,'pnl_pct'),'+24.00%')

    def test_legacy_position_uses_entry_feature_and_calculates_margin_percent(self):
        p=dict(symbol='BTC',side=-1,opened='original-time',entry=100,mark=101,
               margin_usd=20,unrealized_pnl=-2,
               features={'original_entry':90,'pivot_type':'LOCAL_HIGH','pivot_price':102})
        markup=self.positions_markup(p)
        self.assertEqual(field(markup,'original_entry'),'90.0000')
        self.assertEqual(field(markup,'entry_time'),'original-time')
        self.assertEqual(field(markup,'entry_local'),'LOCAL_HIGH · 102.0000')
        self.assertEqual(field(markup,'pnl'),'-2.0000 USDT')
        self.assertEqual(field(markup,'pnl_pct'),'-10.00%')
        self.assertEqual(field(markup,'current_confirmed'),'—')

    def test_canonical_zero_and_unavailable_pnl_do_not_fall_back_to_stale_metrics(self):
        p=self.position();p.update(pnl_usdt=0,pnl_percent=0)
        self.assertEqual(field(self.positions_markup(p),'pnl'),'+0.0000 USDT')
        self.assertEqual(field(self.positions_markup(p),'pnl_pct'),'+0.00%')
        p.update(pnl_usdt=None,pnl_percent=None)
        self.assertEqual(field(self.positions_markup(p),'pnl'),'—')
        self.assertEqual(field(self.positions_markup(p),'pnl_pct'),'—')

    def test_held_discovery_card_exposes_entry_provenance_and_explicit_wait_reason(self):
        page=render({'strategy1_primary':{'tokens':[{'symbol':'BTC','position':self.position(),
            'decision':{'action':'WAIT','reason':'Покупатели не подтверждены'},
            'confirmed_local':{'pivot_type':'LOCAL_LOW','pivot_price':103}}]},'health':{}})
        discovery=page.split('<section id="panel-discovery"',1)[1].split('<details',1)[0]
        self.assertEqual(field(discovery,'original_entry'),'100.0000')
        self.assertEqual(field(discovery,'entry_local'),'LOCAL_LOW · 98.0000')
        self.assertEqual(field(discovery,'decision'),'ЖДЁМ')
        self.assertEqual(field(discovery,'reason'),'Покупатели не подтверждены')

    def test_startup_stage_is_visible_and_updates_without_replacing_html(self):
        page=render({'strategy1_primary':{'startup':{'stage':'FLOW_WARMUP','status':'WAITING',
                     'reason':'Нужно наблюдать свежие исполнения'}},'health':{}})
        self.assertIn('id="startup-stage">Наблюдение исполненных BUY / SELL',page)
        self.assertIn('id="startup-status">ЖДЁМ',page)
        self.assertIn('id="startup-reason">Нужно наблюдать свежие исполнения',page)
        for name in ('original_entry','entry_time','entry_local','current_confirmed','current_forming'):
            self.assertIn("'"+name+"'",SCRIPT)
        self.assertIn("text($('startup-stage'),startup.stage)",SCRIPT)
        self.assertNotIn('.innerHTML',SCRIPT)
        self.assertNotIn('replaceWith',SCRIPT)
