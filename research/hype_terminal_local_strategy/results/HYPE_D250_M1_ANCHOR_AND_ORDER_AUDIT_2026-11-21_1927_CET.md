# Frozen D250 — raw M1 gate anchor/order audit (2026-11-21 19:27 CET)

Research only; no orders or detector retraining.

## Reproduced by direct source inspection
Inspected frozen H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md, HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md, and d250_raw_m1_preentry_gate_20261121.py in the requested branch.

The current M1 audit filters rows with `t0 < bar.utc < entry_utc`, initializes expected timestamp to `t0+1 minute`, and then loops over rows **in input CSV order**. It does not sort by UTC. Therefore an otherwise complete but out-of-order M1 file produces M1_GAP_OR_DUPLICATE, a false rejection; conversely, a correctly sorted file can still pass without evidence about what happened inside the anchor minute after the actual local extreme.

More importantly, `local_extreme_utc` is required to be minute aligned, but the detector report describes the actual extreme, not whether that timestamp is the **open** of an M1 candle or the exact trade time of the extreme. The gate entirely excludes the candle starting at `t0`. If the extremum was printed early in that minute and then exceeded later within that minute, the excluded candle cannot prove or disprove an extension. OHLC alone also cannot establish the order of the high/low prints within a candle.

## Concrete deterministic counterexample
LONG; original LOW price 100; anchor 12:00:00; M1 candle 12:00–12:01 low 99.5; every subsequent minute through entry 16:11 has low >=100. Under the existing filter, the 12:00 candle is excluded, and the LOW_EXTENDED_BEFORE_ENTRY condition is never triggered. Whether 99.5 was before or after the anchor's 100 print cannot be established from M1 OHLC. Correct status is INDETERMINATE_ANCHOR_TICK_ORDER, not PASS.

Another counterexample: two otherwise valid consecutive bars supplied as [12:02, 12:01] trigger a gap despite full chronological coverage. Normalize and validate UTC order before the audit; never silently treat an out-of-order file as missing historical data.

## Required remediation / next replay
1. Define anchor provenance explicitly: exact trade UTC and price, H1 strict pivot candle interval, and whether the source is trade ticks or M1 OHLC.
2. Include the anchor M1 bar in the coverage audit. Without tick-level order inside the anchor candle, mark uncertain same-minute extension as INDETERMINATE, not pass or a fabricated invalidation.
3. Sort M1 by UTC, reject duplicate starts, enforce one-minute continuity and close<=entry, and preserve a stable SHA256 of the raw source.
4. For D250 eligibility, require the frozen thresholds and no causally known same-side extension through actual fill time, not merely through signal time.
5. Pair the original 67 trade timestamps with archived Bybit ticks/L50/funding and actual execution-cost assumptions. Do not infer stops, liquidation count, net equity or MFE from M1-only validation.
6. Compare frozen 1% adverse cut with 0.25% and 0.5% equity-risk sizing only on identical eligible trades and matched execution data. Preserve rejected flow/MFE trails and K0/K1 overlays as rejected.

## Status
This is a source-level counterexample and an execution-data readiness checkpoint, **not** a 67-trade event replay. No new performance, fills, liquidation or OOS claims. Frozen D250 remains unchanged. No production changes or orders.
