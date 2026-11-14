"""Research-only LONG/SHORT stop-gap stress; no market fills or orders. Stdlib."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Case:
    side: str
    entry: float
    stop: float
    fill: float

def loss_fraction(c):
    assert c.side in ("LONG", "SHORT")
    assert c.entry > 0 and c.stop > 0 and c.fill > 0
    assert (c.stop < c.entry if c.side == "LONG" else c.stop > c.entry)
    adverse = (c.entry - c.fill) / c.entry if c.side == "LONG" else (c.fill - c.entry) / c.entry
    return max(0., adverse)

def nominal(equity, risk_pct, adverse_fraction, fee_fraction):
    assert equity > 0 and 0 < risk_pct <= 1 and adverse_fraction >= 0 and fee_fraction >= 0
    return equity * risk_pct / (adverse_fraction + fee_fraction)

def main():
    equity, budget, fees = 100., .005, .0015
    assumed = .01 + .01 + fees
    fixed_nominal = equity * budget / assumed
    cases = [
        Case("LONG", 100, 99, 98.5),
        Case("SHORT", 100, 101, 102),
        Case("LONG", 100, 99, 95),
        Case("SHORT", 100, 101, 105),
    ]
    for c in cases:
        adverse = loss_fraction(c)
        actual_loss = fixed_nominal * (adverse + fees)
        safe_nominal = nominal(equity, budget, adverse, fees)
        print(c.side, "fill", c.fill, "adverse_pct", round(adverse*100, 3),
              "loss_at_fixed_nominal_usd", round(actual_loss, 6),
              "budget_safe_nominal_usd", round(safe_nominal, 6))
    assert abs(fixed_nominal - 23.25581395348837) < 1e-8
    assert abs(nominal(100, .005, .05, .0015) - 9.70873786407767) < 1e-8
    assert fixed_nominal*(.05+.0015) > 1.0
    assert loss_fraction(Case("SHORT",100,101,105)) == loss_fraction(Case("LONG",100,99,95))
    print("PASS 4 deterministic checks; hypothetical stress only")

if __name__ == "__main__":
    main()
