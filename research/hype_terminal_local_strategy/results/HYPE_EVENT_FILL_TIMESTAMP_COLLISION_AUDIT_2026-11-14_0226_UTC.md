# HYPE event/fill timestamp collision audit — 2026-11-14 02:26 UTC

Research-only checkpoint. Existing frozen D250 and 1% adverse cut unchanged. No production edits, orders, or retraining.

## New concrete code-path finding
Reviewed `causal_event_tape_guard_research.py` directly at the target branch. Its replay selects `active = [e for e in events if e.ts_ms >= fill_ms]`. An exchange trade print with exactly the same millisecond timestamp as the reported fill is NOT guaranteed to occur after the fill. Therefore an earlier-in-sequence stop print can be attributed to a position that did not exist. The guard has no exchange sequence ID or order-event ordering key. This is a distinct execution ambiguity from a same-minute OHLC collision and from simultaneous opposite-local/stop signals.

## Reproducible adversarial fixtures against current guard
Call `replay` with `Event` objects from the module:

1. LONG, signal=10, fill=20, entry=100, stop=99, events=[Event(20,"TRADE",98),Event(21,"TRADE",100)]. Current result: STOP_TRIGGER_FILL_UNVERIFIED. Correct evidence-based classification: UNRESOLVED_FILL_TIMESTAMP_ORDER (the 20ms print may precede fill).
2. SHORT, signal=10, fill=20, entry=100, stop=101, events=[Event(20,"TRADE",102),Event(21,"TRADE",100)]. Current result: STOP_TRIGGER_FILL_UNVERIFIED. Correct: UNRESOLVED_FILL_TIMESTAMP_ORDER.
3. LONG, signal=10, fill=20, entry=100, stop=99, events=[Event(19,"TRADE",98),Event(21,"TRADE",100)]. Current result: HOLD. Correct: HOLD; earlier trade is unambiguously pre-fill.
4. LONG, signal=10, fill=20, entry=100, stop=99, events=[Event(21,"TRADE",98)]. Current result: STOP_TRIGGER_FILL_UNVERIFIED. Correct: stop trigger AFTER fill; executable price still unverified.

These are synthetic counterexamples, not historical Bybit trades. No new net-equity estimate is justified.

## Mandatory replay contract before evaluating 67 trades
- Use ordered exchange event identifiers to establish fill-versus-trade ordering within a millisecond, OR conservatively mark any price-trigger at exactly fill_ms unresolved; never assume `>=` means after fill.
- Persist signal-available time, order-submit time, exchange acknowledgment, actual fill time/sequence, stop trigger time, bid/ask executable exit time, mark-price/liquidation checks.
- Require independent provenance and timestamp coverage for M1 Public Trades/CVD/L50/OI/liquidations; missing values are unavailable, not zero.
- Evaluate LONG and SHORT separately. For 25x isolated require stop-plus-gap safely inside verified liquidation distance; size at 0.25–0.5% account risk and total stop-risk <=1%.
- On common 67-trade sample compare original unchanged baseline with staged entry, cost-aware stop and MFE protection; same costs, no overlapping capital. Never promote previously rejected overlays without independent forward evidence.
- Mark monthly net equity, MTM DD, fills, stop gaps, liquidation counts and MFE as NOT VERIFIED until actual matched event tapes are present.

## Verdict
This run established a specific unresolved fill-boundary defect in the current research guard. The prior 67-trade results remain historical simulation only; do not claim zero live liquidations or improved return. Next engineering action: make exact-fill-timestamp event ordering fail-closed, test fixtures, then connect actual saved tapes and 67 entry timestamps.
