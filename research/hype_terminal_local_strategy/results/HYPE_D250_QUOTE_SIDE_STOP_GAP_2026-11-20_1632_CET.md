# HYPE D250 — quote-side stop-gap scenario checkpoint — 2026-11-20 16:32 CET

Research-only; frozen D250 thresholds unchanged. No new detector, orders, production changes, or claims of historical fills.

## New concrete work
Added `quote_side_stop_scenario_20261120.py`, an independent deterministic quote-side scenario replay with four synthetic assertions. It uses the first observation strictly **after** signal availability, LONG entry ask/exit bid, SHORT entry bid/exit ask, Mark Price stop trigger, and first subsequent observed quote as the stop-market execution *scenario*. It fails closed on invalid/crossed quotes, missing post-signal observations, non-monotonic timestamps, and gaps over 60 seconds. It does not assert a real order would fill at displayed top-of-book: L50 depth, latency and exchange matching remain unverified. Test cases are included but CI execution has not been verified.

## Quantitative stop-gap counterexample (synthetic, NOT historical HYPE)
LONG signal at t=0; first post-signal quote t=1000 ms bid=99.9, ask=100.1, mark=100.0. Enter at 100.1; 1% adverse-price stop = 99.099. Next quote t=2000 ms bid=98.5, ask=98.7, mark=98.6. Mark triggers stop, but first displayed executable bid is 98.5. Gross loss per notional = (98.5/100.1)-1 = -1.5984%; after 0.15% assumed round-trip fees = -1.7484%. Gap past trigger is 0.5984% of entry. For $100 equity and $15.87 nominal, modeled loss is ~$0.2775, below $0.50 *in this specific scenario*, but no guarantee for a larger gap. The stop does not cap actual losses at 1% of price.

SHORT example: first post-signal bid=99.9, stop=100.899; later mark=101.9, ask=102.0. Buy-to-cover at ask implies (99.9-102)/99.9=-2.1021% gross and -2.2521% after fees. Gap past stop is ~1.1021% of entry. This demonstrates asymmetric short-side execution even when the same 1% stop rule is applied.

## Interpretation and next required evidence
Frozen D250 71/71 first accepted signals and 67 completed simulated swings do not imply verified bid/ask fills or observed zero liquidations. The quote scenario code does not verify market-depth capacity, funding, margin, or opposite-local exit. Do not promote its synthetic tests to historical performance. Prior rejected MFE overlays remain rejected. For matched historical replay, recover per-trade UTC signal timestamps and actual Bybit mark, bid/ask, L50 and funding series; require source hashes and source-specific sequence continuity. Report LOW/LONG and HIGH/SHORT separately, comparing the identical baseline against conservative risk and exit variants, including monthly equity and MTM DD only when data suffice.

## Provenance
Sources: `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`, `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`, and `execution_event_integrity_gate_20261120.py`. No new historical per-trade tape recovered in this iteration.
