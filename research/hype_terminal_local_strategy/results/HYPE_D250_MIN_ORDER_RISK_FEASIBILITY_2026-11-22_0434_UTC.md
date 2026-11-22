# D250 minimum-order feasibility and fee floor audit — 2026-11-22 04:34 UTC

Research-only. Frozen entry unchanged; no detector retraining, production edits, orders or historical execution claims.

## Sources inspected
Read `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`, `d250_execution_policy_wrapper_20261122.py`, `d250_combined_risk_gate_20261122.py`, and `d250_conservative_stop_risk_sizer_20261121.py` directly from this branch.

## New deterministic feasibility analysis
Assume equity $100, entry $100, adverse stop distance 1%, round-trip fee allowance 0.15%, adverse gap reserve 2%. Modeled loss fraction per unit notional = 0.0315. With per-trade equity risk 0.25% / 0.50%, maximum notional = $7.93650794 / $15.87301587 respectively. At illustrative 25x leverage, margin = $0.31746032 / $0.63492063. These are stress-budget *caps*, not executable orders.

For hypothetical minimum notionals $5 / $10 / $20, minimum modeled equity risk at this stop/gap/cost assumption is $0.1575 / $0.3150 / $0.6300 respectively. Hence a $10 minimum is **infeasible at 0.25%** but feasible at 0.50% if lot-step rounding permits; a $20 minimum is infeasible at either risk. These are **illustrative** limits, NOT historical Bybit HYPEUSDT specifications.

At $100 entry and hypothetical 0.01 HYPE lot step, 0.25% budget floors to 0.07 HYPE ($7 notional; $0.2205 stressed loss), and 0.50% floors to 0.15 HYPE ($15 notional; $0.4725 stressed loss). If the minimum notional is $10, the 0.25% case blocks; the 0.50% case passes. At a $20 minimum both block. The wrapper correctly refuses upward quantity rounding in these examples.

## Important distinction from original baseline
The 67 sequential modeled trades and 3x $100->$531.16 result in the frozen report use 0.15% cost but do not verify stop gaps, mark-to-market drawdown, or order-size feasibility. The report's 49.25% positive closes and 22 stop exits are historical *simulation outputs*, not independent executable fills. Replacing 3x exposure with <=0.1587x cannot inherit its terminal equity result.

## Replay blocker and next action
Before matched 67-trade replay, obtain (1) immutable per-trade UTC signal/confirmation/entry/exit ledger, (2) event-time Public Trades and mark-price data, (3) timestamped HYPEUSDT lot/min-notional rules, (4) relevant L50/liquidation/OI provenance, and (5) fee/funding assumptions. Do not synthesize missing events, substitute unrelated CSV, or treat hypothetical minimum limits as verified. If a lot minimum violates risk budget, mark NO_TRADE rather than relax the stop/risk cap.

## Status
This checkpoint is a new deterministic order-feasibility analysis, not a matched trade replay. No monthly net equity, MTM DD, fills, stop count, liquidations, MFE capture or independent forward metrics are newly established. Previously rejected profit-protection overlays remain rejected.
