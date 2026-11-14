#!/usr/bin/env python3
"""Scenario cost-floor calculation, not a historical replay. Stdlib only."""
from decimal import Decimal as D
E = D("100")
FEE = D("0.0015")  # historical modeled round-trip notional cost
for name, stop in [("Tier-A nominal 5bp",D(".0005")),("frozen 1pct cut",D(".01")),("median structural",D(".0314"))]:
    for slip in [D("0"),D(".005"),D(".01")]:
        unit=stop+FEE+slip
        print(name, "slippage_pct",slip*100,
              "notional_r025",round(E*D(".0025")/unit,4),
              "notional_r050",round(E*D(".005")/unit,4),
              "loss_5x_equity_pct",round(D("5")*unit*100,4))
