# HYPE post-local latency and causality checkpoint — 2026-11-15 01:35 CET

Research only. Existing branch; no detector retraining, no live orders, no production changes.

## Direct source audit
Read the original frozen D250 walk-forward, asymmetric 67-trade simulation, unified entry/MFE contract, and the two existing execution guards directly from this branch. Frozen entry: D250 rev_atr > 2.0840049433824706, trade_ratio5 > 0.2727842248141979, flow15 < 0.4504731635235635. LOW->LONG and HIGH->SHORT only. 71 accepted, 67 fully finalized opposite-local paths, 4 censored. The 67-trade 3x/5x account simulations are not tick-level execution evidence.

## New defect found
event_ordered_exit_guard_20261114.py rejects observations when available_ts_ms > ts_ms. In real event ingestion, exchange event time normally precedes local receive/availability time, so the condition rejects legitimate delayed market messages and may silently bias which executions are replayable. Its implicit same-clock requirement is not established. It also does not separately require that an observed trade occurred after the position was actually entered. This is a research replay integrity defect, not evidence of wrong historical fills.

## New code and executed tests
Added latency_aware_event_gate_20261115.py, with explicit exchange_ms and received_ms and optional entry_exchange_ms. It handles observed latency without pretending that event time and knowledge time are identical; rejects out-of-order exchange timestamps pending reconciliation; excludes pre-entry prints when entry_exchange_ms is known; and stops MFE on first observed stop trigger or opposite-local availability notification. Six deterministic synthetic assertions executed locally and passed: delayed LONG stop-first, delayed SHORT stop-first, causal opposite-local signal, late-received pre-entry trade exclusion, invalid timestamp rejection, and exchange reorder rejection.

Reproduce: python research/hype_terminal_local_strategy/latency_aware_event_gate_20261115.py

## Strict limitations
This is NOT a complete event replay or order execution model. Exchange/receive timestamps must be clock-synchronized and source-specific sequence semantics validated. Real historical files may have missing receive timestamps; do not fabricate them or assert latency validation in that case. The gate does not validate full start-to-exit coverage, venue book depth, order queue, stop trigger-to-fill delay, funding, mark-price liquidation, or net equity. Opposite-local availability is a decision event, not an executable fill. The test code is exploratory and should not replace the original baseline without independent data and tests.

## Next concrete replay
Recover exact 71 signal timestamps and corresponding raw Bybit Public Trades, CVD, L50, OI, liquidation, mark/index, and funding artifacts; label missing channels explicitly. Join on exchange timestamps plus known availability, independently LOW/LONG and HIGH/SHORT. Verify contiguous coverage and stop trigger->fill, then compare frozen original vs risk-based 0.25%-0.5% equity risk, <=1% aggregate stop risk, same fills/fees/slippage/funding and no double-use of margin. Account for all 4 censored signals at the sample end. Report monthly net equity, closed and mark-to-market DD, MFE captured/given back, fills/stops/liquidations, and untouched forward. Previously rejected protection overlays remain rejected pending new independent evidence.

## Verdict
A new reproducible causality guard was added and its synthetic tests passed. No matched rich event replay completed this run; no new live-validated PnL, MFE, stop-fill, or liquidation claims are made.
