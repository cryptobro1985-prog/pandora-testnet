"""Research-only sizing and stress calculations; no orders or inferred fills.
Usage: python stop_risk_budget_replay_20261116.py
All costs and gaps are explicit scenarios, not observed Bybit executions.
"""
from math import isfinite

def size(equity, entry, stop, side, risk_fraction, fee_roundtrip=0.0015,
         funding_reserve=0.0006, gap_reserve=0.01, max_notional_multiple=1.0):
    assert side in ("LONG", "SHORT")
    assert equity > 0 and entry > 0 and stop > 0
    assert 0 < risk_fraction <= 0.005
    assert (stop < entry if side == "LONG" else stop > entry)
    assert all(isfinite(x) for x in (equity, entry, stop, risk_fraction, fee_roundtrip, funding_reserve, gap_reserve))
    assert min(fee_roundtrip, funding_reserve, gap_reserve) >= 0
    distance = abs(entry-stop)/entry
    unit_loss = distance + fee_roundtrip + funding_reserve + gap_reserve
    notional = min(equity*risk_fraction/unit_loss, equity*max_notional_multiple)
    return {"notional":notional, "quantity":notional/entry,
            "stop_distance_pct":100*distance,
            "budgeted_loss":notional*unit_loss,
            "budgeted_equity_risk_pct":100*notional*unit_loss/equity,
            "unit_loss_with_gap_reserve":unit_loss}

def stress(equity, entry, stop, side, risk_fraction, realized_gap, **kwargs):
    s=size(equity,entry,stop,side,risk_fraction,**kwargs)
    actual_loss=s["notional"]*(abs(entry-stop)/entry + kwargs.get("fee_roundtrip",0.0015)
              + kwargs.get("funding_reserve",0.0006) + realized_gap)
    return {**s,"scenario_gap_pct":realized_gap*100,
            "scenario_loss_pct_equity":100*actual_loss/equity,
            "breaches_budget":actual_loss>equity*risk_fraction+1e-10}

if __name__=="__main__":
    for side,stop in (("LONG",99),("SHORT",101)):
        a=size(100,100,stop,side,0.005)
        assert abs(a["notional"]-22.62443438914027)<1e-8
        assert abs(a["budgeted_loss"]-0.5)<1e-10
        b=stress(100,100,stop,side,0.005,0.05)
        assert b["breaches_budget"]
        print(side, "notional",round(a["notional"],4),
              "5pct_gap_loss_equity_pct",round(b["scenario_loss_pct_equity"],4))
    # Two concurrent positions each 0.5% risk consume full 1% portfolio stop budget.
    assert 2*0.005 <= 0.01
    print("PASS: symmetric sizing and explicit gap-budget breach; synthetic only")
