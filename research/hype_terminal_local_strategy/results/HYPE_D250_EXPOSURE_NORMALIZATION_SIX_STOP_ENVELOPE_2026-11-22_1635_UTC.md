# HYPE D250 — exposure normalization and six-stop risk envelope
Date: 2026-11-22 16:35 UTC. Research-only, no orders or production changes.

## Inputs verified directly in existing branch
- Frozen D250: 71 accepted signals; 67 with completed opposite-local; 22.4% coverage. No detector retraining.
- Asymmetric risk report: 67 sequential modeled trades, 22 fixed-cut exits; fixed 1% adverse-price cut; round-trip notional fee allowance 0.15%; original 5x equity exposure and 25x instrument leverage; max observed loss streak 6; published closed-equity DD 29.36%.
- Unified causal entry/MFE contract: LOW->LONG, HIGH->SHORT; control transfer requires actual price impact, not raw counter-volume.
- Prior 15:30 checkpoint: actual UTC fill/mark and rich book replay remain missing. GitHub code search searches default branch, not a proof of missing branch files.

## NEW matched-baseline comparability calculation
A 5x *account* exposure is **not** a 0.5% stop-risk trade. With a 1% stop and 0.15% round-trip fees, the modeled stop loss at 5x exposure is 5 * (0.01+0.0015)=5.75% of equity, BEFORE any additional gap. At $100 equity: $500 notional and $20 initial margin at 25x.

A 0.5% equity stop-risk policy with the identical 1% stop and fees, zero gap assumption, allows $43.4783 notional, or 0.434783x equity exposure; at 25x instrument leverage its initial margin is $1.73913. Thus it is 11.5 times less notional than the published 5x baseline. A 0.25% policy allows $21.7391 notional (0.217391x exposure), 23 times less notional than baseline.

**Therefore the published $100->$1,308.86 5x curve must not be described as an outcome of a 0.25-0.5% risk policy.** Nor can its published drawdown be linearly rescaled without per-trade chronological fills and equity path.

## NEW deterministic consecutive-stop envelope (illustration, not historical replay)
For six consecutive identical stops with full re-sizing to the remaining equity, no slippage, and all costs captured in the 1.15% notional loss:
- 0.25% equity risk per stop: equity factor (1-0.0025)^6 = 0.985093; loss 1.491%.
- 0.50% equity risk per stop: equity factor (1-0.005)^6 = 0.970373; loss 2.963%.
- Original 5x exposure: equity factor (1-0.0575)^6 = 0.700998; loss 29.900%.
These are counterfactual identical-stop sequences, NOT the actual reported 29.36% closed DD or an observed live tail-risk limit. Gaps, funding, mark-price liquidation, and fills can make actual losses worse.

## Capital and margin concurrency gate
Let E be current marked-to-market equity; risk_i = notional_i * (stop_distance_i + fees_i + conservative_gap_i). Before any new entry:
1. risk_i <= 0.005*E (exploratory single-trade cap), or 0.0025*E for conservative variant;
2. sum risk_i for all OPEN trades plus new trade <= 0.01*E;
3. sum initial_margin_i + reserved fees + open unrealized losses <= available margin; no double-use of released capital until the closing fill is confirmed;
4. actual Bybit mark-based liquidation distance must exceed stop + gap + basis/maintenance buffer, otherwise BLOCK even if nominal risk_i is small;
5. mark/last/book/funding missing => mark-to-market equity, executable stop, and liquidation count UNKNOWN, not zero.
At two simultaneous 0.5%-risk positions, the full 1% total budget is consumed; further entries BLOCK until actual fills release budget. At four simultaneous 0.25%-risk positions likewise.

## Reproducible Python 3 stdlib
```python
E=100.0
d=0.01; f=0.0015; lev=25.0
for r in (0.0025,0.005):
    N=E*r/(d+f)
    assert abs(N/E - r/(d+f))<1e-12
    print("risk",r,"notional",round(N,6),"margin",round(N/lev,6),"six-stop-loss-pct",round(100*(1-(1-r)**6),6))
N_base=5*E
print("baseline stop loss pct",100*N_base/E*(d+f))
print("baseline six-stop loss pct",100*(1-(1-5*(d+f))**6))
```

## Execution research status
No new matched Bybit event-level replay this iteration: per-trade UTC candidate/K2/entry/exit timestamps, executable L50 snapshots, mark-price path, funding and censored four signals are still not materialized here. Monthly net equity, MTM DD, actual fills, liquidation count and independent forward remain unverified. Rejected tight trailing / raw flow MFE overlays remain rejected. Frozen D250 and production untouched.

## Next replay gate
Recover immutable 71-row first-signal ledger and 67 completed + 4 censored IDs; timestamp-join each to Bybit Public Trades/L50/mark/funding without future info; compute LOW and HIGH execution separately; compare original 5x baseline against risk-budgeted policies on the SAME ordered trade IDs with no capital reuse. Do not report simulated profitability until these are matched.
