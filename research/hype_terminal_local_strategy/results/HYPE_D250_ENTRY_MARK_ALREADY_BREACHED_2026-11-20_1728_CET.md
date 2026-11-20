# D250 quote-side stop replay: entry-time trigger and mark/quote dislocation audit
Date: 2026-11-20 17:28 CET. Research only; no live orders.

## Frozen reference
The D250 entry thresholds remain rev_atr > 2.0840049433824706, trade_ratio5 > 0.2727842248141979, side-normalized flow15 < 0.4504731635235635, at D250, no same-side invalidation. This audit does NOT retrain or reclassify snapshots.

## Newly identified replay boundary
Inspected `quote_side_stop_scenario_20261120.py` at branch head 09d9e00d. The quote-side model enters at first observation strictly after signal, then begins evaluating Mark Price stop triggers only from the *second* post-signal observation. Therefore the first executable quote can already have Mark Price beyond the stop reference, or Mark Price may become inconsistent with the bid/ask quote, and the model cannot establish a realistic pre-entry stop geometry. It also allows arbitrarily long delay between signal and first quote because the gap check is only between successive supplied ticks, and has no spread cap, depth, funding or liquidation checks.

## Reproducible counterexample (synthetic; not Bybit fills)
Call `replay("LONG", 0, [Tick(1000000,99.9,100.1,98.0), Tick(1001000,99.8,100.0,97.9)])`.
The existing routine buys at ask 100.1 despite 1000-second signal-to-quote delay. It computes stop = 99.099 and then triggers on the second quote with Mark 97.9, selling at bid 99.8. Model net notional return = (99.8/100.1 - 1) - 0.0015 = -0.004497002997 (~-0.450%). The execution is not verified. A 1000-second blind interval is not evidence of immediate causal execution, and Mark Price 98.0 was already below the derived stop at the first observation.

Second counterexample: `replay("SHORT",0,[Tick(1000,99.9,100.1,102.0),Tick(2000,99.9,100.1,102.1)])`. It sells bid 99.9, computes stop 100.899, even though entry Mark 102.0 is already beyond the short stop. The routine nevertheless treats it as a newly entered short and exits at ask 100.1, net return = (99.9-100.1)/99.9 - 0.0015 = -0.003502002002 (~-0.350%). These are deliberately adversarial quote/mark sequences, not evidence that Bybit behaved this way.

## Fail-closed promotion requirements
1. Require the earliest timestamped quote AFTER confirmed signal and bound signal-to-first-quote latency; do not backdate execution.
2. Require valid entry Mark/quote geometry; if stop would already be breached at entry, reject rather than fill and retroactively stop.
3. Require source identity, continuity and freshness for Mark, bid/ask and L50 depth; mark-vs-quote divergence must be measured, not assumed zero.
4. Compute executable stop fills from opposite-side quote and sufficient book depth, with slippage/gap stress; verify liquidation boundary and funding independently.
5. Run identical events for baseline and alternatives, preserve previously rejected exit overlays as rejected. No promotion until 67 per-trade UTC trajectories and independent forward are reconciled.

## Evidence and status
Source is the existing Python scenario module, not an independently reconstructed Bybit tape. The calculations above are direct arithmetic and the test inputs are reproducible. No historical fills, month-by-month net equity, MTM drawdown or zero-liquidation claim can be derived from this audit. Frozen D250 unchanged; no production changes or real orders.
