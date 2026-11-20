# HYPE D250 causal quote-side entry gate — 2026-11-20 18:29 CET

Research-only. Frozen detector and baseline remain unchanged. No real orders.

## Verified source
Read existing `quote_side_stop_scenario_20261120.py`, frozen `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`, and prior `HYPE_D250_ENTRY_MARK_ALREADY_BREACHED_2026-11-20_1728_CET.md` directly on target branch.

## New reproducible code
`research/hype_terminal_local_strategy/entry_quote_failclosed_gate_20261120_1829.py`
introduces an independent, quote-only, fail-closed **entry eligibility** check for LONG and SHORT. It does not replace the original baseline or classify detector snapshots.

Enforces:
- strictly post-signal first quote, bounded signal-to-quote delay (exploratory 5000 ms, NOT calibrated);
- ordered quote timestamps and interquote gap <=60000 ms;
- bid <= ask, finite positive bid/ask/mark;
- spread/mid <=0.5%, mark/mid divergence <=1% (exploratory safety gates, NOT proven edge);
- entry-side executable quote (LONG ask, SHORT bid);
- entry Mark strictly on safe side of derived 1% stop (LONG mark > stop, SHORT mark < stop);
- explicit `verified_fill=False` even when quote-only gate passes.

## New deterministic synthetic cases
Seven tests embedded in module: stale LONG quote, SHORT mark dislocation, LONG already-breached stop, SHORT already-breached stop, wide spread, eligible LONG, eligible SHORT. **Tests added but not independently executed in this checkpoint.** Expected outcomes are asserted in code. Synthetic data are not historical Bybit observations.

## Important limitation
Entry Mark/quote divergence can fail the gate before stop-breach evaluation; this is conservative. No D250 threshold recomputation, depth-based fill, order-book queue, Mark Price/liquidation trajectory, fees/funding reconciliation, MFE preservation or historical replay is claimed. A 5000 ms quote freshness cap is a hypothetical risk policy and must not be retrofitted as a profitable historical filter.

## Next required evidence
Find 67 entry timestamps and raw UTC matching Bybit quote/Mark/L50/funding sources; verify hashes and clock alignment. Replay original baseline and risk 0.25%-0.5% alternatives on the **same** events, with independent unseen forward; report fills, non-fills, monthly equity, MTM and closed DD, stop gaps, liquidation distance, and causal MFE giveback. Missing source => mark unavailable, not zero-impute.

## Status
New fail-closed research code and reproducible scenarios committed on existing branch. Historical fills verified: **0**. No revised net-return, zero-liquidation, or MFE claim. No detector retraining, production modifications, new branches, or orders.
