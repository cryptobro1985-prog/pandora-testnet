"""PAPER ONLY: size HYPE positions using estimated all-in stop loss.

No guarantee of stop fills or avoidance of liquidation in gaps/outages.
All fractional inputs are decimals; outputs are notional fractions of equity.
"""
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class RiskInputs:
    stop_fraction: float
    risk_fraction: float
    round_trip_fee_fraction: float = 0.0015
    extra_slippage_fraction: float = 0.001
    max_notional_to_equity: float = 1.0
    max_margin_fraction: float = 0.20
    exchange_leverage: float = 2.0
    expected_funding_fraction: float = 0.0

def max_notional_fraction(params: RiskInputs) -> float:
    values = list(vars(params).values())
    if any(not math.isfinite(v) for v in values):
        raise ValueError('nonfinite risk input')
    if params.stop_fraction <= 0 or params.risk_fraction <= 0 or params.exchange_leverage < 1:
        raise ValueError('invalid stop/risk/leverage')
    if any(v < 0 for v in (params.round_trip_fee_fraction, params.extra_slippage_fraction,
                          params.expected_funding_fraction, params.max_margin_fraction,
                          params.max_notional_to_equity)):
        raise ValueError('negative cost or cap')
    loss_per_notional = (params.stop_fraction + params.round_trip_fee_fraction
                         + params.extra_slippage_fraction + params.expected_funding_fraction)
    return min(params.risk_fraction / loss_per_notional,
               params.max_notional_to_equity,
               params.max_margin_fraction * params.exchange_leverage)

def planned_max_loss_fraction(params: RiskInputs) -> float:
    return max_notional_fraction(params) * (params.stop_fraction + params.round_trip_fee_fraction
                             + params.extra_slippage_fraction + params.expected_funding_fraction)
