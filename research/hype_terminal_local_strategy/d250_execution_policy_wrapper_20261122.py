#!/usr/bin/env python3
"""Research-only D250 execution-policy wrapper. No orders or Bybit spec claims."""
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from dataclasses import replace
from d250_combined_risk_gate_20261122 import evaluate

MAX_LEVERAGE = 25.0
MAX_MARGIN_FRACTION = 0.20

def policy_evaluate(candidate, state, *, actual_leverage, lot_step, min_qty, min_notional):
    """Fail closed on overrides, leverage mismatch, missing/invalid instrument limits.
    Instrument limits must be sourced and timestamp-verified by the caller.
    """
    if not (0 < candidate.max_leverage <= MAX_LEVERAGE and
            0 < candidate.max_margin_fraction <= MAX_MARGIN_FRACTION):
        return {"status":"BLOCK","reason":"POLICY_CAP_OVERRIDE"}
    if (not isinstance(actual_leverage,(int,float)) or
        actual_leverage != candidate.max_leverage or
        not (0 < actual_leverage <= MAX_LEVERAGE)):
        return {"status":"BLOCK","reason":"ACCOUNT_LEVERAGE_UNVERIFIED"}
    try:
        step, minimum, notional_min = [Decimal(str(x)) for x in (lot_step,min_qty,min_notional)]
        if not all(x.is_finite() and x>0 for x in (step,minimum,notional_min)):
            raise ValueError("invalid limits")
    except (InvalidOperation,ValueError,TypeError):
        return {"status":"BLOCK","reason":"INSTRUMENT_LIMITS_UNVERIFIED"}
    result = evaluate(candidate,state)
    if result["status"] != "RESEARCH_CANDIDATE_ONLY":
        return result
    raw = Decimal(str(result["sizing"]["notional"])) / Decimal(str(candidate.entry))
    qty = (raw/step).to_integral_value(rounding=ROUND_DOWN)*step
    actual_notional = qty*Decimal(str(candidate.entry))
    if qty < minimum or actual_notional < notional_min:
        return {"status":"BLOCK","reason":"BELOW_EXCHANGE_MINIMUM_NO_ROUND_UP"}
    modeled_loss_fraction = (abs(candidate.entry-candidate.stop)/candidate.entry +
                             candidate.round_trip_cost_fraction+candidate.adverse_gap_fraction)
    actual_loss = float(actual_notional)*modeled_loss_fraction
    remaining = min(candidate.risk_fraction, .01-candidate.existing_stop_risk)
    if actual_loss > candidate.equity*remaining+1e-9:
        return {"status":"BLOCK","reason":"RISK_BUDGET_AFTER_ROUNDING"}
    return {"status":"RESEARCH_CANDIDATE_ONLY","not_executable":True,
            "quantity":str(qty),"notional":str(actual_notional),
            "modeled_stress_loss":actual_loss,
            "note":"Limits and liquidation snapshot supplied by caller; no real fill or mark replay."}
