# HYPE D250 opposite-event ledger fail-closed checkpoint — 2026-11-18 19:25 CET

## Scope
Research-only change in existing branch. Frozen D250 thresholds unchanged. No retraining, orders, deployment, or trading-performance claims.

## Concrete code change
Updated `research/hype_terminal_local_strategy/d250_trade_replay_manifest_gate.py` in commit `32789f8f78ca6f5279d666da3db177e7da4c8a4d`.
The manifest now requires `opposite_ledger_coverage` and `opposite_ledger_first_utc`. `COMPLETE` plus `NONE` means an explicitly asserted empty opposite-local event ledger; empty/missing evidence blocks. The earliest opposite event at or before STOP exit blocks STOP. An opposite-local exit must match the earliest ledger timestamp. Same-timestamp events fail closed; events preceding entry block. All flags remain untrusted until independent event-ledger reconstruction from source.

## Why this matters
Previous gate accepted STOP with absent opposite-confirmation timestamp. That is not evidence STOP preceded the opposite event, and can produce invalid hold-to-opposite results. The new fields are a prerequisite to *candidate* replay eligibility, not validation of chronology or fills.

## Validation status
Source change committed and fetched pre-change source reviewed. New code was **not executed in this run**; do not claim regression tests passed. Next action: run synthetic and adversarial tests on committed module, especially missing ledger, NONE with opposite exit, equal timestamps, conflicting explicit confirmation, and ledger events before entry. Then independently reconstruct the ledger from raw UTC source events; the manifest COMPLETE flag alone is not proof.

## Data/replay blockers
67-trade May-inclusive UTC event journal and matched Bybit Public Trades/L50/mark/funding execution tape remain unverified. Consequently no new monthly net equity, MTM DD, stop fills, liquidations, MFE captured/given back, or forward result is asserted. Do not compare changed samples with the historical 3x/5x baseline. Keep rejected profit-lock overlays rejected pending unseen evidence.
