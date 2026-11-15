# HYPE leverage-independent stop-risk and gap-budget audit — 2026-11-15 08:31 CET

Research-only deterministic extension of the frozen D250 / 1% adverse-price cut. No detector training, production change, or orders. Sources read directly from this branch: H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md, HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md, HYPE_STOP_TO_LIQUIDATION_BUFFER_AUDIT_2026-11-15_0727_CET.md.

## New analysis: notional sizing must be independent of leverage

Given equity E=100, stop adverse move s=0.01, assumed round-trip fees f=0.0015, *illustrative* funding reserve u=0.0006, and additional adverse stop-fill gap g, all-in adverse loss per unit notional d=s+f+u+g. Notional cap N=E*r/d, with r=0.0025 or 0.005. This is a **conditional scenario** not a guaranteed stop-risk cap. Isolated margin M=N/L at leverage L, but changing L does not change N or dollar loss if fills are the same. Real Bybit order minimums, margin tiers, fee schedule, mark/last stop triggers, and liquidation price must be checked separately.

| Additional gap | all-in adverse % of notional | N at 0.25% E | N at 0.50% E | margin at 3x for 0.50% | margin at 25x for 0.50% |
|---:|---:|---:|---:|---:|---:|
| 0% | 1.21% | $20.66 | $41.32 | $13.77 | $1.65 |
| 1% | 2.21% | $11.31 | $22.62 | $7.54 | $0.90 |
| 2% | 3.21% | $7.79 | $15.58 | $5.19 | $0.62 |
| 3% | 4.21% | $5.94 | $11.88 | $3.96 | $0.48 |
| 5% | 6.21% | $4.03 | $8.05 | $2.68 | $0.32 |

**New risk comparison**: A $22.62 nominal sized to 0.5% equity at 1% gap instead loses $0.9525 (0.9525% equity) if the actual gap is 3%, before any additional unmodeled fees/funding. Sizing to 3% gap gives N=$11.8765, so the same 3% gap loss is $0.50. A stop-market order can still fill worse than 3% gap, and liquidation can preempt it.

## Six-stop-streak compounding diagnostic
The frozen asymmetric report observed a maximum historical losing streak of six, but its simulated loss magnitudes are not reliable real fill bounds. If *each* of six losses exactly equals a fraction r of then-current equity, the compounded drawdown is 1-(1-r)^6: 1.4907% at 0.25% risk; 2.9627% at 0.5% risk; 5.8520% at 1% risk. This excludes correlated gaps, funding variation and open-equity drawdown. It is not a replay of the observed streak.

## Critical execution geometry
- LOW -> LONG: 1% stop trigger at 0.99 x actual entry fill; stop-market SELL; estimate bid depth, adverse sell sweeps, mark/last divergence and latency.
- HIGH -> SHORT: 1% stop trigger at 1.01 x actual entry fill; stop-market BUY; estimate ask depth, adverse squeeze/buy sweeps, mark/last divergence and latency.
- Fixed 25x isolated leverage gives only about 4% initial margin/nominal; real liquidation boundary is closer than this theoretical margin-only ceiling. 3x gives about 33.33% initial margin/nominal, but neither is a verified Bybit liquidation price. Choosing lower leverage at the same risk-sized notional increases initial collateral and generally improves distance to liquidation, subject to account mode and exchange rules.
- For staged entry, each fill must recompute weighted entry, stop trigger, total worst-case stop risk and available collateral; do not sum independent 0.5% budgets when overlapping. Total active stop-risk <=1% E under the chosen gap scenario; gaps can exceed it.
- Profit-lock and opposite-local exits remain unpromoted; do not use future exact opposite extreme or post-stop MFE.

## Reproduction
```python
E=100.; s=.01; f=.0015; u=.0006
for g in (0,.01,.02,.03,.05):
    d=s+f+u+g
    n25=E*.0025/d; n50=E*.005/d
    print(g,round(100*d,2),round(n25,2),round(n50,2),round(n50/3,2),round(n50/25,2))
    assert abs(n50*d-.5)<1e-10
n_at_1pct_gap=.5/(s+f+u+.01)
assert abs(n_at_1pct_gap*(s+f+u+.03)-.9524886877828054)<1e-9
for r in (.0025,.005,.01):
    print(r,100*(1-(1-r)**6))
```

## Evidence and limitations
This is a **new deterministic sizing/leveraging stress analysis**, not matched trade-event replay. Original 71 accepted signals, 67 closed episodes, 4 censored episodes, event timestamps, Bybit rich M1 Public Trades/L50/OI/liquidations, order-book execution and funding records still need to be joined. Do not report monthly net equity, fills, mark-to-market DD, actual liquidations, MFE retention or independent forward performance from this calculation. Baseline unchanged, rejected overlays remain rejected. Prioritize recovery of event data and identical-sample comparison before promoting any protection layer.
