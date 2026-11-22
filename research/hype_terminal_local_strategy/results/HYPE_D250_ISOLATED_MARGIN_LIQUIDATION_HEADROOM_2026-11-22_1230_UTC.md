# D250 isolated-margin liquidation headroom — 2026-11-22 12:30 UTC

Research only; no orders, no detector retraining, no production changes. Original frozen D250 thresholds, 67-trade baseline, and rejected MFE overlays remain unchanged.

## New calculation: stop-risk sizing is NOT sufficient to prevent liquidation

The prior risk-budget sensitivity caps *account loss* for a specified adverse fill gap, but does not establish that an isolated leveraged position can survive the mark-price path until that stop fills. For isolated margin with notional N and leverage L, initial posted margin is N/L. An approximate necessary collateral condition for surviving a modeled adverse price move d, additional adverse gap g, fee reserve f, and maintenance margin fraction m is:

    N/L + extra_isolated_collateral >= N*(d+g+f+m)

This is a conservative accounting **screen**, not the Bybit liquidation formula. The actual exchange formula also depends on risk tier, mark price, funding, unrealized PnL, position mode, liquidation fees, and other collateral. If the screen fails, do NOT assert that the stop will execute before liquidation.

At 25x, posted isolated initial margin = 4.00% of notional. With round-trip cost reserve f=0.15%, illustrative maintenance reserve m=0.50% (NOT verified Bybit parameter):

| Stop distance d | Extra gap g | Total required fraction d+g+f+m | Shortfall versus 4% initial margin | Approx max leverage with no extra margin |
|---|---|---|---|---|
| 1.00% fixed | 0.00% | 1.65% | none | 60.61x |
| 1.00% fixed | 2.00% | 3.65% | none, 0.35pp headroom | 27.40x |
| 3.14% structural median | 0.00% | 3.79% | none, 0.21pp headroom | 26.39x |
| 3.14% structural median | 2.00% | 5.79% | 1.79pp of notional | 17.27x |

**Finding:** the 25x isolated margin setting leaves only 0.35 percentage points of modeled collateral headroom for the 1% stop + 2% adverse execution gap, and fails this illustrative collateral screen for the median 3.14% structural stop + 2% gap. Risk-based notional sizing alone does not repair this: scaling N down scales both initial isolated margin and loss proportionally. More account equity sitting outside isolated margin does not necessarily protect the position unless it is actually available as position collateral under the exchange's margin mode.

## Illustrative $100 account, 0.5% account stop-risk budget

With d=3.14%, g=2%, f=0.15%, notional upper bound N=100*0.005/(0.0314+0.02+0.0015)=$9.4518. At 25x, initial margin is $0.3781, while illustrative required collateral including 0.5% maintenance is $0.5473. Gap is $0.1692. This is a **hypothetical** stress scenario, not a replayed fill, exchange specification, or proof of liquidation.

With d=1%, g=2%, f=0.15%, N=$15.8730 and initial margin $0.6349. Illustrative requirement including maintenance is $0.5794, leaving just $0.0556 modeled headroom. Actual mark-price liquidation could still precede the stop trigger, especially under a larger gap or maintenance/risk-tier change.

## Reproducible calculation

```python
E=100; risk=.005; leverage=25; fee=.0015; maintenance=.005
for stop in (.01,.0314):
    for gap in (0,.02):
        n=E*risk/(stop+gap+fee)
        margin=n/leverage
        required=n*(stop+gap+fee+maintenance)
        print(stop,gap,round(n,4),round(margin,4),round(required,4),
              round(max(0,required-margin),4),round(1/(stop+gap+fee+maintenance),2))
```

## Mandatory replay checks (not yet met)

- For every D250 accepted LOW->LONG and HIGH->SHORT: UTC confirmation, next executable quote, actual mark/index/last stop trigger basis, initial/maintenance margin tier, risk limits, liquidation price, position mode and isolated/cross status.
- Reconstruct the mark-price path, order-book liquidity, queue and gap/slippage at each stop; treat stop-market as potentially worse than trigger, and stop-limit as potentially unfilled.
- Compare frozen 1% stop, structural stop, and no-tight-trail causal opposite-local exit on the **same chronological trade ledger**; reserve equity for concurrent positions, never reuse capital.
- Stop-risk <=0.5% per trade and aggregate <=1% remains a *research budget*, not a guarantee; skip any order that fails both notional risk and collateral-to-liquidation checks.
- Do not promote any profit-lock or control-transfer overlay without independent forward evidence.

## Evidence boundary

This iteration performed a new deterministic liquidation-headroom stress calculation using preserved median 3.14% structural stop and 0.15% assumed costs. The 0.5% maintenance reserve is explicitly hypothetical. No individual 67-trade UTC ledger, matched M1 Public Trades/L50/liquidations/OI fills, real exchange margin tiers or liquidation-price paths were validated here. Monthly net equity, MTM DD, realized fills, stop count, liquidation count, MFE captured/given back and truly unseen forward performance remain **unverified**. The 71 accepted signals and 67 completed pairs are not interchangeable.
