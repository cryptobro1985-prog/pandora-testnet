"""Research-only independent risk/equity authorization. No detector or order changes."""
from math import isfinite

def authorize(equity, entry, stop, side, fee_fraction, gap_fraction,
              funding_reserve_fraction, risk_fraction, prior_open_stop_risk=0.0,
              max_total_risk_fraction=0.01):
    vals=(equity,entry,stop,fee_fraction,gap_fraction,funding_reserve_fraction,
          risk_fraction,prior_open_stop_risk,max_total_risk_fraction)
    if not all(isinstance(v,(int,float)) and isfinite(v) for v in vals):
        return {"status":"BLOCKED_NONFINITE"}
    if equity<=0 or entry<=0 or stop<=0 or side not in ("LONG","SHORT"):
        return {"status":"BLOCKED_GEOMETRY"}
    if (side=="LONG" and stop>=entry) or (side=="SHORT" and stop<=entry):
        return {"status":"BLOCKED_WRONG_SIDE_STOP"}
    if min(fee_fraction,gap_fraction,funding_reserve_fraction,prior_open_stop_risk)<0:
        return {"status":"BLOCKED_NEGATIVE_RESERVE"}
    if not (0<risk_fraction<=.005 and 0<max_total_risk_fraction<=.01):
        return {"status":"BLOCKED_RISK_LIMIT"}
    stop_distance=abs(stop-entry)/entry
    stressed_loss_fraction=stop_distance+fee_fraction+gap_fraction+funding_reserve_fraction
    remaining=max_total_risk_fraction*equity-prior_open_stop_risk
    budget=min(risk_fraction*equity,remaining)
    if budget<=0: return {"status":"BLOCKED_PORTFOLIO_RISK"}
    notional=budget/stressed_loss_fraction
    return {"status":"SCENARIO_AUTHORIZED_NOT_EXECUTION_VERIFIED",
            "notional":notional,"stressed_loss_usd":notional*stressed_loss_fraction,
            "stop_distance_fraction":stop_distance,"budget_usd":budget,
            "required_inputs_not_checked":["mark_price_tape","maintenance_margin_tiers",
              "actual_fills","funding_tape","L50_depth","causal_local_confirmation"]}

def reconcile_authorization(trades,start_equity=100.):
    """Reject caller-supplied equity drift; returns no simulated performance."""
    if not isinstance(trades,(list,tuple)) or not trades: return {"status":"BLOCKED_NO_TRADES"}
    equity=float(start_equity); prev_exit=None
    for i,t in enumerate(trades):
        try:
            if prev_exit is not None and int(t["entry_ts_ms"])<prev_exit:
                return {"status":"BLOCKED_OVERLAP","index":i}
            if int(t["exit_ts_ms"])<=int(t["entry_ts_ms"]):
                return {"status":"BLOCKED_TIME","index":i}
            prev_exit=int(t["exit_ts_ms"])
            if abs(float(t["entry_equity"])-equity)>max(1e-8,equity*1e-8):
                return {"status":"BLOCKED_EQUITY_DRIFT","index":i}
            a=authorize(equity,float(t["entry_price"]),float(t["stop_price"]),
              t["side"],float(t["fee_fraction"]),float(t["gap_fraction"]),
              float(t["funding_reserve_fraction"]),float(t["risk_fraction"]),
              float(t.get("prior_open_stop_risk",0)))
            if not a["status"].startswith("SCENARIO_"):
                return {"status":a["status"],"index":i}
            if float(t["authorized_notional"])>a["notional"]*(1+1e-8):
                return {"status":"BLOCKED_NOTIONAL_OVER_BUDGET","index":i}
            gross=float(t["underlying_return_fraction"])
            actual_funding=float(t["funding_fraction"])
            actual_fee=float(t["actual_roundtrip_fee_fraction"])
            if not all(isfinite(x) for x in (gross,actual_funding,actual_fee)) or actual_fee<0:
                return {"status":"BLOCKED_ECONOMICS","index":i}
            equity+=float(t["authorized_notional"])*(gross-actual_fee-actual_funding)
            if equity<=0:return {"status":"BLOCKED_INSOLVENT","index":i}
        except (KeyError,ValueError,TypeError,OverflowError):
            return {"status":"BLOCKED_MISSING_OR_INVALID","index":i}
    return {"status":"SCENARIO_RECONCILED_CLOSED_ONLY","end_equity":equity,
            "mtm_dd":None,"liquidations":None,"mfe":None}

def self_test():
    kw=dict(equity=100.,entry=100.,stop=99.,side="LONG",fee_fraction=.0015,
            gap_fraction=.02,funding_reserve_fraction=0.,risk_fraction=.005)
    a=authorize(**kw)
    assert abs(a["notional"]-15.873015873)<1e-6
    assert authorize(**{**kw,"side":"SHORT"})["status"]=="BLOCKED_WRONG_SIDE_STOP"
    assert authorize(**{**kw,"prior_open_stop_risk":.9})["status"].startswith("SCENARIO_")
    assert abs(authorize(**{**kw,"prior_open_stop_risk":.9})["budget_usd"]-.1)<1e-9
    assert authorize(**{**kw,"prior_open_stop_risk":1.})["status"]=="BLOCKED_PORTFOLIO_RISK"
    base=dict(entry_ts_ms=1,exit_ts_ms=2,entry_equity=100.,entry_price=100.,
      stop_price=99.,side="LONG",fee_fraction=.0015,gap_fraction=.02,
      funding_reserve_fraction=0.,risk_fraction=.005,authorized_notional=10.,
      underlying_return_fraction=.01,funding_fraction=0.,
      actual_roundtrip_fee_fraction=.0015)
    assert reconcile_authorization([base,{**base,"entry_ts_ms":3,"exit_ts_ms":4,
      "entry_equity":100.}])["status"]=="BLOCKED_EQUITY_DRIFT"
    assert reconcile_authorization([base])["status"]=="SCENARIO_RECONCILED_CLOSED_ONLY"
    return 7

if __name__=="__main__":print({"tests_passed":self_test()})
