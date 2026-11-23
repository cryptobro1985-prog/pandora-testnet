#!/usr/bin/env python3
"""Research-only direction-exact stop loss sizing. No orders, no Bybit liquidation claims."""
import math

def size_exact(equity, risk_fraction, entry, stop, side, fee_entry, fee_exit,
               slip_entry, slip_stop, gap_stop, leverage, free_margin,
               existing_stop_risk=0.0, total_risk_cap=.01):
    values=locals()
    if any(not isinstance(v,(int,float)) or not math.isfinite(v) for k,v in values.items() if k!="side"):
        raise ValueError("nonfinite input")
    if side not in ("LONG","SHORT") or equity<=0 or entry<=0 or stop<=0 or free_margin<0 or leverage<1:
        raise ValueError("invalid capital/side/price/leverage")
    if not (0<risk_fraction<=.005 and 0<total_risk_cap<=.01 and 0<=existing_stop_risk<total_risk_cap):
        raise ValueError("risk bounds")
    if any(not 0<=v<1 for v in (fee_entry,fee_exit,slip_entry,slip_stop,gap_stop)):
        raise ValueError("invalid costs")
    if (side=="LONG" and stop>=entry) or (side=="SHORT" and stop<=entry):
        raise ValueError("stop on wrong side")
    sign=1 if side=="LONG" else -1
    actual_entry=entry*(1+sign*slip_entry)
    actual_exit=stop*(1-sign*(slip_stop+gap_stop))
    if actual_exit<=0: raise ValueError("invalid adverse fill")
    qty_loss=sign*(actual_entry-actual_exit)+fee_entry*actual_entry+fee_exit*actual_exit
    if qty_loss<=0: raise ValueError("nonpositive modeled loss")
    loss_per_entry_notional=qty_loss/actual_entry
    budget=equity*min(risk_fraction,total_risk_cap-existing_stop_risk)
    notional=min(budget/loss_per_entry_notional,free_margin*leverage)
    if notional<=0: raise ValueError("no margin")
    return dict(side=side,notional=notional,quantity=notional/actual_entry,
                actual_entry=actual_entry,adverse_exit=actual_exit,
                modeled_loss=notional*loss_per_entry_notional,
                loss_per_entry_notional=loss_per_entry_notional,
                risk_fraction=notional*loss_per_entry_notional/equity,
                initial_margin=notional/leverage,
                liquidation_status="UNVERIFIED: require exchange mark-price/tier liquidation model",
                note="Gap/slippage assumptions are scenario inputs, not guaranteed bounds.")

def selftest():
    base=dict(equity=100,risk_fraction=.005,entry=100,fee_entry=.0006,fee_exit=.0006,
              slip_entry=.0003,slip_stop=.0005,gap_stop=.01,leverage=5,free_margin=100)
    a=size_exact(**base,side="LONG",stop=99)
    b=size_exact(**base,side="SHORT",stop=101)
    assert a["notional"]>b["notional"]
    assert abs(a["modeled_loss"]-.5)<1e-10
    assert abs(b["modeled_loss"]-.5)<1e-10
    c=size_exact(**base,side="SHORT",stop=101,existing_stop_risk=.008)
    assert abs(c["modeled_loss"]-.2)<1e-10
    for change in (dict(side="LONG",stop=101),dict(side="SHORT",stop=99),dict(side="LONG",stop=99,gap_stop=float("nan"))):
        try: size_exact(**dict(base,side="LONG",stop=99,**change))
        except ValueError: pass
        else: raise AssertionError("invalid scenario accepted")
    print("PASS 6 direction-exact sizing assertions; no real execution replay")
if __name__=="__main__":
    selftest()
