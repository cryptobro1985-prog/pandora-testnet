# HYPE D250 risk sizing: stop-gap budget and six-loss streak stress — 2026-11-15 20:28 CET

Research-only incremental stress test. This is NOT per-trade replay, historical fills, verified liquidation count or new OOS evidence. Source: frozen H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md and HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md (67 completed, 22 modeled fixed cuts, longest losing streak 6, assumed 0.15% round-trip notional). No detector changes.

## New calculation: a six-loss streak with stop execution gaps

Let equity E, planned stop risk r=0.25% or 0.50%, stop distance s=1.00%, round-trip cost c=0.15%, *budgeted* additional adverse gap g_b=1.00%, and optional funding reserve f=0.06% of notional. Risk-sized notional N/E = r/(s+c+g_b+f) = r/2.21%; for r=0.25% -> 0.113122x and r=0.50% -> 0.226244x. This is **account exposure**, not instrument leverage or margin percentage. Funding is a stress reserve, not observed funding.

For a realized gap g_a and fixed N/E fraction re-sized after each loss, per-loss fraction L = (N/E)*(s+c+g_a+f). Equity after six consecutive identical modeled losses = E0*(1-L)^6. This is a conditional deterministic stress test, not a historical sequence replay.

| Planned risk r | Actual adverse gap | Single modeled loss % equity | Equity remaining after 6 losses, E0=$100 |
|---|---:|---:|---:|
| 0.25% | 0.0% | 0.1369% | $99.18 |
| 0.25% | 1.0% | 0.2500% | $98.51 |
| 0.25% | 2.0% | 0.3631% | $97.84 |
| 0.25% | 5.0% | 0.7025% | $95.86 |
| 0.50% | 0.0% | 0.2738% | $98.37 |
| 0.50% | 1.0% | 0.5000% | $97.04 |
| 0.50% | 2.0% | 0.7262% | $95.72 |
| 0.50% | 5.0% | 1.4050% | $91.86 |

**Interpretation:** six losses with a 2% adverse gap can cost ~4.28% at planned 0.5% risk, despite a nominal 1% stop. At a 5% adverse gap the single-trade loss exceeds the planned 1% aggregate stop-risk ceiling; the ceiling is a pretrade sizing target, NOT a hard guaranteed loss cap.

## Gate before any promotion

1. Reconstruct individual frozen entry timestamps and K2 availability. Distinguish LOW->LONG and HIGH->SHORT; never use next opposite exact extreme as exit.
2. Join M1/Public Trades, L50, mark, OI, liquidations, funding by event time and source hash; report unavailable streams as missing. For M1-only ambiguous stop and opposite exit in the same bar, conservatively treat stop as first, but label interval uncertainty rather than assert a fill.
3. Re-run same 67 episode universe (if individually recoverable) at unchanged 5x baseline and conservative risk-sized exposures, with a single capital ledger, fees/funding and gap/slippage applied consistently. Compare staged entry and BE/profit lock only as unpromoted challengers.
4. Compute month-level net equity, closed and mark-to-market DD, observed fills, stops, liquidations, MFE capture/giveback, and truly later unseen forward. Do not claim these from aggregate means.
5. Previously rejected flow/MFE and K0/K1 overlays remain rejected without independent new evidence.

## Reproducibility

```python
for r in (.0025,.005):
    exposure=r/(.01+.0015+.01+.0006)
    for gap in (0,.01,.02,.05):
        loss=exposure*(.01+.0015+gap+.0006)
        print(r,gap,round(100*loss,4),round(100*(1-loss)**6,2))
```

No real orders, no production edits, no training, no threshold changes. This stress test is a risk boundary only; no claim of positive forward returns or zero liquidations.
