# HYPE symmetric stop-risk budget — 2026-11-16 06:32 CET

Research-only checkpoint; no detector retraining, D250 threshold changes, production changes or orders.

## New reproducible calculation
Added `research/hype_terminal_local_strategy/stop_risk_budget_replay_20261116.py` (commit f6e45cf95d0ffa140a45f077cc80414bccdd88b6) with symmetric LONG/SHORT sizing and explicit fees/funding/gap reserve. For $100 equity, 0.5% equity risk, $100 entry and 1% stop distance, fee 0.15%, funding 0.06%, gap reserve 1%, nominal exposure is $22.6244 (0.2262x). Both LONG stop $99 and SHORT stop $101 produce the same budgeted $0.50 loss. If actual gap is 5%, scenario loss becomes $1.405 (1.405% equity), breaching target risk. This is not a hard maximum risk cap. Two concurrent 0.5% risk allocations consume the 1% total stop-risk budget; actual correlated gaps can exceed it.

## Important evidence limits
These are deterministic arithmetic stress cases, not observed Bybit trade fills. Execution costs are explicit *assumptions*, not measured source values. No matched 67-trade event replay or new monthly net equity / mark-to-market DD / liquidation / MFE statistics. The script includes synthetic assertions; GitHub Actions execution is not verified.

## Follow-up
Identify individual episode timestamps and IDs; match historical M1/Public Trades/L50/mark and OI/liquidation availability, hash source artifacts, and run baseline versus conservative sizing on the same chronological trades. Missing paths and stop-bar ambiguity must fail closed. Do not promote rejected MFE overlays without independent forward evidence. Preserve frozen D250 thresholds and the original 67-trade baseline unchanged.
