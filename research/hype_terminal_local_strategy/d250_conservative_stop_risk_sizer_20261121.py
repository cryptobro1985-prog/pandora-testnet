#!/usr/bin/env python3
"""Research-only conservative sizing gate for frozen D250 confirmed-local entries.
Not an exchange liquidation calculator, fill simulator, or claim of safe execution.
All inputs are explicit; missing mark/liquidation or stress slippage fails closed.
"""
import math
from dataclasses import dataclass

@dataclass(frozen=True)
class Candidate:
    side: str
    equity: float
    entry: float
    stop: float
    risk_fraction: float
    existing_stop_risk: float
    round_trip_cost_fraction: float
    adverse_gap_fraction: float
    liquidation_price: float
    max_leverage: float = 25.0
    max_margin_fraction: float = 0.20

def size(c: Candidate):
    vals = (c.equity,c.entry,c.stop,c.risk_fraction,c.existing_stop_risk,
            c.round_trip_cost_fraction,c.adverse_gap_fraction,c.liquidation_price,
            c.max_leverage,c.max_margin_fraction)
    if not all(math.isfinite(v) for v in vals):
        return {"status":"BLOCK","reason":"NONFINITE"}
    if c.side not in ("LONG","SHORT") or min(c.equity,c.entry,c.stop,c.liquidation_price,c.max_leverage)<=0:
        return {"status":"BLOCK","reason":"INVALID_PRICE_OR_SIDE"}
    if not (0<c.risk_fraction<=0.005 and 0<=c.existing_stop_risk<=0.01 and
            0<=c.round_trip_cost_fraction<1 and 0<=c.adverse_gap_fraction<1 and
            0<c.max_margin_fraction<=1):
        return {"status":"BLOCK","reason":"INVALID_BUDGET"}
    adverse = (c.entry-c.stop)/c.entry if c.side=="LONG" else (c.stop-c.entry)/c.entry
    liquidation_distance = (c.entry-c.liquidation_price)/c.entry if c.side=="LONG" else (c.liquidation_price-c.entry)/c.entry
    if adverse<=0 or liquidation_distance<=0 or adverse+c.adverse_gap_fraction>=liquidation_distance:
        return {"status":"BLOCK","reason":"STOP_NOT_BEFORE_LIQUIDATION_UNDER_STRESS"}
    remaining = min(c.risk_fraction,0.01-c.existing_stop_risk)
    if remaining<=0:
        return {"status":"BLOCK","reason":"AGGREGATE_RISK_EXHAUSTED"}
    stressed_loss_per_notional = adverse+c.round_trip_cost_fraction+c.adverse_gap_fraction
    risk_notional = c.equity*remaining/stressed_loss_per_notional
    margin_cap = c.equity*c.max_margin_fraction*c.max_leverage
    notional = min(risk_notional,margin_cap)
    return {"status":"SIZED","notional":round(notional,8),
            "exposure_x":round(notional/c.equity,8),
            "margin":round(notional/c.max_leverage,8),
            "stressed_stop_loss":round(notional*stressed_loss_per_notional,8),
            "stressed_stop_risk_fraction":round(notional*stressed_loss_per_notional/c.equity,8),
            "risk_cap_binding":"MARGIN" if margin_cap<risk_notional else "STOP_RISK",
            "note":"Model-only: gaps may exceed assumed stress; liquidation price must be sourced from exchange account state."}

if __name__=="__main__":
    import unittest
    class Tests(unittest.TestCase):
        def case(self,side="LONG",**kwargs):
            d=dict(side=side,equity=100,entry=100,stop=99 if side=="LONG" else 101,
                   risk_fraction=.005,existing_stop_risk=0,
                   round_trip_cost_fraction=.0015,adverse_gap_fraction=.02,
                   liquidation_price=95 if side=="LONG" else 105)
            d.update(kwargs)
            return Candidate(**d)
        def test_long(self):
            x=size(self.case());self.assertEqual(x["status"],"SIZED")
            self.assertAlmostEqual(x["notional"],15.87301587,places=6)
            self.assertLessEqual(x["stressed_stop_loss"],.5)
        def test_short(self):
            self.assertEqual(size(self.case("SHORT"))["status"],"SIZED")
        def test_liquidation(self):
            self.assertEqual(size(self.case(liquidation_price=98))["status"],"BLOCK")
        def test_aggregate(self):
            x=size(self.case(existing_stop_risk=.009))
            self.assertLessEqual(x["stressed_stop_loss"],.10000001)
        def test_nonfinite(self):
            self.assertEqual(size(self.case(adverse_gap_fraction=float("nan")))["status"],"BLOCK")
        def test_wrong_side_stop(self):
            self.assertEqual(size(self.case(stop=101))["status"],"BLOCK")
    unittest.main()
