# HYPE terminal H1 entry — funding-inclusive gap-risk stress, 2026-11-15 18:25 CET

Research only; **scenario analysis, NOT matched execution replay**. Original D250 detector and 1% adverse-price cut unchanged. No production changes/orders.

## Directly checked preserved sources
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md: 71 first accepted / 0 historical false, 67 finalized opposite locals, median MFE giveback 61.2%, late-Aug mean causal opposite exit -0.727% price.
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md: 67 simulated sequential trades, 22 fixed cuts, 0.15% assumed round-trip cost, 5x exposure closed DD 29.36%; no verified intratrade DD or actual stop fills.
- HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md: different earlier frozen high-confidence cascade and its historical scores; **do not merge these counts with D250 or treat them as independent executions**.
- strict_execution_provenance_research.py: hash check of declared files is not event-level replay.

## New quantitative stress test: funding and stop-gap budget
At equity E, adverse stop distance s=1.00% of entry, modeled round-trip fees/slippage baseline c=0.15% notional, *additional* adverse execution gap g, and hypothetical funding reserve f=0.06% notional, set maximum position notional N=E*r/(s+c+g+f). This is a **conservative scenario parameter**, not observed Bybit funding; actual funding depends on holding timestamps/rates and must be replayed. Fee 0.15% is inherited from frozen study, not verified realized fees. Avoid double-counting if its original 0.15% already includes a slippage component. Instrument leverage L changes required initial margin N/L, not stop-risk N*(s+c+g+f)/E.

| Target stop risk/equity | Gap reserve | Max N/E | N at $100 equity | Initial margin at 3x |
|---|---:|---:|---:|---:|
| 0.25% | 0.00% | 0.20661x | $20.66 | $6.89 |
| 0.25% | 0.50% | 0.14620x | $14.62 | $4.87 |
| 0.25% | 1.00% | 0.11312x | $11.31 | $3.77 |
| 0.25% | 2.00% | 0.07788x | $7.79 | $2.60 |
| 0.50% | 0.00% | 0.41322x | $41.32 | $13.77 |
| 0.50% | 0.50% | 0.29240x | $29.24 | $9.75 |
| 0.50% | 1.00% | 0.22624x | $22.62 | $7.54 |
| 0.50% | 2.00% | 0.15576x | $15.58 | $5.19 |

**Previously quoted 0.232558x** uses stop 1% + 0.15% cost + 1% gap **without** the additional hypothetical 0.06% funding reserve. These figures are different assumptions, not contradictory results.

### Underreserved gap sensitivity (new)
If a $100 account sizes to r=0.50% with a 0.50% assumed gap, N=$29.24; but realized additional gap is 2.00%, the adverse trade loss becomes 0.2924*(1%+0.15%+0.06%+2%)=$0.9386 = **0.9386% of initial equity**. This breaches both the single-trade 0.5% budget and nearly exhausts the proposed total 1% concurrent stop-risk cap. Thus a risk-based sizing formula cannot enforce a hard bound under an unbounded gap.

Six successive losses each *actually* limited to 0.25%/0.50% of contemporaneous equity would cause compound DD 1.491% / 2.963%, respectively; this is arithmetic, not observed loss streak replay. Original 5x six exact modeled stop losses of 5.75% each would cause 29.91% compound DD, absent intervening profits.

## Side-specific causal trade replay requirements
- LOW -> LONG: authorization no earlier than max(K2 H1 local confirmation availability, frozen D250 signal availability, required market data availability). Stop trigger below entry; gap/slippage measured on actual bid-side exit. Confirm liquidation threshold on contemporaneous mark, not M1 last trade.
- HIGH -> SHORT: same authorization; stop trigger above entry; exit on ask-side liquidity. Mark path and short-specific adverse gap are separately required.
- First adverse stop/structural invalidation/causally available opposite local wins in event-time; no future exact opposite extreme, no intraminute favorable sequencing assumption.
- Missing L50/trade/mark data => UNKNOWN, never zero fill; do not treat a successful file-hash check as a verified fill.
- Never add profit-lock / BE / MFE overlay to promoted baseline without new independent forward evidence. Report both frozen original baseline and each new risk-budget scenario on the **same 67 eligible completed episodes**, with a separate accounting of 4 unfinalized, no capital reuse.

## Reproduction
```python
for r in (.0025,.005):
    for g in (0,.005,.01,.02):
        x=r/(.01+.0015+.0006+g)
        print(r,g,round(x,5),round(100*x,2),round(100*x/3,2))
print((1-(1-.0025)**6)*100,(1-(1-.005)**6)*100)
print((.005/(.01+.0015+.0006+.005))*(.01+.0015+.0006+.02)*100)
```

## Evidence boundary / next action
This iteration read frozen source reports and calculated a new funding-inclusive risk/gap stress frontier. **No individual event tape was available to this run**, so no per-trade fill, monthly net equity, MTM DD, verified stop count, liquidation count, MFE capture or independent forward result is asserted. Next priority: locate timestamped 67-trade manifest + recovered M1, match K2/D250 times and replay first-hit bid/ask/mark events; require event integrity and distinguish historical simulation from exchange-verified ACKs. No detector retraining, no new branch, no live orders.
