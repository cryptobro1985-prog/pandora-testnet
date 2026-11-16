# HYPE post-local event-coverage checkpoint — 2026-11-16 13:39 CET

Research only. No real orders. No detector retraining or changes to frozen D250.

## New executable analysis
Added `trade_event_coverage_gate_20261116.py`, an episode-by-episode fail-closed gate. It requires LOW/LONG or HIGH/SHORT, confirmed H1 local timestamp no later than entry, entry at least 250 minutes after local extreme, frozen D250 rule identifier, explicit absence of same-side invalidation and already-confirmed opposite local. It requires sorted, unique public-trade, mark-price, and valid L50 timestamps bracketing each trade, with explicit stream-specific maximum gap tolerance. Missing OI, CVD or liquidation streams are disclosed, never zero-imputed.

## Deterministic cases encoded
1. Complete synthetic LONG coverage: COVERAGE_GATE_PASS_ONLY (NOT fill verified).
2. Missing intermediate mark sample beyond permitted gap: UNKNOWN_EVENT_COVERAGE.
3. Entry one millisecond before D250: BEFORE_D250.
4. H1 local confirmed after entry: CAUSALITY_VIOLATION.
5. Missing L50 validity evidence: UNKNOWN_EVENT_COVERAGE.

These are code assertions; no claim is made here that CI executed them.

## Audit finding
The prior M1 replay can establish a conservative candle stop-touch envelope, but cannot certify stop fills, bid/ask, mark-price liquidation precedence, or chronological MFE. The new gate explicitly separates event *coverage* from execution verification. Even PASS does not produce a PnL or zero-liquidation claim. This prevents promotion of the prior 67-trade 3x/5x account results as execution-verified.

## Remaining required inputs
For each of 67 original trades: frozen signal timestamp and strict H1 confirmation timestamp; matched public-trade, mark-price and valid L50 event files with real timestamps; fee tier and funding events; actual exchange stop-order trigger basis and liquidation parameters. Without these, monthly net equity, mark-to-market DD, realized stops, liquidation count, and MFE captured remain UNKNOWN. No baseline or risk overlay has been promoted.

## Next reproducible command
`python research/hype_terminal_local_strategy/trade_event_coverage_gate_20261116.py`
Then `python research/hype_terminal_local_strategy/trade_event_coverage_gate_20261116.py <matched_episodes.json>` once genuine matching data are located. Do not synthesize missing events. Preserve the original baseline and previously rejected protection overlays.
