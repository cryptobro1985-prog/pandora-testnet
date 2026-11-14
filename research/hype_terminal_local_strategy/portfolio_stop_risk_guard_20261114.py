"""Research-only portfolio risk sizing. No orders, no assumed fills.
Run: python research/hype_terminal_local_strategy/portfolio_stop_risk_guard_20261114.py
"""
import json
import math

def authorize(equity, side, entry, stop, risk_fraction=.005,
              fees_fraction=.0015, gap_fraction=.01,
              existing_stop_risk=0., max_total_risk=.01,
              max_notional_multiple=1.):
    """Notional based on price loss + costs + stress gap; fail closed."""
    vals=(equity,entry,stop,risk_fraction,fees_fraction,gap_fraction,
          existing_stop_risk,max_total_risk,max_notional_multiple)
    if not all(isinstance(x,(float,int)) and not isinstance(x,bool)
               and math.isfinite(x) for x in vals):
        return {"status":"REJECT_INVALID_NUMBER"}
    if equity<=0 or entry<=0 or stop<=0 or risk_fraction<=0 or max_total_risk<=0 or max_notional_multiple<=0:
        return {"status":"REJECT_INVALID_INPUT"}
    if fees_fraction<0 or gap_fraction<0 or existing_stop_risk<0 or risk_fraction>max_total_risk:
        return {"status":"REJECT_INVALID_INPUT"}
    if side not in ("LONG","SHORT") or (side=="LONG" and stop>=entry) or (side=="SHORT" and stop<=entry):
        return {"status":"REJECT_STOP_GEOMETRY"}
    available=max(0.,equity*max_total_risk-existing_stop_risk)
    if available<=0:
        return {"status":"REJECT_PORTFOLIO_RISK_FULL"}
    stop_fraction=abs(entry-stop)/entry
    loss_fraction=stop_fraction+fees_fraction+gap_fraction
    budget=min(equity*risk_fraction,available)
    notional=min(budget/loss_fraction,equity*max_notional_multiple)
    if notional<=0:
        return {"status":"REJECT_NO_CAPACITY"}
    return {"status":"SCENARIO_ONLY_NOT_FILL_VERIFIED",
            "side":side,"stop_fraction":round(stop_fraction,8),
            "notional":round(notional,8),
            "account_exposure":round(notional/equity,8),
            "stress_loss":round(notional*loss_fraction,8),
            "total_stress_risk_after":round((existing_stop_risk+notional*loss_fraction)/equity,8)}

def self_test():
    long=authorize(100,"LONG",100,99)
    short=authorize(100,"SHORT",100,101)
    assert long["status"]=="SCENARIO_ONLY_NOT_FILL_VERIFIED"
    assert abs(long["notional"]-23.25581395)<1e-6
    assert short["notional"]==long["notional"]
    assert long["stress_loss"]==.5
    assert authorize(100,"LONG",100,99,existing_stop_risk=.8)["stress_loss"]==.2
    assert authorize(100,"LONG",100,99,existing_stop_risk=1.)["status"]=="REJECT_PORTFOLIO_RISK_FULL"
    assert authorize(100,"LONG",100,101)["status"]=="REJECT_STOP_GEOMETRY"
    assert authorize(100,"SHORT",100,99)["status"]=="REJECT_STOP_GEOMETRY"
    assert authorize(100,"LONG",100,float("nan"))["status"]=="REJECT_INVALID_NUMBER"
    assert authorize(100,"LONG",100,99,risk_fraction=.0025)["stress_loss"]==.25
    assert authorize(100,"LONG",100,99,max_notional_multiple=.1)["notional"]==10.
    assert authorize(100,"LONG",100,96.86)["notional"]<long["notional"]
    return 11

if __name__=="__main__":
    print(json.dumps({"synthetic_tests_passed":self_test(),
                      "long":authorize(100,"LONG",100,99),
                      "short":authorize(100,"SHORT",100,101),
                      "portfolio_used_0_8":authorize(100,"LONG",100,99,existing_stop_risk=.8)},indent=2))
