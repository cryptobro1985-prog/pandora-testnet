# HYPE post-local risk-gap stress grid — 2026-11-16 07:32 CET

Research-only deterministic extension of `stop_risk_budget_replay_20261116.py`. No actual fills, no new detector training, no production orders. Uses $100 equity, 0.15% roundtrip fees + 0.06% funding reserve, 1% sizing gap reserve. Notional = equity * risk_fraction / (stop_distance + 0.0015 + 0.0006 + 0.01). Scenario loss = notional * (stop_distance + 0.0015 + 0.0006 + realized_gap). Symmetric arithmetic for LONG and SHORT, **not** evidence their actual fill/slippage distributions are symmetric.

|Stop %|Risk budget %|Notional $|Realized gap %|Scenario loss % equity|Exceeds risk budget|
|---:|---:|---:|---:|---:|:---:|
|1.00|0.25|11.3122|0|0.1369|NO|
|1.00|0.25|11.3122|1|0.2500|NO|
|1.00|0.25|11.3122|2|0.3631|YES|
|1.00|0.25|11.3122|5|0.7025|YES|
|1.00|0.50|22.6244|0|0.2738|NO|
|1.00|0.50|22.6244|1|0.5000|NO|
|1.00|0.50|22.6244|2|0.7262|YES|
|1.00|0.50|22.6244|5|1.4050|YES|
|3.14|0.25|5.7471|0|0.1925|NO|
|3.14|0.25|5.7471|1|0.2500|NO|
|3.14|0.25|5.7471|2|0.3075|YES|
|3.14|0.25|5.7471|5|0.4799|YES|
|3.14|0.50|11.4943|0|0.3851|NO|
|3.14|0.50|11.4943|1|0.5000|NO|
|3.14|0.50|11.4943|2|0.6149|YES|
|3.14|0.50|11.4943|5|0.9598|YES|

## Interpretation and audit gates

- A nominal 0.5% stop-risk budget is **conditional** on a 1% or smaller realized gap in this stress model; at a 5% realized gap it can be exceeded substantially. Stops are not guaranteed fills. At 25x instrument leverage, $22.6244 notional requires ~$0.905 margin before fees; liquidation proximity requires actual maintenance-margin tiers, mark prices, and position/cross-margin state, not a simplistic 1/25 threshold.
- A 3.14% structural stop reduces notional versus 1%, but does not establish better expected return. This is a scenario parameter, not an observed universal stop distance.
- Do not promote this grid to strategy PnL. No per-trade timestamps, event-level Bybit L50/trades, mark-price liquidation trajectories, funding records, or actual fills were joined in this iteration. Thus monthly net equity, MTM DD, MFE capture, liquidations and unseen forward are **NOT VERIFIED**.
- Next concrete replay gate: require episode ID, side, terminal-local confirmation timestamp, order-ready timestamp, first available bid/ask/trade, stop order acknowledgment timestamp, stop trigger basis, position margin mode, and contiguous event coverage; reject unprotected entry and unresolved intrabar order. Then run frozen baseline and alternatives on identical chronological episodes with no reused overlapping capital.
- Frozen D250 thresholds unchanged: rev_atr>2.084004943, trade_ratio5>0.2727842248, side-normalized flow15<0.45047316. Previously rejected profit-protection overlays remain rejected.

## Reproduce

Run `python research/hype_terminal_local_strategy/stop_risk_budget_replay_20261116.py` and evaluate the two formulas above over stop_distance in [0.01, 0.0314], risk_fraction in [0.0025, 0.005], realized_gap in [0, 0.01, 0.02, 0.05]. All figures are rounded to four decimal places. No market data were inferred.
