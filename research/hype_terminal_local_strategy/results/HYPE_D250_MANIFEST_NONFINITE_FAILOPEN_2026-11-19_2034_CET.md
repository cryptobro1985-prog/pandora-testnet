# HYPE D250 — strict manifest numeric audit, 2026-11-19 20:34 CET

Research-only; frozen D250 unchanged. This checkpoint addresses a specific false-PASS condition in `entry_execution_manifest_gate_20261119.py`. It does **not** claim matched historical fills.

## Executed local regression
A separate strict Python audit was executed locally with 15 deterministic assertions passing: one valid manifest, 12 single-field mutations, duplicate-ID and missing-fields cases. Mutations tested nonfinite entry price, stop, funding, fee and mark-min; negative gap; invalid exit reason; confirmation after entry; mark crossing liquidation; stop beyond liquidation; missing quote stream; and unverifiable source hash. The existing gate can silently accept NaN because Python comparisons against NaN return false. A negative max-gap also passes the original `>60000` check.

## New reproducible counterexample
Use the original module's `audit` on its own valid `base` record, substituting `entry_vwap=float('nan')` or `funding=float('nan')` or `max_quote_gap_ms=-1`. These values can be marked replay-eligible despite invalid provenance. Correct screening requires `math.isfinite` for *all* numeric fields, nonnegative gaps, valid exit reasons and strictly causal timestamps. A screening PASS is not an execution fill validation.

## Risk implication
Never use a manifest-only PASS to claim zero liquidations, valid stop-first precedence, realistic fills, or MTM drawdown. A quote-event replay requires individual ordered UTC bid/ask, mark and L50 events, trigger-source metadata, margin tier, actual fills and funding. Keep all unknown or missing streams UNKNOWN rather than imputing them. The original 67 sequential trades, 71 accepted D250 signals and 411 every-local trades are distinct samples and cannot be merged without ID/UTC matching.

## Status
15 local deterministic assertions passed; **0 real historical trades newly replayed**. No new net PnL, drawdown, fill, liquidation, or MFE claim. No detector retraining, production changes, or real orders. Existing rejected profit-protection overlays remain rejected.

## Next executable milestone
Recover 67 individual UTC trade paths and match each to preserved rich-data files by SHA; count exact matches and failures, then replay original baseline and conservative 0.25%-0.5% equity stop-risk on identical chronological samples with funding, fees, slippage, liquidation precedence and non-overlapping capital.
