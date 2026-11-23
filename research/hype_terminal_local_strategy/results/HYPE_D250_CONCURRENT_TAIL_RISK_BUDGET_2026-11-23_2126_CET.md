# D250 risk-budget stress: simultaneous LONG/SHORT tail exposure — 2026-11-23 21:26 CET

Research-only, **new deterministic calculation** continuing HYPE_D250_STOP_GAP_TAIL_BUDGET_2026-11-23_2034_CET.md. Not a Bybit event replay. Frozen D250, cohort, rejected overlays and production unchanged. No live orders.

## Question
Does sizing two concurrent positions at 0.25% equity planned stop-risk each ensure <=1% total realized loss if both experience the previously modeled 2% additional adverse execution gap? **No**, for the 1% stop: LONG $0.56205 + SHORT $0.56731 = **$1.12936**, or **1.12936% of $100 equity**. The same two 3.14% structural-stop positions total $0.75208 (0.75208%). Correlation of stop events is not measured; this is a joint stress, not a predicted frequency.

## Inputs (identical to previous checkpoint)
Reference HYPE price $100; equity $100; taker fee 0.075% per side; entry adverse slippage 0.03%; stop slippage 0.05%; initial sizing assumes extra gap 0.20%; tail stress extra gap 2.00%. Stop price distances: 1.00% and 3.14%. Direction-specific exact fill arithmetic retained.

| Side | Stop | Nominal for 0.25% risk at 0.20% gap | Loss at 2% gap | Nominal for 0.25% *tail-budget* at 2% gap |
|---|---:|---:|---:|---:|
| LOW -> LONG | 1% | $17.5296 | $0.56205 | $7.7972 |
| HIGH -> SHORT | 1% | $17.4356 | $0.56731 | $7.6834 |
| LOW -> LONG | 3.14% | $7.0253 | $0.37236 | $4.7168 |
| HIGH -> SHORT | 3.14% | $6.9804 | $0.37973 | $4.5957 |

**New distinction:** sizing to 0.25% under the *2% gap stress* (last column) limits modeled loss to $0.25 per trade in that specific scenario, but it does **not** guarantee a loss ceiling for larger gaps, exchange failure, mark-price liquidation, or absent liquidity. Such conservative tail-based sizing is a stress candidate only, not a validated strategy improvement. Margin and Bybit minimum quantity/notional constraints may render small sizes untradeable.

## Reproduction (Python 3, standard library)
```python
for sign, name in ((1, "LOW->LONG"), (-1, "HIGH->SHORT")):
    for distance in (0.01, 0.0314):
        entry = 100*(1+sign*0.0003)
        def loss_fraction(gap):
            fill = 100*(1-sign*distance)*(1-sign*(0.0005+gap))
            return (sign*(entry-fill)+0.00075*(entry+fill))/entry
        nominal_base = 0.25/loss_fraction(0.002)
        nominal_tail = 0.25/loss_fraction(0.02)
        print(name, distance, round(nominal_base, 4),
              round(nominal_base*loss_fraction(0.02), 5), round(nominal_tail, 4))
```

## Decision / evidence boundary
The 1% stop is **not rejected**: earlier frozen sequential simulation favored its drawdown/compound trade-off, but did not measure mark-to-market risk or actual stop fills. This calculation exposes a separate aggregate-tail-risk constraint. Before any promotion, recover the immutable 71-signal cohort and timestamp-matched real Bybit event tapes; verify signal-available timestamps, bid/ask, mark-price liquidation distance, stop order acknowledgements, actual fills, funding, and overlapping positions. Replay identical frozen trades with the original 1% cut, structural stop, 0.25%/0.5% stop-risk sizing, staged entry, and previously rejected protection variants as challengers only. Report monthly net equity, MTM and closed DD, stop failures, MFE, liquidation counts and untouched forward outcomes. No observed trades, fills, gaps, liquidation counts, or net returns are claimed here.
