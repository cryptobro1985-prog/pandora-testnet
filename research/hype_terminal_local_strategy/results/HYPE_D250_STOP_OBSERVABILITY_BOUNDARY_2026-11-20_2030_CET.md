# HYPE D250 — stop observability boundary (2026-11-20 20:30 CET)

Research-only checkpoint. No production or detector changes. Frozen D250 unchanged.

## New source audit
Inspected actual branch blobs:
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md` (blob 54865475546c10cd555199c65a2a81ce0f14aab7)
- `quote_gate_followthrough_audit_20261120.py` (blob aee... not used; actual code inspected directly)
- `results/HYPE_D250_POST_ENTRY_STOP_FOLLOWTHROUGH_2026-11-20_1934_CET.md`.

## Newly isolated execution-identification problem
The current `audit()` marks `NO_OBSERVED_STOP` whenever none of the **sampled** later Mark quotes crosses the stop. This is not evidence that a stop was not triggered in the unsampled intervals. A transient Mark excursion below/above the stop between quotes can trigger a real stop and then recover before the next sample. Thus 'no observed stop' cannot be counted as a survived trade, and especially cannot be treated as a win. Without complete exchange-side trigger observations, the proper status is **STOP_TRIGGER_UNOBSERVABLE**. This affects LONG and SHORT symmetrically, although the executable exit side differs (LONG bid, SHORT ask).

The implementation also uses Python `assert` for essential input validation. Running Python with `-O` disables asserts, allowing malformed timestamps, invalid quote sides, or impossible stop fractions to pass. Replace with unconditional `ValueError`/explicit reject paths before using this as a replay component.

## Two deterministic counterexamples (not Bybit history)
LONG entry ask 100.10, stop 99.099. Sampled Mark: 100.0 at t=1, 100.2 at t=3. Unobserved Mark 98.8 at t=2 would have triggered a real stop. Current code returns `NO_OBSERVED_STOP`, despite the same sampled inputs being compatible with both a stop and no stop.

SHORT entry bid 99.90, stop 100.899. Sampled Mark: 100.0 at t=1, 99.8 at t=3. Unobserved Mark 101.2 at t=2 would have triggered a real stop. Again the sampled observations cannot distinguish stop from no stop.

These are observational-equivalence demonstrations, not fabricated historical trades. They prove an information limitation, not a measured frequency of missed triggers.

## Mandatory fail-closed replay contract
- An entry is only eligible after frozen D250 causal signal timestamp and fresh, validated post-signal bid/ask/Mark/L50; no retroactive rejection based on future quotes.
- After entry, absence of sampled stop breach is `UNRESOLVED` unless the full relevant Mark trigger tape is verified continuous through exit. Do not infer an execution from best bid/ask alone; depth, latency, order quantity, partial fills and slippage are required.
- With missing Mark trigger segments, report lower/upper outcomes as unidentified; do not compute a single net equity, liquidation count or MFE-captured number.
- For stop fills, match trigger time to the next executable opposite-side depth and fee/funding schedule, and verify liquidation distance from contemporaneous Mark, margin tier and maintenance margin.
- Apply risk 0.25%-0.5% of equity, aggregate stop risk <=1%, minimum-order feasibility and capital lockout. Same 67-trade chronology for unchanged baseline and alternatives; report missing events as missing, not zero.
- Existing rejected MFI+flow and ATR-trail exit overlays remain rejected.

## What this iteration did / did not do
Completed a new deterministic causal observability audit against the actual existing source code. Historical matched trade executions: 0 newly verified. Monthly net equity, MTM drawdown, stops, liquidations, MFE giveback and independent forward performance: **not identified** from this audit. No detector retraining, no live orders, no production changes.

## Next checkpoint
Recover the exact 67 UTC entry IDs and continuous exchange Mark trigger tape plus L50/fee/funding metadata; classify each event as `VERIFIED`, `CENSORED`, or `MISSING` before attempting a risk-adjusted strategy comparison.