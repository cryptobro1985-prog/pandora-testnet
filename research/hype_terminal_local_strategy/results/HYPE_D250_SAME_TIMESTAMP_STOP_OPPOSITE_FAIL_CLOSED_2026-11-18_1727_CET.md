# HYPE D250 event-order ambiguity checkpoint — 2026-11-18 17:27 CET

Research only. Frozen detector and original baseline unchanged. No production edits, orders, retraining or claimed execution replay.

## Concrete source-level finding
In the previously committed manifest gate, a STOP at precisely the same timestamp as a confirmed opposite H1 local passed the ordering check: it rejected only opposite_confirmed_utc < exit_utc. The preceding checkpoint explicitly left this ambiguity unresolved. When the only available timestamps are minute-resolution, STOP-first cannot be established. Crediting a STOP outcome would therefore silently assume intraminute order not supported by the evidence.

## Applied fix
Changed the STOP ordering condition to opposite_confirmed_utc <= exit_utc. Such rows now fail closed with STOP_NOT_PROVEN_BEFORE_OPPOSITE_CONFIRMATION. A STOP strictly earlier than a known opposite confirmation remains eligible for later exchange-tape verification. The opposite-confirmed exit path is unchanged. Code commit: 884ef241ee6c09c85b011c76f7d857d73f73f501.

## Deterministic chronology cases (logical inspection, not executed regression tests)
- opposite confirmation 12:00, STOP 12:01 => BLOCKED
- opposite confirmation 12:00, STOP 12:00 => BLOCKED (new boundary case)
- STOP 11:59, opposite confirmation 12:00 => ordering gate alone does not block
- STOP with no opposite confirmation supplied => timestamp ordering cannot be verified; manifest gate does not establish event completeness

## Limits
This is a concrete source-level causal-order correction, **not** a matched per-trade replay. No test suite was executed in this run. The original May-inclusive 67-trade UTC ledger, May M1 cohort, and synchronized Bybit trades/mark/L50/liquidation/OI event tape remain unverified. Thus net monthly equity, MTM/closed DD, fill and stop counts, liquidation count, and protected MFE cannot be credibly reported. COMPLETE coverage flags are assertions, not exchange validation.

## Next execution requirement
Run the existing regression suite including an equal-timestamp case, recover immutable trade IDs and timestamps, validate exchange event ordering and gaps, then replay the same frozen cohort with original baseline versus 0.25%-0.5% risk-based sizing and <=1% total stop-risk. Never substitute a nearest future opposite extreme or re-enable rejected profit-lock overlays without independent evidence.
