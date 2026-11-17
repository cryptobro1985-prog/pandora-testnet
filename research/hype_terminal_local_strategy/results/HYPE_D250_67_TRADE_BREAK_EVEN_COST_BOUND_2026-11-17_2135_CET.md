# D250 67-trade break-even execution-cost bound — 2026-11-17 21:35 CET

Research-only reproducible arithmetic audit. No new fills, no trade-level replay, no model changes.

## Primary sources
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`: 67 completed sequential trades; 49.25% positive, 5x exposure, rounded mean positive equity return +14.16%, mean negative equity return -4.37%, 0.15% round-trip notional cost already included.
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`: 71 accepted signals, 67 with finalized opposite local. Do not assume remaining four are executed, open or profitable without UTC records.
- `results/HYPE_D250_MONTHLY_EQUITY_AND_STOP_BUDGET_RECONCILIATION_2026-11-17_2029_CET.md`: published equity checkpoints are noncontiguous research windows and not a chronological forward return curve.

## New independent calculation from published rounded aggregates
49.25% of 67 = 33 winning and 34 nonwinning completed trades (consistent with rounding). Arithmetic mean equity return at 5x from the published rounded winner/loser averages:

`(33*14.16 - 34*4.37)/67 = +4.7567164179% per trade`.

For a **hypothetical uniform additional round-trip execution cost c percent of notional** applied to every trade without changing fills, exits or trade membership, equity arithmetic mean decreases by `5*c` percentage points. Break-even incremental c = `4.7567164179/5 = 0.9513432836%` of notional. This is **not a safe slippage allowance**: the distribution, stop gaps, missed fills and compounding change when execution costs change. Base 0.15% round-trip cost was already deducted; do not double count.

| Additional cost % of notional | Approx. mean 5x equity return per trade | Implied break-even winner fraction under fixed rounded winner/loser magnitudes |
|---:|---:|---:|
| 0.00 | +4.7567% | 23.58% |
| 0.10 | +4.2567% | 26.28% |
| 0.25 | +3.5067% | 30.33% |
| 0.50 | +2.2567% | 37.08% |
| 0.75 | +1.0067% | 43.82% |
| 1.00 | -0.2433% | 50.57% |

Break-even winner fraction formula: `(4.37+5*c)/(14.16+4.37)`, where c is percentage points of notional; fixed winner/loser magnitudes assumed. Historical observed winner fraction = 33/67 = 49.25%. These averages are rounded and not sufficient to reproduce compound equity, chronological monthly returns, mark-to-market DD, or any OOS claim.

## Important execution and inference caveats
1. The 0.9513% threshold is a **mean-return sensitivity**, not an execution model or a robustness guarantee. Price slippage can also alter stop triggering, trade direction eligibility and winners vs losers.
2. An unusually favorable conditional payoff can yield a low arithmetic break-even win rate while hiding tail risk and poor temporal generalization. The frozen late-Aug causal-exit weakness and the missing MTM evidence remain unresolved.
3. Do not equate 71 accepted signals with 71 executed trades; 67 finalized-next-local episodes are not a reconciled execution ledger. Do not label four missing episodes right-censored without timestamp-level proof.
4. For LOW->LONG and HIGH->SHORT replay separately, require UTC signal availability, first executable quote/trade after decision, stop order activation and price trigger, stop gap/slippage, funding, liquidation/mark-price buffer, opposite-local availability, and MFE path. Missing L50/OI/liquidations are UNKNOWN, not zero.
5. For conservative 0.25–0.50% equity stop-risk sizing, size by total expected stop distance plus fees/slippage/gap reserve and enforce aggregate 1% stop-risk; no inferred zero-liquidation result.
6. Rejected MFE/flow, K0/K1 and tight ATR trailing overlays remain rejected. No production changes, real orders, or retraining.

## Reproduce (Python 3 standard library)
```python
wins, losses, exposure = 33, 34, 5
avg_win, avg_loss = 14.16, 4.37
mean = (wins*avg_win - losses*avg_loss)/(wins+losses)
print("mean equity return %", mean)
print("incremental notional cost break-even %", mean/exposure)
for c in (0, .1, .25, .5, .75, 1):
    print(c, mean-exposure*c, 100*(avg_loss+exposure*c)/(avg_win+avg_loss))
```

## Status
Completed new quantitative cost-bound calculation using directly fetched frozen source reports. Historical event-level matching and genuinely unseen forward replay **not completed**. Do not promote to live trading.
