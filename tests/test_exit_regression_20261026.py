"""Reproduce observed fixed-price fills, lost MFE and delayed thesis exits."""
import ast
import copy
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from hype_h1_swing import update_path, profit_lock_exit
from momentum_scanner import continuation_candidates
from news_logic import analyze_headline


def app_function(name, namespace):
    # Load the real function without starting the service or requiring DB drivers.
    tree = ast.parse(Path('app.py').read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), namespace)
    return namespace[name]


class RegressionTests(unittest.TestCase):
    def test_local_lock_tracks_peak_and_fills_at_observed_mark_for_both_sides(self):
        for side in (-1, 1):
            p = dict(entry=100., side=side, leverage=25., features={})
            p, _ = update_path(p, 100 * (1 + side * .02))
            self.assertAlmostEqual(p['features']['profit_lock_stop'], 100 * (1 + side * .01))
            p, _ = update_path(p, 100 * (1 + side * .015))
            self.assertIsNone(profit_lock_exit(p, 100 * (1 + side * .015)))
            gap_mark = 100 * (1 - side * .005)
            self.assertEqual(profit_lock_exit(p, gap_mark), gap_mark)
            self.assertAlmostEqual(p['features']['profit_lock_stop'], 100 * (1 + side * .01))

    def test_shared_profit_lock_retains_half_peak_and_does_not_invent_gap_fill(self):
        ns = dict(copy=copy, MARKET_OBS=SimpleNamespace(context=lambda *a: {}),
                  _timeline_return=lambda *a: None, now=lambda: 'test',
                  PROFIT_PROTECT_ARM_MOVE=.004, PROFIT_PROTECT_LOCK_MOVE=.0012,
                  PROFIT_PROTECT_R15=.0012, PROFIT_PROTECT_R60=.0022,
                  PROFIT_PROTECT_FLOW=.12, PROFIT_PROTECT_REVERSAL_MIN_MOVE=.0012)
        evaluate = app_function('_profit_protection_eval', ns)
        for side in (-1, 1):
            p = dict(entry=100., side=side)
            p, reason, _, state = evaluate(p, 'X', 100 * (1 + side * .02), 1, [])
            self.assertIsNone(reason)
            self.assertAlmostEqual(state['stop'], 100 * (1 + side * .01))
            gap = 100 * (1 - side * .005)
            _, reason, fill, _ = evaluate(p, 'X', gap, 2, [])
            self.assertEqual(reason, 'profit_lock_stop')
            self.assertEqual(fill, gap)

    def test_whale_absolute_invalidation_works_without_widening_streak(self):
        closed = []
        pos = dict(entry=100., side=1, leverage=25., opened='test',
                   features=dict(liquidation_price=100.5, victim_side='short',
                                 ptv_entry_distance_pct=.5,
                                 ptv_distance_history_after_entry=[1.52]))
        ns = dict(copy=copy, LOCK=threading.RLock(), time=SimpleNamespace(time=lambda: 10),
                  S=dict(whale_positions={'X': pos}, _timeline={}), now=lambda: 'test',
                  MARKET_OBS=SimpleNamespace(context=lambda *a: {}),
                  _timeline_return=lambda *a: None,
                  _profit_protection_eval=lambda p,*a: (p,None,None,{}),
                  _profit_protection_arm_journal=lambda *a: None,
                  whale_liq_close=lambda *a: closed.append(a))
        app_function('whale_liq_mark_positions',ns)({'X':99.})
        self.assertEqual(closed[0][2], 'ptv_distance_invalidation')

    def test_equity_buyback_is_not_eth_purchase(self):
        title = "Tom Lee's Bitmine favors share buybacks to ether purchases as crypto declines"
        self.assertEqual(analyze_headline(title, {'ETH':3000})['side'], 0)
        self.assertEqual(analyze_headline('$ETH buyback announced', {'ETH':3000})['side'], 1)

    def test_continuation_needs_abnormal_volume_not_oi_or_ordinary_rebound(self):
        t=1000.;history={'X':[(t-a,100/(1+a*.00003)) for a in range(182,0,-2)]}
        ctx={'epoch':t,'trade_data_fresh':True,'flow_imbalance':.8,
             'volume_burst_ratio':1.6,'volume_rate_z':.2,'oi_delta_60s':.01}
        args=({'X':100},history,{'X':1e7},t,{'X':ctx},{'side':1})
        self.assertEqual(continuation_candidates(*args),[])
        ctx.update(volume_burst_ratio=3,volume_rate_z=2)
        self.assertEqual(len(continuation_candidates(*args)),1)
