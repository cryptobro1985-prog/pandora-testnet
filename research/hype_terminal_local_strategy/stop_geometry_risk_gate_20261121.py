"""Research only: frozen D250 post-local stop geometry and capital-risk gate.
No detector training, orders, or inferred Bybit executions.
Run: python stop_geometry_risk_gate_20261121.py
All price distances expressed as fractions, NOT percentages.
"""
from dataclasses import dataclass
from math import isfinite

@dataclass(frozen=True)
class Candidate:
    side: str
    entry: float
    original_local: float
    atr_h1: float
    liquidation_price: float | None = None

def gate(c: Candidate, equity: float, risk_fraction: float = .005,
         adverse_cut: float = .01, structural_atr_buffer: float = .25,
         roundtrip_cost: float = .0015, gap_reserve: float = .02,
         max_total_stop_risk: float = .01):
    values = (c.entry,c.original_local,c.atr_h1,equity,risk_fraction,
              adverse_cut,structural_atr_buffer,roundtrip_cost,gap_reserve,
              max_total_stop_risk)
    if not all(isfinite(v) for v in values) or min(values[:4]) <= 0:
        raise ValueError("nonfinite/nonpositive market inputs")
    if c.side not in ("LONG","SHORT") or not 0 < risk_fraction <= max_total_stop_risk <= 1:
        raise ValueError("invalid side or risk budget")
    if not (0 < adverse_cut < 1 and structural_atr_buffer >= 0 and
            roundtrip_cost >= 0 and gap_reserve >= 0):
        raise ValueError("invalid assumptions")
    if c.side == "LONG":
        if c.original_local >= c.entry: raise ValueError("LOW must precede higher LONG entry")
        structural = c.original_local - structural_atr_buffer*c.atr_h1
        fixed = c.entry*(1-adverse_cut)
        stop = max(fixed,structural) # closer stop, per frozen baseline
        distance = (c.entry-stop)/c.entry
        liq_distance = ((c.entry-c.liquidation_price)/c.entry
                        if c.liquidation_price is not None else None)
    else:
        if c.original_local <= c.entry: raise ValueError("HIGH must precede lower SHORT entry")
        structural = c.original_local + structural_atr_buffer*c.atr_h1
        fixed = c.entry*(1+adverse_cut)
        stop = min(fixed,structural)
        distance = (stop-c.entry)/c.entry
        liq_distance = ((c.liquidation_price-c.entry)/c.entry
                        if c.liquidation_price is not None else None)
    if not 0 < distance < 1: raise ValueError("invalid stop geometry")
    if liq_distance is not None and (not isfinite(liq_distance) or
                                   liq_distance <= distance+gap_reserve):
        return {"status":"REJECT_LIQUIDATION_BUFFER","stop":stop,
                "stop_distance":distance}
    risk_per_notional = distance + roundtrip_cost + gap_reserve
    exposure = risk_fraction/risk_per_notional
    return {"status":"PAPER_ONLY_UNVERIFIED_LIQUIDATION" if liq_distance is None
            else "PAPER_ELIGIBLE",
            "side":c.side,"stop":stop,"stop_distance":distance,
            "risk_per_notional":risk_per_notional,"notional":equity*exposure,
            "exposure_equity_multiple":exposure,
            "margin_at_25x":equity*exposure/25,
            "modeled_loss_at_stop_plus_reserve":equity*risk_fraction,
            "liquidation_distance":liq_distance}

def tests():
    # Fixed 1% stop wins over wider structural stop, both sides.
    l=gate(Candidate("LONG",100,97,2,80),100)
    s=gate(Candidate("SHORT",100,103,2,120),100)
    assert abs(l["stop"]-99)<1e-9 and abs(s["stop"]-101)<1e-9
    assert abs(l["exposure_equity_multiple"]-(.005/.0315))<1e-12
    assert abs(l["exposure_equity_multiple"]-s["exposure_equity_multiple"])<1e-12
    # Structural stop can be closer than the fixed cut: this changes risk geometry.
    near=gate(Candidate("LONG",100,99.6,.4,90),100)
    assert abs(near["stop"]-99.5)<1e-9
    assert near["exposure_equity_multiple"]>l["exposure_equity_multiple"]
    assert gate(Candidate("LONG",100,97,2,98),100)["status"]=="REJECT_LIQUIDATION_BUFFER"
    assert gate(Candidate("SHORT",100,103,2,102),100)["status"]=="REJECT_LIQUIDATION_BUFFER"
    try: gate(Candidate("LONG",100,101,2),100)
    except ValueError: pass
    else: raise AssertionError("wrong-side local accepted")
    print("PASS 7 assertions; LONG and SHORT fixed stop exposure",
          round(l["exposure_equity_multiple"],8),
          "; closer structural stop exposure",
          round(near["exposure_equity_multiple"],8))
if __name__=="__main__": tests()
