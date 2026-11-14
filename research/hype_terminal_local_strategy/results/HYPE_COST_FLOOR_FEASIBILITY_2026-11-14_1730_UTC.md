# HYPE cost-floor feasibility audit — 2026-11-14 17:30 UTC

Research only. Existing D250 detector frozen. No orders, production changes, new branches, or exit-overlay promotion.

## New calculation, grounded in frozen research
Read directly from this branch:
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`: D250 71 accepted first signals; 67 completed opposite-local paths; diagnostic structural stop median 3.14%; frozen 1% adverse-cut alternative belongs to separate audit.
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`: round-trip fee model 0.15% of notional; 5x exposure; 67 completed trades, 22 adverse cuts.
- `results/HYPE_EVERY_LOCAL_ROBUST_STRATEGY_2026-11-12.md`: Tier A stop 5 basis points beyond candidate extreme, 5x maximum account exposure, 7% nominal risk budget, and distinct 411-trade population.
- `results/HYPE_COMPACT_REPORT_REPLAY_ELIGIBILITY_2026-11-14_1634_UTC.md`: sampled compact reports lack executable trade tape.

For an adverse price move `d`, assumed total round-trip fee fraction `f=0.0015`, and incremental stop execution slippage fraction `s`, modeled worst loss per notional = `d+f+s`. Risk-budget notional upper bound = `equity*risk_fraction/(d+f+s)`. This is a **scenario sizing bound, not a guaranteed stop loss**; no liquidation, funding, order-book depth or real fills are inferred.

### Reproducible deterministic calculation ($100 equity)
| Stop distance | Extra stop slippage | 0.25% equity risk notional | 0.50% equity risk notional | Loss at 5x equity exposure |
|---|---:|---:|---:|---:|
| Tier-A nominal 0.05% | 0% | $125.00 | $250.00 | 1.00% |
| Tier-A nominal 0.05% | 0.5% | $35.71 | $71.43 | 3.50% |
| Tier-A nominal 0.05% | 1.0% | $20.83 | $41.67 | 6.00% |
| Frozen adverse cut 1.0% | 0% | $21.74 | $43.48 | 5.75% |
| Frozen adverse cut 1.0% | 0.5% | $15.15 | $30.30 | 8.25% |
| Frozen adverse cut 1.0% | 1.0% | $11.63 | $23.26 | 10.75% |
| Median diagnostic structural 3.14% | 0% | $7.60 | $15.20 | 16.45% |
| Median diagnostic structural 3.14% | 1.0% | $5.83 | $11.66 | 21.45% |

### New consequential finding
At 5x account exposure, the **0.15% round-trip fee assumption alone costs 0.75% of equity**, exceeding the entire 0.25–0.5% per-trade loss budget before any adverse price move. Therefore neither the 5x frozen adverse-cut simulation nor the 5x Tier-A 5-bp-stop all-local simulation is compatible with the requested conservative risk budget without changing notional. The 7% Tier-A nominal risk budget is also incompatible with the new mandate. This is a policy feasibility finding, not evidence of inferior trading alpha.

A 5-bp stop with 0.5% execution slippage implies 3.5% equity loss at 5x despite a nominal 0.25% equity price move. Small stop distance is not a reliable proxy for small realized risk. Fees are modeled as 0.15% round trip because that is the frozen report's assumption, **not verified Bybit fees**. Stop distance measured from candidate extreme is not necessarily 5 bps from actual entry; Tier-A row is an illustrative best-case entry-to-stop geometry, not an observed Tier-A trade.

## Decision
Keep original baselines unchanged for historical comparability, but mark 5x sizing as **not eligible** for a 0.25–0.5% risk-budget forward candidate. Do not retrofit risk-adjusted PnL to the 67/411 trades from aggregate reports; need chronological event ledger, actual entry-to-stop distances, gap/slippage, margin/liquidation state, fees/funding, all four censored signals, and event-time mark-to-market. No new net equity, fill, liquidation or MFE claims. Preserve rejected MFI-flow, ATR trail, K0/K1 and simple pyramiding overlays as rejected.

## Reproduce
Run `python research/hype_terminal_local_strategy/cost_floor_feasibility_20261114.py` (stdlib only). Output prints every stress case. Independent forward must be genuinely later than the already examined May–Nov periods; freeze settings before observing it.
