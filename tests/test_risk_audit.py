"""Adversarial sizing/model checks; no fixed percentage trading exits or halts."""
from dataclasses import FrozenInstanceError
import unittest
from unittest.mock import patch

from accounting import paper_pnl
from pandora_risk import (RiskPolicy, plan_entry, plan_add, position_guard,
                         position_risk, protective_stop, signal_strength)


def structure(side=1):
    return dict(anchor_confirmed=True,entry_side=side,ready=True)


def tape(side=1,strong=True):
    windows={}
    for seconds in (5,15,30,60):
        windows[str(seconds)]=dict(trade_count=10,imbalance=side*(1 if strong else .1),
            price_return=side*.002 if strong else 0,
            volume_velocity=200 if strong and seconds==15 else 50)
    return dict(trade_data_fresh=True,windows=windows)


class DynamicSizingTests(unittest.TestCase):
    def test_defaults_have_no_fixed_loss_budgets_and_honor_entry_minimums(self):
        policy=RiskPolicy()
        self.assertIsNone(policy.position_risk_fraction)
        self.assertIsNone(policy.portfolio_risk_fraction)
        self.assertIsNone(policy.daily_loss_fraction)
        plan=plan_entry(500,500,100,100,1,{}, {})
        self.assertTrue(plan.allowed)
        self.assertGreaterEqual(plan.margin,50)
        self.assertGreaterEqual(plan.leverage,10)
        self.assertIsNone(plan.risk_budget)
        self.assertTrue(plan.planning_reference_only)
        with self.assertRaises(FrozenInstanceError):plan.notional=5000

    def test_stronger_corroborated_volume_structure_selects_larger_margin_and_leverage(self):
        weak=plan_entry(500,500,100,100,1,structure(),tape(strong=False))
        strong=plan_entry(500,500,100,100,1,structure(),tape(strong=True))
        self.assertTrue(weak.allowed and strong.allowed)
        self.assertGreater(strong.margin,weak.margin)
        self.assertGreater(strong.leverage,weak.leverage)
        self.assertEqual(strong.margin,150)
        self.assertEqual(strong.signal_strength,1)

    def test_wider_observed_geometry_reduces_leverage_or_refuses_below_ten(self):
        calm=plan_entry(500,500,100,100,1,structure(),tape())
        wide=tape();wide['windows']['60']['price_range_fraction']=.06
        constrained=plan_entry(500,500,100,100,1,structure(),wide)
        self.assertTrue(constrained.allowed)
        self.assertLess(constrained.leverage,calm.leverage)
        wide['windows']['60']['price_range_fraction']=.15
        refused=plan_entry(500,500,100,100,1,structure(),wide)
        self.assertFalse(refused.allowed)
        self.assertEqual(refused.reason,'CONTRACT_OR_GEOMETRY_BELOW_MIN_LEVERAGE')

    def test_fifty_requires_both_signal_support_and_declared_geometry(self):
        policy=RiskPolicy(minimum_adverse_move=.002,maintenance_rate=.005,liquidation_buffer=.001)
        high=plan_entry(500,500,100,100,1,structure(),tape(),policy=policy)
        low=plan_entry(500,500,10,100,1,structure(),tape(),policy=policy)
        self.assertEqual(high.leverage,50)
        self.assertEqual(low.leverage,10)
        below=plan_entry(500,500,5,100,1,structure(),tape(),policy=policy)
        self.assertFalse(below.allowed)

    def test_insufficient_cash_never_produces_a_position_below_ten_percent_equity(self):
        plan=plan_entry(500,49,100,100,1,structure(),tape())
        self.assertFalse(plan.allowed)
        self.assertEqual(plan.reason,'MIN_ENTRY_MARGIN_UNFUNDED')
        cash_limited=plan_entry(500,80,100,100,1,structure(),tape())
        self.assertTrue(cash_limited.allowed)
        self.assertGreaterEqual(cash_limited.margin,50)
        self.assertLess(cash_limited.margin,80)

    def test_compounding_recomputes_minimum_margin_from_current_equity(self):
        first=plan_entry(500,500,100,100,1,{}, {})
        second=plan_entry(800,800,100,100,1,{}, {})
        self.assertEqual(first.margin,50)
        self.assertEqual(second.margin,80)

    def test_optional_loss_caps_apply_only_if_explicit_and_never_break_entry_floor(self):
        uncapped=plan_entry(500,500,100,100,1,{}, {},portfolio_risk=10000)
        self.assertTrue(uncapped.allowed)
        self.assertIsNone(uncapped.risk_budget)
        cap=RiskPolicy(position_risk_fraction=.01)
        small=plan_entry(500,500,100,100,1,{}, {},policy=cap)
        self.assertFalse(small.allowed)
        self.assertEqual(small.reason,'OPTIONAL_RISK_CAP_BELOW_ENTRY_MINIMUM')
        feasible=plan_entry(500,500,100,100,1,{}, {},policy=RiskPolicy(position_risk_fraction=.02))
        self.assertTrue(feasible.allowed)
        self.assertLessEqual(feasible.estimated_loss,10+1e-9)
        self.assertGreaterEqual(feasible.margin,50)

    def test_optional_environment_caps_can_be_explicitly_disabled(self):
        with patch.dict('os.environ',{'PANDORA_POSITION_RISK_FRACTION':'off',
              'PANDORA_PORTFOLIO_RISK_FRACTION':'none','PANDORA_DAILY_LOSS_FRACTION':''},clear=True):
            policy=RiskPolicy.from_env()
        self.assertIsNone(policy.position_risk_fraction)
        self.assertIsNone(policy.portfolio_risk_fraction)
        self.assertIsNone(policy.daily_loss_fraction)

    def test_invalid_inputs_and_zero_adverse_planning_floor_are_rejected(self):
        self.assertFalse(plan_entry(500,float('nan'),100,100,1,{},{}).allowed)
        self.assertFalse(plan_entry(-5,500,100,100,1,{},{}).allowed)
        with self.assertRaises(ValueError):RiskPolicy(minimum_adverse_move=0)
        with self.assertRaises(ValueError):RiskPolicy(min_margin_fraction=.4,max_entry_margin_fraction=.3)


