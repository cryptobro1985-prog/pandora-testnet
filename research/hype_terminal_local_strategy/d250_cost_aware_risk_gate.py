#!/usr/bin/env python3
"""Research-only risk sizing gate. No orders; no assumed Bybit fee or fill values.
Inputs are observed/explicit scenario values. Fail closed on missing costs.
"""
import argparse, json, math

def size_trade(equity, risk_fraction, entry, stop, side, fee_entry, fee_exit,
               slip_entry, slip_stop, gap_stop, maintenance_margin_fraction,
               leverage_cap, free_margin, existing_stop_risk=0,
               total_risk_cap=.01):
    vals=locals()
    for k,v in vals.items():
        if k=="side": continue
        if not isinstance(v,(int,float)) or not math.isfinite(v): raise ValueError("nonfinite "+k)
    if side not in ("LONG","SHORT") or equity<=0 or entry<=0 or stop<=0 or free_margin<0:
        raise ValueError("invalid side/capital/price")
    if not (0<risk_fraction<=.005 and 0<total_risk_cap<=.01 and
            0<=existing_stop_risk<total_risk_cap and leverage_cap>=1):
        raise ValueError("risk bounds")
    for k in ("fee_entry","fee_exit","slip_entry","slip_stop","gap_stop","maintenance_margin_fraction"):
        if not 0<=vals[k]<1: raise ValueError("invalid "+k)
    if side=="LONG" and stop>=entry or side=="SHORT" and stop<=entry:
        raise ValueError("stop wrong side")
    adverse=abs(entry-stop)/entry
    cost=fee_entry+fee_exit+slip_entry+slip_stop+gap_stop
    loss_fraction=adverse+cost
    if loss_fraction<=0: raise ValueError("zero risk")
    risk_budget=equity*min(risk_fraction,total_risk_cap-existing_stop_risk)
    notional_by_stop=risk_budget/loss_fraction
    # Require adverse excursion + execution uncertainty strictly before
    # approximate liquidation buffer; this is NOT an exchange liquidation engine.
    if adverse+slip_stop+gap_stop+maintenance_margin_fraction>=1/leverage_cap:
        raise ValueError("stop not safely inside leverage liquidation buffer")
    notional=min(notional_by_stop,free_margin*leverage_cap)
    if notional<=0: raise ValueError("no available margin")
    return dict(notional=notional,initial_margin=notional/leverage_cap,
        max_modelled_loss=notional*loss_fraction,stop_risk_fraction=notional*loss_fraction/equity,
        loss_fraction_per_notional=loss_fraction,price_stop_fraction=adverse,
        cost_fraction_per_notional=cost,leverage_cap=leverage_cap,
        warning="Gap and slippage are scenario inputs, not bounded live guarantees; verify Bybit tier and mark liquidation.")

def selftest():
    kw=dict(equity=100,risk_fraction=.005,entry=100,stop=99,side="LONG",
            fee_entry=.0006,fee_exit=.0006,slip_entry=.0003,slip_stop=.0005,
            gap_stop=.002,maintenance_margin_fraction=.005,
            leverage_cap=5,free_margin=100)
    a=size_trade(**kw)
    assert abs(a["notional"]- (.5/.014))<1e-8
    assert abs(a["max_modelled_loss"]-.5)<1e-8
    b=size_trade(**dict(kw,side="SHORT",stop=101))
    assert abs(b["notional"]-a["notional"])<1e-8
    c=size_trade(**dict(kw,existing_stop_risk=.008))
    assert abs(c["max_modelled_loss"]-.2)<1e-8
    try: size_trade(**dict(kw,leverage_cap=100))
    except ValueError: pass
    else: raise AssertionError("unsafe liquidation geometry accepted")
    try: size_trade(**dict(kw,stop=101))
    except ValueError: pass
    else: raise AssertionError("wrong-side stop accepted")
    print("PASS 5 deterministic risk-gate assertions; NOT an exchange replay")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--json",help="JSON object with all explicit inputs")
    a=p.parse_args()
    if a.self_test: selftest()
    elif a.json: print(json.dumps(size_trade(**json.loads(a.json)),indent=2))
    else: p.error("--self-test or --json required")
