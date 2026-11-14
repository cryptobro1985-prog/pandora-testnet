# HYPE conservative funding-inclusive risk-budget sensitivity — 2026-11-14 20:32 UTC

Research-only incremental calculation. **Not an execution replay**, not a new entry detector, not a performance improvement claim.

## Source checks
Read original frozen D250 walk-forward, asymmetric 67-trade audit, unified causal entry/MFE contract, and existing cost/OHLC scenario scripts directly from this branch. D250 is 250 minutes after candidate, 71 accepted and only 67 completed opposite locals; late-Aug opposite-local exit mean -0.727% price, 27.27% win rate. The original 67-trade 5x modeled final equity is **$1,308.86**, while **$531.16 is the 3x result**. Both are closed-equity simulation, not event-matched fills. Earlier summaries that imply $531.16 at 5x are incorrect.

## New independent risk-budget sensitivity
Reproducible script: `research/hype_terminal_local_strategy/funding_inclusive_risk_budget_20261114.py`.
Assumptions for BOTH LOW->LONG and HIGH->SHORT: $100 equity; frozen 1% adverse-price cut; 0.15% modeled round-trip fee; **0.06% adverse funding reserve** (hypothetical, not observed Bybit funding); slippage stress as shown. Nominal = equity × stop-risk fraction / (stop distance + fee + slippage + funding reserve). The funding reserve is a conservative scenario parameter, not a statement of historical rates.

| Stop-risk budget | Extra stop slippage | Max nominal | Equity exposure |
|---|---:|---:|---:|
| 0.25% | 0.5% | $14.62 | 14.62% |
| 0.25% | 1% | $11.31 | 11.31% |
| 0.25% | 2.5% | $6.74 | 6.74% |
| 0.5% | 0.5% | $29.24 | 29.24% |
| 0.5% | 1% | $22.62 | 22.62% |
| 0.5% | 2.5% | $13.48 | 13.48% |

These are **symmetric scenario caps**, NOT evidence that actual LONG/SHORT execution distributions are equal. A 5x equity exposure with 1% stop and 0.15% fees consumes at least 5.75% equity at modeled stop even before slippage/funding, violating the 0.5% trade budget. Actual exchange leverage, maintenance tiers, liquidation buffer, stop order lifecycle, mark-price triggers and available margin still require source evidence. A gap can exceed the modeled stress and break the cap.

## Evidence gap / required next replay
GitHub default-branch code search for rich HYPE Public Trades artifacts returned no matches; it does **not** establish absence on this research branch or GitHub Actions. Must obtain 71 immutable entry timestamps (67 finalized, 4 right-censored), and event-level historical Public Trades/mark/book plus funding before estimating actual fill distribution. Reconstruct chronological equity with reserved capital, fees, funding, intratrade MTM DD and side-specific stop gaps. Compare frozen 1% cut/causal opposite-local baseline and 0.25%-0.5% sizing on exactly the same trades, then staged entry/profit lock only as unpromoted challengers; previously rejected overlays remain rejected. Do not treat future opposite extreme as an executable exit.

No production edits, live orders, threshold fitting, or detector retraining.
