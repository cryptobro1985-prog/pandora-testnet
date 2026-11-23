#!/usr/bin/env python3
"""Research-only post-sizing quantity gate; exchange filters must be supplied, never assumed."""
from decimal import Decimal, ROUND_DOWN
def check(s, step, min_qty, min_notional, equity, free_margin, leverage, fee_entry, risk_cap):
    D=lambda v:Decimal(str(v))
    step=D(step)
    if step<=0: raise ValueError("step")
    q=(D(s["quantity"])/step).to_integral_value(rounding=ROUND_DOWN)*step
    if q<=0:return {"status":"REJECT_ZERO_AFTER_ROUNDING"}
    entry=D(s["actual_entry"]); out=D(s["adverse_exit"])
    if q<D(min_qty) or q*entry<D(min_notional):return {"status":"REJECT_MIN_ORDER"}
    if s["side"] not in ("LONG","SHORT"):raise ValueError("side")
    sign=1 if s["side"]=="LONG" else -1
    loss=q*(D(sign)*(entry-out)+D(fee_entry)*entry+D(s["fee_exit"])*out)
    cash=q*entry*(1/D(leverage)+D(fee_entry))
    if cash>D(free_margin):return {"status":"REJECT_MARGIN"}
    if loss>D(equity)*D(risk_cap):return {"status":"REJECT_RISK"}
    return {"status":"SIZE_FEASIBLE_LIQUIDATION_UNVERIFIED","quantity":str(q),"modeled_loss":str(loss),"entry_cash":str(cash)}
def selftest():
    s=dict(quantity=.00499,actual_entry=100,adverse_exit=98,fee_exit=.0006,side="LONG")
    f=lambda **kw:check(kw.pop("s",s),kw.pop("step",.001),kw.pop("min_qty",.001),kw.pop("min_notional",.1),kw.pop("equity",100),kw.pop("free_margin",100),kw.pop("leverage",5),kw.pop("fee_entry",.0006),kw.pop("risk_cap",.005))
    assert f()["quantity"]=="0.004"
    assert f(step=.01)["status"]=="REJECT_ZERO_AFTER_ROUNDING"
    assert f(min_qty=.01)["status"]=="REJECT_MIN_ORDER"
    assert f(min_notional=1)["status"]=="REJECT_MIN_ORDER"
    assert f(free_margin=.01)["status"]=="REJECT_MARGIN"
    assert f(s=dict(s,quantity=.1),equity=1)["status"]=="REJECT_RISK"
    assert f(s=dict(s,side="SHORT",adverse_exit=102))["status"]=="SIZE_FEASIBLE_LIQUIDATION_UNVERIFIED"
    print("PASS 7 synthetic precision/constraints checks; no exchange replay")
if __name__=="__main__":selftest()
