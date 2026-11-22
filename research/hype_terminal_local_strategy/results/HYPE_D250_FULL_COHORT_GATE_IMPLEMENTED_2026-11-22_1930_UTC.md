# HYPE D250 full-cohort gate implementation — 2026-11-22 19:30 UTC

Research-only. No orders, production edits, detector retraining, or threshold changes.

## Actual change this iteration
Inspected frozen D250 walk-forward, asymmetric risk report, prior 71/67 censoring audit, and the actual branch-specific `d250_trade_replay_manifest_gate.py`. Added companion executable `research/hype_terminal_local_strategy/d250_full_cohort_gate.py` without changing the original 67-trade gate or frozen reports.

The companion accepts CLOSED_STOP, CLOSED_OPPOSITE, OPEN_AT_CUTOFF, UNKNOWN_DATA statuses, so the 4/71 non-finalized next-opposite trajectories can remain censored rather than being assigned invented exits. It requires a 71-row uniqueness/size check; exact frozen D250 thresholds; side matching LOW->LONG/HIGH->SHORT; D250 >= extreme+250 minutes; entry >= max(H1 confirmation, D250 signal, feature availability); complete declared opposite and same-side ledger coverage; independently attributable source hash; and for OPEN rows, observed bid/ask/mark with timestamps. Unknown-data rows cannot be silently assigned zero PnL.

It explicitly labels passing rows MANIFEST_ELIGIBLE_NOT_VERIFIED. The code includes deterministic synthetic self-tests for an open row, fabricated exit, feature latency and side mismatch. These are *included*, but were not executed against exchange data in this run.

## Important limitations
This is a new functional validator, **not** a Bybit event replay. The `COMPLETE` labels and source hashes remain assertions until matched against actual immutable event tapes. The gate does not calculate fills, funding, mark-price liquidation, equity curves, stops, same-side invalidation event contents, or overlapping capital; these must be independently reconstructed before trading conclusions. In particular, requiring a complete same-side ledger label is not the same as proving no invalidation. The original 67 completed-trade historical figures are unchanged and not interchangeable with the full 71 cohort.

No historical matched M1 Public Trades/CVD/L50/OI/mark/quote tape was newly verified in this run. No new monthly net equity, MTM DD, MFE capture, liquidation count, or independent forward performance can be claimed.

## Next executable step
Populate the 71-row manifest with original UTC signals and source hashes from archived research/Actions artifacts; independently validate source event ledgers and same-side invalidation, then run the gate. Replay all accepted signals chronologically with actual bid/ask/mark and stop trigger ordering, using identical tape/costs for unchanged baseline vs 0.25%-0.5% risk sizing and <=1% aggregate stop risk. Preserve rejected MFE overlays unless genuinely independent forward evidence changes the conclusion.

Commit with gate: 0b669b4049e303ff03bfffd126e7f6a9e3582e4c.
