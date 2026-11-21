# HYPE D250: partial-fill / cancellation risk reservation — 2026-11-21 09:32 CET

Research-only. No detector retraining, production modifications, orders or claimed historical fills.

## Source inspection
Read existing `portfolio_risk_ledger_20261121.py`, frozen `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md` and `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md` from the specified branch. Frozen D250 entry thresholds and the original 67-trade baseline remain unchanged.

## Newly isolated execution state gap
The original ledger reserves risk at acceptance and releases via `confirm_exit(order_id)`, but stores only a single amount per order. It does not distinguish pending quantity from partially filled open quantity. If an order partially fills and the remaining quantity is cancelled, a caller treating cancellation as terminal could release the *entire* budget despite a live position. That is a conditional integration failure mode, not evidence that it occurred historically.

## Concrete reproducible state transition
Equity $100, aggregate stop-risk limit 1%. Order A reserves $0.50; 40% of original quantity fills (risk $0.20); remaining 60% cancels. Correct committed risk is $0.20, NOT $0.00. Order B reserves $0.50, total $0.70. Mark-to-market equity then drops to $60, capacity becomes $0.60: new orders must be blocked until confirmed close fills free risk. After A is fully closed, B still commits $0.50; no release on a mere opposite-local signal.

Added `execution_risk_reservation_20261121.py` with independent `pending` and `open_risk` accounting, `partial_fill`, `cancel_unfilled`, `close_confirmed`, MTM equity update, and embedded deterministic assertions. The assertions have NOT been independently executed in CI in this run. This is an isolated research module, not wired into trading.

## Causal and risk constraints
LOW -> LONG / HIGH -> SHORT only after frozen D250 confirmation; opposite-local availability time must precede any close order. An accepted order reserves worst-case stop loss including fees and modeled slippage. A fill transfers pending risk to open risk without freeing capacity. Cancellation frees only unfilled risk. Closing frees only confirmed filled quantity. Unknown stop fills, missing bid/ask, liquidation distance, or funding prevent a live-ready verdict. A stop-risk cap is not a guarantee under gaps.

## Still missing for promotion
Per-trade UTC joins of all 67 entries with public trades, executable bid/ask or L50 snapshots, mark price, liquidations, OI, funding and stop fill sequence; separate LOW/LONG and HIGH/SHORT performance; equal-cost baseline vs alternative sizing/staging/exit; monthly net equity, MTM and closed drawdown, liquidation count and MFE retention; unseen chronological forward. No new return metrics or historical liquidation claims are made.

## Reproduction
`python research/hype_terminal_local_strategy/execution_risk_reservation_20261121.py`

Research commit for code: `452f370326984478bcabcef791c2ae90d02c2e07`.
