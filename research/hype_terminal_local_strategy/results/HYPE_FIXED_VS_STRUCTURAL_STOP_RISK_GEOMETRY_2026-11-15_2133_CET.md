# HYPE frozen D250: structural versus fixed-stop risk-budget incompatibility — 2026-11-15 21:33 CET

Research-only arithmetic on actual frozen report parameters; **not** matched trade execution replay, no new OOS result, no proof of fills/liquidation safety.

## Sources and audit distinction
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md: 71 accepted signals; 67 with finalized next opposite strict H1 local; median next-opposite-extreme upside 2.046% is **oracle geometry**, NOT executable profit; median diagnostic structural stop distance 3.140%; median MAE 0.414%, worst 1.958%.
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md: 67 modeled sequential closed trades, 22 modeled 1% cuts, 0.15% assumed round-trip cost, 49.25% profitable. The 1% adverse cut was selected on Jul-Aug development. The 67 trades cannot be independently joined to the 67 completed geometry cases without event identifiers.
- Prior HYPE_SIX_LOSS_GAP_RISK_STRESS_2026-11-15_2028_CET.md: funding reserve 0.06% and adverse gap budget 1%; these are stress assumptions, not observed fees/funding/gaps.

## New quantitative comparison, same risk-budget assumptions
Risk-sized account exposure = equity-risk / (price stop distance + 0.15% round-trip cost + 1% budgeted gap + 0.06% funding reserve).
This is NOT exchange leverage; 25x leverage is possible only if actual margin, maintenance margin, and liquidation checks pass.

| Price-stop geometry | Planned equity risk | Account exposure | Notional at $100 equity | Loss if actual adverse gap 2%, % equity | Oracle median 2.046% price target gross, % equity |
|---|---:|---:|---:|---:|---:|
| 1.00% | 0.25% | 0.1131x | $11.31 | 0.363% | 0.231% |
| 1.00% | 0.50% | 0.2262x | $22.62 | 0.726% | 0.463% |
| 3.14% | 0.25% | 0.0575x | $5.75 | 0.307% | 0.118% |
| 3.14% | 0.50% | 0.1149x | $11.49 | 0.615% | 0.235% |

At equal 0.5% planned equity risk, a 3.14% structural stop requires smaller notional than a 1% stop. The median **oracle** upside / stop distance is 2.046/3.14 = 0.652 before fees; it cannot establish executable expectancy. The 1% cut and structural stop are different strategies; do not assume one universally dominates based on aggregated reports.

## New evidence gate / no-trade conditions
- LONG only after H1 LOW confirmation and frozen D250 causal availability; SHORT only after HIGH confirmation. Validate timestamp ordering and no intervening invalidation.
- Before entry require stop-order feasibility and conservative expected fill price. If 1% cut is already within bid/ask spread, stale data, or maintenance/liquidation buffer, reject entry. No fallback to 25x notional sizing.
- No per-trade comparison is valid without identical trade identifiers, event-time bid/ask, stop trigger type (mark vs last), order acknowledgment, and funding history. Missing L50/OI/liquidations remain missing, not zero.
- Report both equity mark-to-market and closed DD and all open cases; do not convert oracle extremes into executable exits.
- Previously rejected flow/MFE, K0/K1 and tight trailing overlays remain rejected.

## Reproduce
```python
for stop in (0.01,0.0314):
    for risk in (0.0025,0.005):
        exposure=risk/(stop+0.0015+0.01+0.0006)
        print(stop,risk,round(exposure,6),round(100*exposure,2),
              round(100*exposure*(stop+0.0015+0.02+0.0006),3),
              round(100*exposure*0.02046,3))
```

No detector retraining, no threshold tuning, no production changes, no orders. Next checkpoint must prioritize actual individual tape replay, not another aggregate-only optimization.
