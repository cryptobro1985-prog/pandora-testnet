# HYPE causal replay boundary counterexamples — 2026-11-14 00:29 CET

Research-only checkpoint. No new detector fitting, no production changes, no orders. This is a **deterministic codepath counterexample**, NOT a Bybit historical tick replay and NOT a new return estimate.

## Source inspected
`research/hype_terminal_local_strategy/causal_exit_replay_research.py` on branch `research/hype-h1-local-v5-oi-microstructure-20261104`. Its loop requires strictly increasing `ts_ms`, but does **not** check that bar starts after entry availability, nor does it check `available_ts_ms` when recording high/low, MAE, MFE or stop. It checks `available<=ts` only for opposite-confirmation exit.

## Reproducible synthetic test A: pre-entry STOP (LONG)
Inputs: entry LONG=100, stop_pct=.01, exposure=.2, cost_pct=.0025. First row `ts_ms=0, available_ts_ms=60000, low=98, high=102, close=101, opposite_confirmed=false`. Assume entry becomes executable only at `60000` (at the close of this minute). Existing replay uses `low=98` and immediately returns STOP at `min(99,101)=99`; net equity return = 100*.2*((99/100-1)-.0025) = **-0.25%**. It also records 2% MFE from a bar that was not yet executable. This is **not a valid causal fill**. A replay must skip the earlier bar or use post-entry tick slices, never infer its intrabar sequence.

## Reproducible synthetic test B: pre-entry STOP (SHORT)
Entry SHORT=100, same settings, first row `ts_ms=0, available_ts_ms=60000, low=98, high=102, close=99`. Existing replay returns STOP at `max(101,99)=101`, net equity = **-0.25%** and a spurious 2% MFE. Same pre-entry contamination.

## Reproducible synthetic test C: same-bar ambiguity
LONG entry 100; after a valid entry, a minute has low=98.5, high=103, close=102 and a newly available opposite-local signal. The existing code always takes STOP first, and uses `min(99,102)=99`, yielding -0.25% equity. With OHLC only, whether stop occurred before or after confirmation is **unobservable**. Label the outcome `AMBIGUOUS_SAME_BAR` and exclude it from any claimed tick-verified performance; optionally calculate worst/best OHLC bounds as sensitivity, not actual fills.

## New implementation gate (frozen, no fitting)
- Entry `entry_available_ts_ms` must be explicit and <= first executable tick timestamp; for minute bars require `bar_end_ts_ms <= entry_available_ts_ms` bars skipped and a later full bar, or mark partial entry bar as unresolved without ticks.
- Every local signal must carry `signal_available_ts_ms`, distinct from extreme timestamp. No trades based on future-confirmed extreme.
- Stop trigger vs opposite confirmation vs mark-price liquidation: use ordered event timestamps from actual public trades, orderbook/mark where available. If not available, flag unresolved, not an observed zero liquidation.
- LONG and SHORT use distinct bid/ask executable fills, taker fee on entry/exit notional, funding timestamps, gap/slippage scenarios, stop price vs actual execution, and mark-price maintenance-margin threshold.
- Do not reclassify previously rejected MFE overlays as successful; maintain unchanged baseline and compare only on identical, non-overlapping sequential trades.
- Risk budget: 0.25–0.5% equity per trade, total active stop-risk <=1%, computed from stop+fees+slippage; position notional alone does not fix 25x isolated liquidation buffer.
- Before reporting monthly net equity, MTM/closed DD, liquidation count, fills, MFE captured/given back and independent forward results, require a matched trade-ID/timestamp-level execution tape and data coverage manifest.

## Status
**New concrete finding**: two symmetric, fully specified counterexamples show pre-entry OHLC contamination, plus one same-bar stop/opposite ambiguity. This invalidates treating the existing OHLC replay implementation as an execution verifier. It does **not** establish that any of the previously reported 67 trades is actually wrong. The original D250 rule and all frozen thresholds are unchanged. Next step is locate/reconstruct the 67 trade timestamps and join Bybit rich tick/orderbook/mark feeds; where absent, report coverage gaps rather than invent fills.
