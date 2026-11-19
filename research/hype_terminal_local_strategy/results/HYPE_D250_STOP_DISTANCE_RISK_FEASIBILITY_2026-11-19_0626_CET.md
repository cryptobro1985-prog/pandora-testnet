# D250 stop-distance vs risk-budget feasibility — 2026-11-19 06:26 CET

Research-only analytical checkpoint. No historical fill replay, no live orders, no detector training.

## Source audit
Read frozen `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md` and `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md` directly on the named branch. Frozen entry is at D250 and 67 entries have finalized opposite locals. Frozen 1% adverse-price cut was selected on development periods and preserved on OOS. The diagnostic structural stop has median entry distance 3.140%; this is a **median**, not a per-trade stop.

## New executable arithmetic (scenario, not Bybit fills)
Account $100; risk budget 0.25% or 0.50%; round-trip fee allowance 0.15% notional, funding allowance 0.09%, assumed extra stop execution gap 0.50% of entry notional. Pre-fill notional = equity*risk_fraction/(adverse_price_distance+fees+funding+gap). Margin shown at 25x is merely required initial margin before exchange constraints, not a recommended leverage.

| stop distance | risk | notional | 25x initial margin |
|---|---:|---:|---:|
| 1.00% | 0.25% | $14.37 | $0.57 |
| 1.00% | 0.50% | $28.74 | $1.15 |
| 3.14% diagnostic structural median | 0.25% | $6.44 | $0.26 |
| 3.14% diagnostic structural median | 0.50% | $12.89 | $0.52 |

Critical implication: a fixed account-exposure multiplier cannot represent equal risk when the stop geometry changes. The 1% cut is closer than the median structural stop, but an individual structural stop can be closer: choose the closest valid stop and recompute notional **per trade**. Never replace an individual stop with 3.14% median. At 25x, margin requirement is not the binding constraint in these four illustrative rows; instrument minimum notional/quantity and step size may be, and must be checked against the contemporaneous exchange metadata. Stop gap is not capped in reality.

## Execution-replay gate
For each frozen entry ID, require UTC extreme timestamp, strict H1 confirmation availability, D250 signal time, side, entry executable quote and fill VWAP, structural stop, minimum quantity/step, actual order-book age/depth, stop-trigger convention and bid/ask execution, funding timestamps, mark-price liquidation trajectory, next opposite local **confirmation** time, and M1 path to compute MAE/MFE. Reject unavailable fields rather than zero-impute. Reconstruct sequential capital before comparing unchanged baseline, fixed 1% cut, risk-based notional, staged fills and profit lock. Report separately by direction and month, including forward. No performance metrics are inferred here.

## Reproduce
```python
E=100
for stop in (0.01,0.0314):
    for risk in (0.0025,0.005):
        notional=E*risk/(stop+0.0015+0.0009+0.005)
        print(f"{stop:.4f} {risk:.4f} {notional:.3f} {notional/25:.3f}")
```

Status: **arithmetic checkpoint only**. No claims of positive net returns, zero liquidation, or MFE protection. Frozen D250 thresholds and rejected exit overlays unchanged.
