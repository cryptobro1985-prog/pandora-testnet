# D250 entry-fee funded margin cap — 2026-11-23 10:26 CET

Research only; no orders and no execution replay.

## Reproduced issue
Read frozen rule and current `d250_side_exact_stop_risk_v2.py` in existing branch. Previous sizing used `min(risk_budget/loss_per_notional, free_margin*leverage)`. At the margin limit this allocates **all** free margin to initial margin, leaving no cash for entry taker fee, so a nominally risk-compliant trade may be unfillable.

Deterministic arithmetic: free margin $1, leverage 5x, entry fee 0.0006 of executed notional, sufficient stop-risk budget. Old cap = $5 notional; cash required = $5/5 + $5*0.0006 = $1.003 > $1. New cap = $1/(1/5 + 0.0006) = $4.985044865; entry margin $0.997008973 and entry fee $0.002991027, sum $1. This holds for LONG and SHORT because notional is measured at executed entry price.

## Change
Research-only risk sizer now caps notional at `free_margin/(1/leverage+fee_entry)`, reports `entry_fee_reserved` and `total_entry_cash_required`, and adds margin/fee regression assertions. Original D250 threshold and baseline unchanged. Arithmetic independently evaluated in JS; Python self-test has NOT been executed in this run.

## Scope / next work
This is a reproducible margin-feasibility defect fix, **not** a historical Bybit tape replay. The 71 UTC signal manifest and matched M1 public-trade / bid-ask / mark / L50 event streams remain necessary for realistic stop fills, liquidation-distance, MTM DD, month-by-month equity and MFE protection comparisons. Funding, maintenance margin tiers, order-size steps, partial fills, dynamic fee schedules, and exit fees may further reduce feasible notional. Reject promotion until full same-sample sequential replay with verified raw data and genuinely unseen forward.

No retraining, no production change, no live orders.
