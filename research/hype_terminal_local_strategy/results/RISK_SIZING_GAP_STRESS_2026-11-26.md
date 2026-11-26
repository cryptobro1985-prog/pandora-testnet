# Risk sizing stress arithmetic — 2026-11-26

Not a replay; no trade paths available in this input. Source blob be76b9a61c86ec59c94b885eea4b15ee97cc1c05. Frozen D250 unchanged. Fixed stop 1%, original round-trip cost 0.15%; additional gap scenarios are hypothetical, not measured. Funding excluded because unknown. Exposure = risk/(stop+cost+gap); margin fraction = exposure/25. Six consecutive full-budget losses are a scenario, not measured DD. Last column tests a 1% extra gap regardless of sizing assumption. No liquidation inference or forward result.

```json
[
  {
    "risk": 0.0025,
    "gap": 0,
    "exposure": 0.2173913043478261,
    "margin_at_25x": 0.008695652173913044,
    "six_full_losses_dd": 0.014906561914647898,
    "loss_if_gap_1pct": 0.004673913043478261
  },
  {
    "risk": 0.0025,
    "gap": 0.0025,
    "exposure": 0.17857142857142858,
    "margin_at_25x": 0.007142857142857143,
    "six_full_losses_dd": 0.014906561914647898,
    "loss_if_gap_1pct": 0.003839285714285714
  },
  {
    "risk": 0.0025,
    "gap": 0.005,
    "exposure": 0.15151515151515152,
    "margin_at_25x": 0.006060606060606061,
    "six_full_losses_dd": 0.014906561914647898,
    "loss_if_gap_1pct": 0.0032575757575757573
  },
  {
    "risk": 0.0025,
    "gap": 0.01,
    "exposure": 0.11627906976744187,
    "margin_at_25x": 0.004651162790697675,
    "six_full_losses_dd": 0.014906561914647898,
    "loss_if_gap_1pct": 0.0025
  },
  {
    "risk": 0.005,
    "gap": 0,
    "exposure": 0.4347826086956522,
    "margin_at_25x": 0.017391304347826087,
    "six_full_losses_dd": 0.029627490643734378,
    "loss_if_gap_1pct": 0.009347826086956522
  },
  {
    "risk": 0.005,
    "gap": 0.0025,
    "exposure": 0.35714285714285715,
    "margin_at_25x": 0.014285714285714285,
    "six_full_losses_dd": 0.029627490643734378,
    "loss_if_gap_1pct": 0.007678571428571428
  },
  {
    "risk": 0.005,
    "gap": 0.005,
    "exposure": 0.30303030303030304,
    "margin_at_25x": 0.012121212121212121,
    "six_full_losses_dd": 0.029627490643734378,
    "loss_if_gap_1pct": 0.006515151515151515
  },
  {
    "risk": 0.005,
    "gap": 0.01,
    "exposure": 0.23255813953488375,
    "margin_at_25x": 0.00930232558139535,
    "six_full_losses_dd": 0.029627490643734378,
    "loss_if_gap_1pct": 0.005
  },
  {
    "risk": 0.01,
    "gap": 0,
    "exposure": 0.8695652173913044,
    "margin_at_25x": 0.034782608695652174,
    "six_full_losses_dd": 0.058519850599,
    "loss_if_gap_1pct": 0.018695652173913044
  },
  {
    "risk": 0.01,
    "gap": 0.0025,
    "exposure": 0.7142857142857143,
    "margin_at_25x": 0.02857142857142857,
    "six_full_losses_dd": 0.058519850599,
    "loss_if_gap_1pct": 0.015357142857142856
  },
  {
    "risk": 0.01,
    "gap": 0.005,
    "exposure": 0.6060606060606061,
    "margin_at_25x": 0.024242424242424242,
    "six_full_losses_dd": 0.058519850599,
    "loss_if_gap_1pct": 0.01303030303030303
  },
  {
    "risk": 0.01,
    "gap": 0.01,
    "exposure": 0.4651162790697675,
    "margin_at_25x": 0.0186046511627907,
    "six_full_losses_dd": 0.058519850599,
    "loss_if_gap_1pct": 0.01
  }
]
```
