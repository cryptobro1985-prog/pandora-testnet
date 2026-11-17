# HYPE D250 post-local execution gate — opposite confirmation must occur after entry
Date: 2026-11-17. Paper research only; no orders, no detector training.

## Verified code defect
In the pre-existing manifest gate, an OPPOSITE_CONFIRMED exit was accepted when opposite_confirmed_utc was after d250_signal_utc but **before entry_utc**. This permits a trade to open despite a known opposing H1 confirmation and subsequently claim an opposite-local exit. This is invalid for an entry-to-opposite causal replay.

## Change
For exit_reason=OPPOSITE_CONFIRMED, require opposite_confirmed_utc >= entry_utc (and exit_utc >= opposite_confirmed_utc). STOP exits continue to permit absent or future opposite confirmation. Frozen D250 thresholds remain unchanged.

## Regression cases added
- Opposite confirmed at minute 250, entry at minute 251: BLOCK (OPPOSITE_PRECEDES_SIGNAL).
- Opposite confirmed at minute 251, entry at minute 251: pass the manifest chronology gate (same timestamp is not a validated executable fill).
- Existing STOP, opposite-late, opposite-missing, future-feature, side-mismatch scenarios retained.

## Execution status
Code and tests committed; test execution NOT verified in this iteration because the runner could not resolve raw.githubusercontent.com. These are synthetic regression cases, not Bybit event replay. No individual 67-trade UTC ledger or matched orderbook/tape has been recovered here. No new net equity, MTM DD, stop-fill, liquidation, or MFE result is asserted.

## Next evidence gate
Recover immutable 67-trade UTC ledger and market event artifacts, run these tests, independently verify M1/trades/mark coverage and enforce non-overlap. Compare same-sample original baseline with 0.25–0.5% equity stop-risk alternatives and explicitly account for gap/slippage/funding. Keep previously rejected exit overlays rejected pending independent forward evidence.
