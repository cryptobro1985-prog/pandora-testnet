# HYPE causal execution boundary guard — 2026-11-14 00:33 UTC

Research-only checkpoint. No detector retraining, production edits, or orders.

## New executable result
Added `research/hype_terminal_local_strategy/causal_boundary_guard_research.py` with seven deterministic tests. Local execution: PASS 7 boundary tests.

This guard is deliberately not an execution simulator. It rejects impossible pre-signal fills, ignores bars before entry, and flags partial-entry OHLC bars and simultaneous stop/opposite-confirmation bars as unresolved. It does not turn a candle's high/low into a real fill. Both LOW->LONG and HIGH->SHORT are covered.

## Source provenance
Read directly from this branch:
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`
- `results/HYPE_EVERY_LOCAL_ROBUST_STRATEGY_2026-11-12.md`
- `research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md`

Frozen D250 thresholds unchanged. The 67-trade $100->$531.16 3x result remains an OHLC/model-cost simulation, not a verified tick/mark-price replay. Existing rejected profit overlays remain rejected.

## Blocking evidence for matched execution replay
Need immutable trade-event rows: anchor time, signal availability, order-submission time, fill time/price/quantity, stop trigger, causal opposite-local availability and exit. Join each row to timestamped public trades and bid/ask/L50; mark price for liquidation and funding intervals. Without these, monthly net equity, mark-to-market DD, true stop fills, liquidation count and MFE retention are NOT MEASURED.

## Replay policy
Use a single chronological position ledger, same sample and costs for original baseline and risk-limited variants, no overlapping capital. A touched stop is not a verified fill. Unresolved bars must be replayed with ticks or reported as execution uncertainty, not silently scored. Risk budgets 0.25%-0.5% equity per trade and <=1% aggregate stop risk are hypotheses to test, not achieved safety guarantees.
