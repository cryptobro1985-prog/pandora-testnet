# D250 execution economics: gap-reserve sensitivity (2026-11-20 13:32 CET)

Research only; frozen entry and rejected exit overlays unchanged. This is an analytical stress comparison, **not** an event replay or a performance estimate.

## Source evidence checked
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md: D250, 71/71 accepted historical first signals, 67 finalized opposite locals, median causal exit MFE giveback 61.2%, median structural stop 3.14% and worst observed MAE -1.958% (historical geometry, not fills).
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md: 67 sequential simulated trades, 22 1% cuts, 0.15% assumed round-trip fee, 3x/5x exposure; no execution-grade replay.
- independent_risk_reconciliation_20261120.py: risk budget denominator = stop fraction + fee fraction + gap fraction + funding reserve.

## New quantitative sensitivity: $100 equity, 0.5% risk, 1% adverse stop, 0.15% round-trip fee, zero *illustrative* funding reserve
| Assumed adverse gap reserve | Nominal allowed | Equity exposure | Model loss at stop with NO gap | Model loss with full reserved gap |
|---:|---:|---:|---:|---:|
| 0% | $43.48 | 0.4348x | $0.5000 | $0.5000 |
| 0.5% | $30.30 | 0.3030x | $0.3485 | $0.5000 |
| 1% | $23.26 | 0.2326x | $0.2674 | $0.5000 |
| 2% | $15.87 | 0.1587x | $0.1825 | $0.5000 |
| 5% | $8.13 | 0.0813x | $0.0935 | $0.5000 |

Calculations: N = 0.50/(0.01+0.0015+g); no-gap stop loss = N*(0.0115); reserved-gap loss = N*(0.0115+g). All values rounded.

**Finding:** at the 2% reserve, only 36.5% of the planned $0.50 loss budget is consumed by a no-gap 1% stop; 63.5% is reserved for uncertain execution. This is a meaningful exposure-vs-robustness tradeoff, not an improvement in predictive edge. A gap larger than the reserve still exceeds the risk budget. At $100, minimum exchange quantity/notional constraints may prevent placing these nominal positions at all. This must be checked against dated Bybit instrument metadata, not assumed.

## Strict next replay requirements
1. Recover the exact 67 signal timestamps, entry prices, sides, causal confirmation timestamps and next opposite-local availability timestamps; hash input manifests.
2. Match each signal with real UTC bid/ask/L50, Mark Price, public trades, funding intervals, and actual fee schedule. Missing intervals -> UNVERIFIED, never zero fill or zero funding.
3. Run identical sample in unchanged 3x/5x baseline and 0.25%/0.5% risk budgets; apply quantity rounding, minimum order rules, maintenance margin tiers and marketable-stop gap execution.
4. Compare LONG and SHORT separately; mark-to-market equity path, monthly net equity, closed/MTM DD, stop counts, rejected orders, liquidity shortfalls, liquidation crossings, MFE retention, and unseen-forward results.
5. Do not promote break-even, trail, staged entry or control-transfer exits without independent unseen-forward improvement.

## Status
This iteration validates the arithmetic sensitivity using the frozen reports and existing authorization formula. **No matched historical trade tape, no new historical fills, no MTM/liquidation proof, and no live orders.** Frozen D250 thresholds unchanged.
