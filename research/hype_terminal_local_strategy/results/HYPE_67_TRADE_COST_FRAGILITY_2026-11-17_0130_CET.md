# HYPE frozen 67-trade cost fragility and execution evidence — 2026-11-17 01:30 CET

Research only. This is a new **aggregate arithmetic sensitivity**, NOT a trade-level/event replay, not a new independent forward result. Frozen D250 and all previous rejected overlays remain unchanged.

## Verified inputs read from branch
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`: 67 sequential paper trades, positive closed 49.25% (33/67), average winning 5x equity return +14.16%, average losing 5x equity return -4.37%, cost assumption 0.15% of notional round-trip, 22 fixed-cut exits.
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`: 71 accepted D250, 67 finalized opposite locals, median causal opposite-local MFE giveback 61.2%.
- `research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md`: profit lock only when sustained opposite price-impact efficiency/control transfer; prior simple overlays rejected.

## New cost fragility calculation (NOT simulated executions)
Using rounded conditional mean equity returns from the original 5x paper report, baseline arithmetic expectation per trade = (33*14.16 - 34*4.37)/67 = **4.7567% equity**. This is NOT a monthly return or compound result and cannot establish fill-level expectancy.

The baseline break-even win frequency at those conditional payoff means is **23.58%**. The actual 33/67 win frequency is 49.25%. Both are derived from *in-sample rounded conditional means*; they are not forward estimates.

Uniform additional round-trip execution cost on every trade, above original 0.15% notional, with 5x exposure and **assuming unchanged gross trade paths and classification**, has the following first-order effect:

| Extra cost (% notional) | Added drag (% equity per trade at 5x) | Adjusted arithmetic mean (% equity per trade) | Fixed-payoff break-even win rate |
|---:|---:|---:|---:|
| 0.00 | 0.00 | 4.757 | 23.58% |
| 0.05 | 0.25 | 4.507 | 24.93% |
| 0.10 | 0.50 | 4.257 | 26.28% |
| 0.20 | 1.00 | 3.757 | 28.98% |
| 0.40 | 2.00 | 2.757 | 34.38% |

**Important:** the 'fixed-payoff break-even win rate' column uses the simplified original winner and loser means, then subtracts the same drag from both. Some winners can become losers as costs rise; the table does not reclassify trades and is not a robust break-even estimate. Actual costs, fills and adverse selection may correlate with trade direction, volatility and stop events. It cannot be used to certify profitability.

## New consistency / provenance findings
1. The report's 5x worst modeled trade -5.75% equity corresponds to -1.15% of notional, exactly 1.00% adverse price cut + 0.15% original round-trip cost in a no-gap ideal fill. **This is a model identity, not evidence of a stop fill or a guaranteed loss bound.**
2. At 5x, an extra 0.20% notional execution friction would consume 1.00% equity *per trade*. Since stop loss is only 1% price before costs, fills and spread must be measured per trade; one global friction constant is inadequate.
3. The 67-paper-trade aggregate does not expose separate LOW→LONG and HIGH→SHORT entry/fill paths. Consequently no valid per-side cost-adjusted risk/reward, mark-price liquidation precedence, monthly equity or independent forward net can be produced from these aggregates alone.
4. Do not confuse the 71 accepted frozen D250 episodes with 67 finalized trades, and do not claim 67 exchange fills.

## Exact reproducible calculation
```python
n,wins=67,33
win_mean,loss_mean=14.16,4.37
mean=(wins*win_mean-(n-wins)*loss_mean)/n
print('mean_equity_pct',mean)
print('baseline_breakeven_win_pct',100*loss_mean/(win_mean+loss_mean))
for extra_notional_pct in [0,.05,.1,.2,.4]:
    drag=5*extra_notional_pct
    print(extra_notional_pct,drag,mean-drag,100*(loss_mean+drag)/(win_mean+loss_mean))
assert round(5*(1+.15),2)==5.75
```

## Next executable replay gate
Find and join immutable UTC trade IDs and entry/exit timestamps for the 67 original paper trades to actual historical Public Trades and mark/L50 coverage. If unavailable, mark **UNMATCHED** and do not invent execution. Run frozen 1% baseline and 0.25/0.5% stop-risk variants on the same chronologically matched event tape, with explicit unknown status for gaps, stop trigger/fill sequence and liquidation. Keep previously rejected MFE overlays rejected unless new truly later untouched evidence supports them.

**Status:** no individual event replay completed here. No new verified net equity, monthly returns, MTM DD, fills, liquidation count or MFE captured. No detector training, no orders, no production changes.
