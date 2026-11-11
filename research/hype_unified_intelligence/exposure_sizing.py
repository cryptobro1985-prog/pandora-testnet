#!/usr/bin/env python3
"""Paper-only equity risk sizing gate for HYPE futures research.

A fixed adverse stop, broker-side risk limits and order type cannot GUARANTEE
non-liquidation; outages, mark-price gaps and execution failures can bypass
stops. No API, no broker, no orders.

All numerical values are SCENARIO ASSUMPTIONS, not fitted alpha or a
person-specific financial recommendation.
"""
from __future__ import annotations
from dataclasses import dataclass,asdict
import math

@dataclass(frozen=True)
class ExposureScenario:
    leverage:float
    margin_fraction:float
    equity_risk_budget:float=.005
    stop_bps:float=35.0
    roundtrip_cost_bps:float=12.0
    extra_slippage_bps:float=8.0
    shock_gap_bps:float=100.0
    maintenance_rate:float=.005
    min_liquidation_cushion:float=4.0

def finite_positive(v):
    return isinstance(v,(int,float)) and math.isfinite(v) and v>0

def evaluate(s:ExposureScenario):
    """Fail closed on scenario violating equity risk budget or liq cushion.

    Risk estimate is a hypothetical stress LOSS of gross notional exposure
    times (stop + fees + slippage + gap shock). Actual realized loss can be
    larger, and liquidation is not modeled precisely.
    """
    if not finite_positive(s.leverage) or s.leverage<1:
        raise ValueError("leverage must be >=1")
    if not finite_positive(s.margin_fraction) or s.margin_fraction>1:
        raise ValueError("margin fraction must be in (0,1]")
    if not finite_positive(s.equity_risk_budget) or s.equity_risk_budget>=1:
        raise ValueError("invalid risk budget")
    if any(not math.isfinite(x) or x<0 for x in (
        s.stop_bps,s.roundtrip_cost_bps,s.extra_slippage_bps,
        s.shock_gap_bps,s.maintenance_rate)):
        raise ValueError("invalid cost / stop / maintenance input")
    worst_underlying=(
        s.stop_bps+s.roundtrip_cost_bps+
        s.extra_slippage_bps+s.shock_gap_bps
    )/10000
    notional_equity_multiple=s.leverage*s.margin_fraction
    expected_stop_equity_loss=notional_equity_multiple*(
        s.stop_bps+s.roundtrip_cost_bps+s.extra_slippage_bps
    )/10000
    stressed_equity_loss=notional_equity_multiple*worst_underlying
    # Approximate isolation liquidation boundary (NOT exchange formula).
    liq_distance=max(0,1/s.leverage-s.maintenance_rate)
    liq_cushion=(liq_distance/worst_underlying if worst_underlying>0 else None)
    max_margin=min(1.,s.equity_risk_budget/(
        s.leverage*worst_underlying)) if worst_underlying>0 else 0.
    # Zero exposure is the only way to ensure no scenario liquidation
    # from an unbounded adverse gap; ACCEPT is only a bounded stress gate.
    equity_gate=stressed_equity_loss<=s.equity_risk_budget
    cushion_gate=(liq_cushion is not None and
                  liq_cushion>=s.min_liquidation_cushion)
    pass_gate=equity_gate and cushion_gate
    return {
        "result":"PAPER_STRESS_PASS" if pass_gate else "REJECT",
        "paper_only":True,"real_orders":False,
        "leverage":s.leverage,"margin_fraction":s.margin_fraction,
        "notional_as_fraction_of_equity":notional_equity_multiple,
        "equity_risk_budget_pct":100*s.equity_risk_budget,
        "assumed_stressed_underlying_loss_pct":100*worst_underlying,
        "assumed_stop_equity_loss_pct":100*expected_stop_equity_loss,
        "assumed_stressed_equity_loss_pct":100*stressed_equity_loss,
        "approx_liq_underlying_distance_pct":100*liq_distance,
        "liquidation_cushion_multiple":liq_cushion,
        "max_margin_fraction_given_risk_budget":max_margin,
        "equity_risk_gate_pass":equity_gate,
        "liquidation_cushion_gate_pass":cushion_gate,
        "assumptions":asdict(s),
        "warning":"Bounded paper scenario only. Never guarantee execution, loss cap or non-liquidation."
    }

def scenario_grid():
    return [evaluate(ExposureScenario(leverage=L,margin_fraction=f))
            for L in (1,2,3,5,10,15,20,25)
            for f in (.01,.02,.03,.05,.10,.20)]

if __name__=="__main__":
    import json
    print(json.dumps({"scenarios":scenario_grid(),
                      "live_authorized":False},indent=2))
