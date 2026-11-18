# D250 evidence preflight — 2026-11-18 03:33 CET

Research only; no retraining, production change, or orders.

## Concrete work
Implemented a separate strict evidence-based gate `d250_event_causality_gate.py` alongside the original manifest gate. It requires independently extracted JSONL event evidence for each trade, verifies D250 chronology and frozen thresholds, checks same-side invalidation and opposite-local confirmation before entry for **both STOP and OPPOSITE_CONFIRMED** episodes, and validates file SHA256 and time bounds for M1/Public Trades/mark evidence. Fail closed on missing provenance, missing files, incomplete bounds and absent event evidence.

Local `py_compile` passed. Three synthetic assertions passed: same-side invalidation, already confirmed opposite local, future-dated feature. These are logic tests, not historical trades.

## Important distinction
A hash verifies file identity, not data completeness or authenticity. A claimed `continuous=true` or `raw_tape_validated=true` remains a producer assertion; independent event-level UTC continuity verification is still necessary. The gate deliberately labels passing rows `PRELIMINARY_CAUSAL_PASS`, not executed or profitable trades.

## Result and remaining work
No original 67-trade UTC ledger or independently matched Bybit event files were available to this run. Therefore **zero real trades replayed**; no new net PnL, monthly equity, MTM/closed DD, stop fills, liquidation count or MFE retention is claimed. Next: recover individual ledger and source files, generate verified event evidence, then perform paired LOW→LONG and HIGH→SHORT fills with identical fees/funding/slippage and 0.25–0.5% equity stop risk, 1% aggregate risk.

Frozen D250 unchanged: rev_atr>2.0840049433824706, trade_ratio5>0.2727842248141979, flow15<0.4504731635235635. Previously rejected overlays remain rejected.
