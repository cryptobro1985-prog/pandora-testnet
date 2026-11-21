# D250 execution replay cost-model parity gate — 2026-11-21 02:30 CET

Research only; no orders, no detector retraining, no threshold changes.

## New source-level finding
Read the frozen `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`, `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`, and `causal_exit_replay_research.py` directly on the target branch.

**Cost mismatch**: the 67-trade frozen asymmetric-risk baseline assumes **0.15% round-trip notional cost** (`0.0015`); the separate `causal_exit_replay_research.replay` defaults to **0.25%** (`0.0025`). These are not interchangeable baselines. Replaying the same gross exits through the latter silently charges an additional 0.10 percentage points of notional per trade.

At 3x account exposure the extra cost is **0.30 percentage points of equity per completed trade**; at 5x it is **0.50 points**. For 67 sequential trades, the arithmetic sum of extra costs before compounding is **20.1 and 33.5 equity percentage points**, respectively. These sums are NOT estimates of the final equity impact: changing equity changes later notionals, and the actual trade-by-trade ledger is required.

**Time/price resolution mismatch**: `causal_exit_replay_research.py` uses OHLC and `close` for opposite exits and stop-gap approximations, whereas the frozen result does not establish matched per-trade bid/ask/mark/funding execution. Its `net_equity_pct` on `OPEN` is unrealized, not closed PnL. Hence it cannot validate the published 67-trade equity curve by substituting default inputs.

## Reproducible deterministic audit
```python
frozen_cost=.0015
replay_default_cost=.0025
n=67
for exposure in (3,5):
    delta=exposure*(replay_default_cost-frozen_cost)
    print(exposure, round(delta*100,6), round(n*delta*100,6))
# 3 0.3 20.1
# 5 0.5 33.5
```

## Required matched replay invariant
1. Freeze one 67-trade manifest with immutable signal UTC, available UTC, side, entry eligibility, original local event ID, opposite event ID, trade exit and all tape provenance.
2. Run **unchanged baseline** with 0.0015 cost as a labeled legacy scenario, and **realistic cost** as a separate scenario; do not compare two different cost defaults as a strategy improvement.
3. For all alternative sizing/staged entries/stops/BE/locks, reuse the same eligibility universe, chronology, fills model, funding schedule, and capital occupancy. Report missing L50/mark segments as unresolved, never as no-stop.
4. Keep LONG and SHORT separate; record realized vs unrealized PnL, quote-side fills, gap/slippage, liquidation buffer, monthly net equity and MTM/closed DD, MFE up to exit only.
5. No performance claim without per-trade evidence and truly unseen forward. Frozen D250 thresholds and previously rejected overlays remain untouched.

## Outcome
A new verified *source-level accounting discrepancy*, not a new historical performance result. No 67-trade event replay was performed; no new equity, liquidation or MFE numbers can be asserted. No production changes.
