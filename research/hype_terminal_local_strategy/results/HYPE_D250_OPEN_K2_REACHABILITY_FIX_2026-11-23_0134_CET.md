# D250 full-cohort audit: OPEN_AT_CUTOFF K2 guard reachability
Date: 2026-11-23 01:34 CET
Research only; no real orders.

## Verified source defect
In d250_full_cohort_gate.py before commit 75c52f72, the check for `OPEN_AT_CUTOFF` with a populated `opposite_k2_available_utc` was nested under `if closed:`, where `closed = status.startswith("CLOSED_")`. Therefore that branch could never run. A row with OPEN_AT_CUTOFF, first opposite ledger event NONE, and a populated opposite K2 timestamp could pass this particular consistency check.

## Implemented change
Moved OPEN_WITH_OPPOSITE_K2 check to the nonclosed branch, and added one deterministic regression assertion. The code now declares 13 synthetic checks; execution of the suite is not established in this run.

## Why it matters
An OPEN position cannot simultaneously claim that an opposite K2 confirmation is available by the cutoff without additional reconciliation. An inconsistent status would corrupt the 71-signal ledger and mark-to-market accounting.

## Important scope
This fixes manifest consistency only. It is NOT evidence of execution profitability, stop fills, zero liquidations, causal MFE protection, or forward generalization. The validator does not verify raw exchange SHA-256 against actual files or reconcile the 71 signal IDs with a frozen canonical cohort.

## Frozen constraints
D250 thresholds unchanged: rev_atr > 2.0840049433824706; trade_ratio5 > 0.2727842248141979; flow15 < 0.4504731635235635. Do not retrain, change rejected profit-protection overlays, place orders, or modify production.

## Required next replay
Resolve canonical UTC 71 signals and 4 censored records; fetch matching public trades, executable bid/ask and L50, mark price, OI and liquidation streams where available. Run identical chronological samples for original 67-trade baseline and 0.25%-0.5% equity stop-risk policies; retain no-data as no-data. Produce monthly net equity, MTM/closed drawdown, stop fill/gap, funding, liquidations, and MFE giveback. No such real-tape replay was executed in this checkpoint.
