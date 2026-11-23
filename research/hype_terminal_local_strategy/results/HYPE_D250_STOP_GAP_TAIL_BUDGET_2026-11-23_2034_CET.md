# D250 stop-gap tail sensitivity — 2026-11-23 20:34 CET

Research-only reproducible numerical sensitivity; **not** a matched Bybit event replay, not empirical tail probabilities, not a liquidation proof. Frozen D250 unchanged.

## Source
Continue `HYPE_D250_COST_GAP_DIRECTIONAL_RISK_STRESS_2026-11-23_1932_CET.md` on this branch, using its precise directional formulas, reference price $100, account equity $100, fee 0.075% per side, entry slippage 0.03%, stop slippage 0.05%, and initial assumed extra gap 0.20%. For each direction and stop, freeze the nominal position calculated for $0.50 planned loss at 0.20% gap; **do not resize it after observing the larger gap**. Recompute realized loss if gap is 0.50%, 1.00%, or 2.00%.

## New stress calculation
All amounts are USD loss on $100 equity. These are *scenario* gaps, not measured Bybit gaps.

| Side | Stop price distance | Fixed nominal | Loss at 0.20% gap | Loss at 0.50% gap | Loss at 1.00% gap | Loss at 2.00% gap |
|---|---:|---:|---:|---:|---:|---:|
| LOW -> LONG | 1.00% | $35.059 | $0.5000 | $0.6040 | $0.7774 | $1.1241 |
| LOW -> LONG | 3.14% | $14.051 | $0.5000 | $0.5408 | $0.6088 | $0.7447 |
| HIGH -> SHORT | 1.00% | $34.871 | $0.5000 | $0.6058 | $0.7821 | $1.1346 |
| HIGH -> SHORT | 3.14% | $13.961 | $0.5000 | $0.5432 | $0.6153 | $0.7595 |

**Decision-relevant observation:** sizing to a $0.50 expected stop loss does **not** cap realized loss at $0.50. With a 2% extra adverse gap, the fixed 1%-stop nominal loses >$1.12 (>1% of equity) in this scenario. The smaller structural-stop nominal loses ~$0.74–$0.76. Neither stop is proved preferable on realized net expectancy or MFE; no observed gap distribution was estimated. Even a 1% total stop-risk budget can be breached by a single position under adverse gaps.

## Reproduction (Python 3, stdlib only)
```python
for sign, name in ((1, "LONG"), (-1, "SHORT")):
    for distance in (0.01, 0.0314):
        entry = 100 * (1 + sign * 0.0003)
        def loss_fraction(gap):
            fill = 100 * (1 - sign * distance) * (1 - sign * (0.0005 + gap))
            return (sign * (entry - fill) + 0.00075 * (entry + fill)) / entry
        nominal = 0.50 / loss_fraction(0.002)
        print(name, distance, round(nominal, 3),
              [round(nominal * loss_fraction(g), 4) for g in (0.002, 0.005, 0.01, 0.02)])
```

## Operational implication
Treat 0.25–0.5% as a *modelled stop-risk target*, not a guaranteed worst-case loss. Keep portfolio aggregate modelled stop-risk <=1%, explicitly stress correlated gaps and partial/failed stop fills, verify mark-price liquidation crossing before claimed fills, and cap exposure by available margin plus fees. Do not introduce a new exit overlay based on this sensitivity alone.

## Evidence boundary
The original 71 D250 accepted signals, 67 completed opposite-local trajectories, and the historical baseline were **not** rerun here. No per-signal event-tape, bid/ask, mark-price or funding records were matched. No claims about monthly equity, realized slippage, fill counts, observed liquidations, MFE captured, or unseen forward performance are supported by this checkpoint. Next priority remains immutable cohort reconstruction and event-level replay on the same chronological sample.
