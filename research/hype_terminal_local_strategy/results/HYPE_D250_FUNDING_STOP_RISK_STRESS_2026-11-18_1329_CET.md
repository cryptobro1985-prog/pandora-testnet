# HYPE D250 — funding-aware stop-risk and minimum executable evidence (2026-11-18 13:29 CET)

Research only; no new detector, no live orders, no production changes. This is a **new deterministic stress calculation, not historical replay**. Sources inspected on the target branch: H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md (blob 5486547...), HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md (blob be76b9a...), HYPE_D250_AGGREGATE_IDENTIFIABILITY_2026-11-18_1228_CET.md (blob 71f7216...). Frozen entry and rejected MFE overlays remain unchanged.

## Newly isolated risk error: funding omitted from stop-risk sizing

Previous conservative notional cap used price stop 1%, round-trip execution fees 0.15% of notional and adverse stop gap/slippage reserve 0.50%, i.e. 1.65% of notional. But D250 opposite-local exits have **median holding time 7.43 hours**, and funding may be paid across funding timestamps; the median hold does not determine actual payments. If funding is adverse, it consumes the SAME stop-risk budget, not an additional budget. Funding values below are **hypothetical cumulative adverse fractions of notional**, not measured Bybit rates. If funding is favorable, do not pre-credit it for protective sizing.

| Cumulative adverse funding / notional | Modeled loss / notional | Max notional/equity at 0.25% risk | Max notional/equity at 0.50% risk | Loss at historical 5x exposure |
|---:|---:|---:|---:|---:|
| 0.00% | 1.65% | 0.1515x | 0.3030x | 8.25% |
| 0.01% | 1.66% | 0.1506x | 0.3012x | 8.30% |
| 0.03% | 1.68% | 0.1488x | 0.2976x | 8.40% |
| 0.09% | 1.74% | 0.1437x | 0.2874x | 8.70% |

The 1% stop is a price-level exit assumption; market gaps can exceed the 0.50% reserve, so even this funded sizing does **not** guarantee the 0.25%-0.50% loss ceiling. A stop-market order may fill beyond trigger; liquidation must be tested with venue-specific maintenance tiers, mark-price path and margin mode. No actual liquidation count is inferred.

## New causal replay acceptance distinction

LOW→LONG and HIGH→SHORT need separate UTC evidence: original strict-H1 extreme, pivot availability/confirmation, D250 feature-window end, same-side invalidation, bid/ask order submission and fills, stop trigger and fill, funding timestamps, maintenance-margin tier, intratrade mark-price extrema and opposite-H1 local **confirmation** (not oracle extreme). For profit protection, compute sustained price-impact efficiency and control-transfer only from data available by each exit decision; previously rejected overlays remain rejected. If funding events or L50 depth are absent, mark their contribution UNKNOWN and do not fabricate zeroes. Replay variants must share the identical ordered signals, fill-cost assumptions, capital constraints and funding ledger.

## Interpretation

This is a quantified risk-budget correction, not evidence that the entry/exit strategy is profitable after executable fills. The historical 67-trade UTC ledger, synchronized Public Trades/L50/mark-price and funding tape remain unverified in this run; consequently no new monthly equity, MTM DD, net PnL, realized fill rate, liquidation count or MFE capture is claimed. May 2026 is historical holdout, not prospective forward.
