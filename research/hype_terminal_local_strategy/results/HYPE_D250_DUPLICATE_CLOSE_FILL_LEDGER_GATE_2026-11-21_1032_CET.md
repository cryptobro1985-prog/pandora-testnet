# HYPE D250 — close-fill accounting invariant, 2026-11-21 10:32 CET

Research-only. Existing frozen detector and 67-trade baseline unchanged. No orders.

## Source checked
`research/hype_terminal_local_strategy/execution_risk_reservation_20261121.py` (current target branch).

## New deterministic execution-accounting challenge

The existing `close_confirmed(order_id, fraction_of_open=1.)` trusts a *fraction of currently open risk*, without validating the quantity actually closed against exchange-confirmed fills. It also permits a close event while part of the original entry remains pending.

Example: equity $100, 1% total risk cap, order A budget $0.50, 40% entry filled. Open risk $0.20, pending risk $0.30. If the system receives a duplicate close-confirmed event twice with fraction_of_open=0.5, it releases $0.10 then $0.05, even if only one real close execution occurred. Remaining reservation becomes $0.35 rather than $0.40. An entirely spurious close event with fraction 1 releases all $0.20 open risk. A later pending entry fill can then increase exposure without the expected risk budget.

This is a **ledger-interface failure scenario**, not evidence of actual Bybit duplicates. It does not alter the 67-trade return figures.

## Required causal invariant

Every accepted close execution must carry a unique exchange execution ID, a strictly positive base-asset quantity, side, order ID, UTC execution time, and actual fill price. Maintain cumulative entry and close filled quantities. Reject duplicate execution IDs; reject closes exceeding open quantity; never reduce open risk on a signal, cancellation, stale status or unverified fill. Convert closed quantity to released risk using the entry fill's per-unit reserved risk (FIFO or explicitly specified matching); account for actual fees and realized PnL separately. Entry order cancellation releases only the *unfilled* reservation. If execution history has gaps or ambiguous reconciliation, freeze new orders and mark state UNRESOLVED.

## Same-sample replay gate

Before comparing frozen baseline and low-risk variants, extract 67 immutable entries with side, available_at UTC, price, opposite-local available_at UTC, original stop, and matching trade/quote tape. For each trade retain entry and close execution IDs or simulated event IDs with quote provenance. Require same fills, fee/funding/slippage model, no capital overlap, and report both closed and MTM DD. Missing quote sequence => UNRESOLVED, never infer a stop fill from M1 close.

## Current measured outcome

A static inspection and deterministic arithmetic counterexample establish the interface risk; no matched Bybit event replay was executed here. No new net-equity, stop, liquidation, or MFE metrics are claimed. Frozen D250 and rejected overlays remain unchanged.
