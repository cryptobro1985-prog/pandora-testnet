# D250 aggregate-only conservative sizing bounds — 2026-11-24
Source: HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md, blob be76b9a61c86ec59c94b885eea4b15ee97cc1c05.
67 sequential trades, 33 positive (49.25%), 34 nonpositive, mean positive equity return 0.1416, mean losing magnitude 0.0437, worst 0.0575 at 5x exposure. No new execution assumptions. Scale all original net returns linearly by k=r/0.0575; fixed exposure 5k, not structural risk sizing. For positive returns product >= 1+sum; for losses log(1-k*x) >= x/0.0575 * log(1-r) on [0,0.0575]. Jensen gives upper bound for each group. Thus approximate aggregate-only terminal equity bounds (rounded source statistics, not exact replay or forward forecast):
```json
[
  {
    "risk": 0.0025,
    "exposure": 0.21739130434782608,
    "lower": 112.7806821124562,
    "upper": 114.78388678759599,
    "sixLossDD": 0.014906561914647898
  },
  {
    "risk": 0.005,
    "exposure": 0.43478260869565216,
    "lower": 123.54801780880526,
    "upper": 131.57450668115095,
    "sixLossDD": 0.029627490643734378
  }
]
```
Reproduce: lower=100*(1+33*0.1416*k)*exp(34*0.0437/0.0575*log(1-r)); upper=100*(1+0.1416*k)^33*(1-0.0437*k)^34. Six consecutive worst losses stress=1-(1-r)^6, not maximum DD. Assumes same fills, linear costs, no minimum order constraints, no gaps beyond original model. No monthly or MTM inference; no liquidation claim. No detector or overlay changes. Individual trade ledger still required.