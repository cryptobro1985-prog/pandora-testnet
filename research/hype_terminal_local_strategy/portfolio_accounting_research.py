"""PAPER ONLY: chronological non-overlapping HYPE post-local portfolio accounting.
Input trades are independently reconstructed causal execution events, NOT hindsight labels.
All returns are fractions of entry equity. No real orders.
"""
from datetime import datetime, timezone
from math import isfinite

def evaluate(trades, start_equity=100.0):
    if not isfinite(start_equity) or start_equity <= 0: raise ValueError("bad capital")
    equity=float(start_equity); peak=equity; max_dd=0.0
    prev_exit=None; monthly={}; by_side={"LONG":[],"SHORT":[]}; equity_path=[]
    for t in trades:
        entry=int(t["entry_ts_ms"]); exit_=int(t["exit_ts_ms"])
        if exit_<=entry or (prev_exit is not None and entry<prev_exit):
            raise ValueError("overlap or noncausal timestamps")
        prev_exit=exit_
        side=t["side"]
        if side not in by_side: raise ValueError("invalid side")
        gross=float(t["underlying_return_fraction"])
        exposure=float(t["account_exposure"])
        costs=float(t["roundtrip_cost_fraction"])
        funding=float(t.get("funding_fraction",0.0))
        if any(not isfinite(x) for x in (gross,exposure,costs,funding)) or exposure<0 or costs<0:
            raise ValueError("invalid economics")
        # underlying_return_fraction is signed in the position's direction
        r=exposure*(gross-costs-funding)
        if r<=-1: raise ValueError("insolvent trade: do not compound through liquidation")
        equity*=1+r; peak=max(peak,equity); max_dd=max(max_dd,1-equity/peak)
        month=datetime.fromtimestamp(exit_/1000,timezone.utc).strftime("%Y-%m")
        m=monthly.setdefault(month,{"trades":0,"first_equity":equity/(1+r),"last_equity":equity,"wins":0})
        m["trades"]+=1; m["last_equity"]=equity; m["wins"]+=r>0
        by_side[side].append(r)
        equity_path.append({"ts_ms":exit_,"equity":equity,"closed_drawdown_fraction":1-equity/peak})
    return {"start_equity":start_equity,"end_equity":equity,
            "max_closed_drawdown_fraction":max_dd,"monthly":monthly,
            "by_side":{k:{"trades":len(v),"mean_equity_return":sum(v)/len(v) if v else None} for k,v in by_side.items()},
            "closed_equity_path":equity_path,
            "limitations":"No mark-to-market DD, actual fills, liquidation, funding verification, or MFE without full event tape."}
