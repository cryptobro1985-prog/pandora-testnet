# D250 67-trade outcome accounting and stop/exit bottleneck — 2026-11-22 07:35 UTC

Research only; source arithmetic audit, **not** historical fill replay or new forward test. Frozen D250 untouched. No production orders.

## Source of record
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md` (67 completed sequential trades; 22 fixed-cut exits; positive closed trades 49.25%; mean winner +14.16% and mean loser -4.37% at 5x; profit factor 3.14)
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md` (71 accepted D250 episodes; 67 finalized next opposite local; 4 not finalized; 61.2% median causal-exit MFE giveback)
- `results/HYPE_D250_OOS_TEMPORAL_DIRECTION_AUDIT_2026-11-22_0633_UTC.md` (35 later historical OOS, 15 backward holdout)

## New reconciled counts (derived, not independently replayed)
- 49.25% of 67 = 32.9975, so **33 positive closed trades**, subject to the report's rounded percentage.
- Therefore **34 nonpositive closed trades**.
- **22 fixed adverse-cut exits** = 22/67 = 32.8358% of all completed trades. If each was a losing trade as the loss-cut wording implies, **at least 12 of 34 nonpositive trades were NOT fixed-cut exits** (34 - 22 = 12). This is a conditional classification, because the report lacks per-trade exit reason and fees.
- 22/34 = 64.7059% of nonpositive trades at most attributable to fixed-cut exits under this assumption. A stop alone does not eliminate the remaining nonpositive opposite-local outcomes.
- Independent arithmetic cross-check of reported 5x profit factor: (33 * 14.16) / (34 * 4.37) = **3.1450**, consistent with rounded PF 3.14. This verifies internal summary consistency, NOT event-level validity.
- **Four accepted D250 episodes are outside the 67 finalized-pair sample**. Their ultimate outcome and exposure are unknown, not zero-return or automatically excluded from a prospective portfolio.
- 67 completed outcomes are not 67 independent entry validations; 71 accepted signals are not 71 tradable fills.

## Execution implications
1. Preserve the frozen 1% adverse-price cut as an *unchanged baseline* rather than assuming it is an exchange-executed stop. Stop fill, gap, mark trigger, and liquidation remain unverified.
2. Audit the 12 or more other nonpositive exits on causal opposite-local timing and control transfer, **without re-promoting** rejected flow+MFE, K0/K1, tight ATR trails, or pyramiding.
3. In a matched UTC ledger, separately flag: accepted signal, order eligible, filled, stopped, opposite-local exited, censored; do not condition the PnL sample on a future finalized opposite local.
4. For risk 0.25%-0.5% equity and max aggregate stop-risk 1%, derive notional from full stress loss per notional including fee, gap and funding. Use same samples/costs/capital accounting across baselines.
5. If rich M1 trades/CVD/L50/liquidations/OI or mark series missing, leave fields null with missingness mask. Do not synthesize or zero-impute them.

## Reproduction
Python:
```python
n=67
wins=round(n*0.4925)
nonpositive=n-wins
cuts=22
print(wins,nonpositive,nonpositive-cuts)
print(cuts/n, cuts/nonpositive)
print((wins*14.16)/(nonpositive*4.37))
# expected: 33 34 12; 0.3283582089552239 0.6470588235294118; ~3.1450
```
No source trades or synthetic fills were generated.

## Status
This iteration contributes a **new source-derived outcome reconciliation**. Full matched event replay, monthly net equity, mark-to-market DD, slippage, fills, liquidation count, and independent prospective forward remain **unverified**. Do not promote strategy to live.