class MaintenanceModelTests(unittest.TestCase):
    def position(self,side=1):
        plan=plan_entry(500,500,100,100,side,{},{}).to_dict()
        return dict(entry=100,side=side,notional=plan['notional'],margin=plan['margin'],
                    leverage=plan['leverage'],features={'risk_plan':plan})

    def test_crossing_planning_reference_is_not_a_fixed_percentage_exit(self):
        for side in (-1,1):
            p=self.position(side)
            reference=protective_stop(p)
            self.assertTrue(p['features']['risk_plan']['planning_reference_only'])
            self.assertEqual(reference,p['features']['risk_plan']['reference_price'])
            self.assertIsNone(position_guard(p,100-side*1.1))
            self.assertLess(paper_pnl(p['notional'],100,100-side*1.1,side),0)

    def test_price_gap_maintenance_breach_preserves_actual_negative_pnl(self):
        p=self.position()
        self.assertEqual(position_guard(p,89),'modeled_maintenance_breach')
        actual=paper_pnl(p['notional'],100,89,1)
        reference=paper_pnl(p['notional'],100,protective_stop(p),1)
        self.assertLess(actual,reference)
        self.assertLess(actual,0)

    def test_legacy_exposure_has_maintenance_check_without_rewriting_size_or_stopping_at_reference(self):
        p=dict(entry=100,notional=2500,margin=100,leverage=25,side=1,features={})
        self.assertIsNone(position_guard(p,98.9))
        self.assertEqual(position_guard(p,90),'modeled_maintenance_breach')
        self.assertEqual(p['notional'],2500)
        self.assertEqual(p['features'],{})

    def test_giving_back_positive_mfe_does_not_generate_a_fixed_profit_exit(self):
        for side in (-1,1):
            p=self.position(side)
            p['features']['peak_mfe_usd']=paper_pnl(p['notional'],100,100+side*4,side)
            reference=protective_stop(p)
            self.assertEqual(protective_stop(p),reference)
            self.assertIsNone(position_guard(p,100+side*.5))


class AggregateAddTests(unittest.TestCase):
    def base(self):
        entry=plan_entry(500,500,100,100,1,{},{}).to_dict()
        return dict(entry=100,notional=entry['notional'],margin=entry['margin'],
                    side=1,leverage=entry['leverage'],features={'risk_plan':entry})

    def test_add_rechecks_whole_position_quantity_margin_and_optional_caps(self):
        p=self.base()
        plan=plan_add(p,103,50,510,450,100,structure(),tape(),portfolio_risk=position_risk(p))
        self.assertTrue(plan.allowed)
        self.assertGreaterEqual(plan.leverage,10)
        self.assertIsNone(plan.risk_budget)
        self.assertAlmostEqual(plan.notional/plan.average_entry,p['notional']/100+plan.added_notional/103)
        self.assertGreaterEqual(plan.margin,p['margin'])
        self.assertEqual(plan.stop_price,p['features']['risk_plan']['stop_price'])
        capped=plan_add(p,103,50,510,450,100,structure(),tape(),
                        portfolio_risk=position_risk(p),policy=RiskPolicy(position_risk_fraction=.05))
        if capped.allowed:self.assertLessEqual(capped.estimated_loss,capped.risk_budget+1e-8)

    def test_no_add_to_losing_position_or_legacy_without_geometry_reference(self):
        p=self.base()
        self.assertFalse(plan_add(p,99,50,500,400,100,{},{}).allowed)
        p['features']={}
        self.assertFalse(plan_add(p,103,50,500,400,100,{},{}).allowed)

    def test_huge_requested_add_cannot_create_cash_or_release_existing_margin(self):
        p=self.base()
        plan=plan_add(p,103,1e9,510,1,100,structure(),tape())
        if plan.allowed:
            self.assertLessEqual(plan.added_margin+plan.added_notional*.0019,1+1e-8)
            self.assertLessEqual(plan.margin,510*.40+1e-8)
            self.assertGreaterEqual(plan.margin,p['margin'])
            self.assertGreaterEqual(plan.added_margin,0)
