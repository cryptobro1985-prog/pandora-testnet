# HYPE D250 execution-manifest gate — 2026-11-19 18:30 CET

Research-only checkpoint. No orders, retraining, new branches or production changes.

## Source inspection
Read the frozen D250 walk-forward, asymmetric 67-trade report, every-local 411-trade report, unified causal entry/MFE contract and quote-event replay module directly from the specified GitHub branch.

## New executed analysis
Added `entry_execution_manifest_gate_20261119.py` to validate individual UTC trade provenance before permitting execution replay. Nine deterministic checks passed in local Python. These test manifest integrity, NOT historical Bybit fills.

Required fields per trade: anchor/confirmation/entry/exit timestamps, side, entry VWAP, stop, liquidation threshold, quote/mark/L50 event counts and maximum gaps, realized entry/exit fees, funding, mark extrema, source hash. Reject if confirmation is after entry, stop lies beyond liquidation, mark crosses liquidation, any required stream is missing, quote/mark/L50 gaps exceed the diagnostic 60-second gate, or evidence is untraceable. The 60s gate is an audit threshold, not a verified exchange microstructure bound.

Command: `python research/hype_terminal_local_strategy/entry_execution_manifest_gate_20261119.py`
Manifest command: `python research/hype_terminal_local_strategy/entry_execution_manifest_gate_20261119.py path/to/67_trade_execution_manifest.csv` (nonzero exit if any row rejected).

## Critical cohort reconciliation
Frozen D250: 71 accepted first signals / 317 scored episodes; 67 finalized opposite-local entry paths. The asymmetric report uses 67 sequential trades. The every-local study uses 322 strict locals, 717 candidate paths, and 411 sequential trades. These are NOT automatically identical trade populations. Before baseline-vs-risk comparison, require explicit join on immutable anchor timestamp, direction, confirmation timestamp and entry timestamp. Do not assume the 67 trades match merely because counts agree.

## Status and limitations
No per-trade historical CSV/UTC quote+L50+mark+funding manifest was established or executed in this iteration. Therefore 0/67 historical fills are **verified by this gate**, not evidence that 0 are valid. No new net PnL, MTM DD, stop-fill statistics, liquidation count, monthly equity or MFE-capture claims. Previous synthetic stress and frozen 3x/5x backtests remain unverified at execution level.

## Next research step
Find and join existing historical trade-level artifact(s) and source streams; run this gate on every matched row, then event replay on only evidence-complete trades. Keep original 67-trade baseline unchanged and compare 0.25%/0.5% risk budgets with identical events, fees/funding, one-position capital allocation, and chronological unseen forward. Fail closed on missing data, rather than substitute future extrema or zero-fill L50/OI.
