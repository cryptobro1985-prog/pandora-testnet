# D250 stop-gap risk-budget sensitivity — 2026-11-22 11:29 UTC

Research only. No live fills, no detector retraining, no production changes. Frozen D250 and the original 67-trade baseline unchanged.

## New reproducible counterfactual calculation

Inputs from the frozen 2026-11-12 asymmetric-risk report: 1.00% adverse-price cut and 0.15% round-trip notional cost. Consider an additional **adverse execution gap** g (percentage points of entry price), not observed market data. With equity E, target stop-risk r, and notional N:

loss_fraction_of_notional = 0.0100 + 0.0015 + g
N_max = E*r/(0.0115+g).

This deliberately treats full 0.15% as loss-side cost and g as *additional* loss after trigger; funding and minimum order constraints are not yet included. All values are upper-bound feasibility estimates, not approved orders.

At E=$100:
| Additional gap | Loss per $ notional | N at 0.25% risk | N at 0.50% risk | N at 1% portfolio cap |
|---|---:|---:|---:|---:|
| 0.00% | 1.15% | $21.74 | $43.48 | $86.96 |
| 0.50% | 1.65% | $15.15 | $30.30 | $60.61 |
| 1.00% | 2.15% | $11.63 | $23.26 | $46.51 |
| 2.00% | 3.15% | $7.94 | $15.87 | $31.75 |

**New finding:** sizing at zero-gap 0.5% risk permits $43.48 notional; if an additional 2% adverse gap occurs, the loss becomes $1.3696 = **1.37% equity**, breaching the 1% aggregate stop-risk budget even with just one position. Sizing *for* the 2% stress scenario reduces notional to $15.87 and keeps the hypothetical stressed loss to $0.50. This is not a guarantee: larger gaps, outages, liquidation, fee changes and funding can still exceed budget.

At 25x, $15.87 notional uses ~$0.635 initial margin before exchange constraints; leverage does not change the dollar loss for a fixed notional. A hypothetical $20 minimum order would make the 0.5%-risk, 2%-gap trade infeasible at $100 equity. Actual Bybit filters, maintenance margin, liquidation mark price and available liquidity must be verified per UTC trade.

## Causal execution gate (unchanged signal)

Only after strict H1 LOW -> LONG or strict H1 HIGH -> SHORT and D250 confirmation; no entry before checkpoint, no oracle opposite extreme. Require actual marketable quote, valid size filters, available account collateral, and a protective stop that can trigger on the chosen Bybit price basis. Check stress gap + cost budget **before** quantity rounding; round quantity down. If no eligible size, skip. Keep existing 1% cut as baseline; test structural stops and staged entries only in matched per-trade replay. Rejected MFE overlays remain rejected.

## Reproduction

```python
E=100.0
for gap in (0,0.005,0.01,0.02):
    cost=0.01+0.0015+gap
    print(gap, *(round(E*r/cost,2) for r in (0.0025,0.005,0.01)))
n0=100*.005/(.01+.0015)
print('zero-gap-sized loss at 2% extra gap',round(n0*(.01+.0015+.02),4))
```

## Evidence status

This is a new deterministic *stress sensitivity*, not an event-level Bybit replay. No per-trade UTC manifest or matched rich M1/L50/liquidations/OI execution fills were established in this iteration. Therefore no new valid monthly net equity, MTM DD, fill, stop, liquidation, MFE-retention or unseen forward metrics. The earlier historical 67-trade results are not relabeled as live or independently replayed. Next useful step is recovery of original per-trade UTC rows and tape provenance, then identical-sample execution replay with no capital overlap.
