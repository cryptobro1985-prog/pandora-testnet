# HYPE D250 — nonfinite execution cost / mark replay gate (2026-11-21 12:35 CET)

Research only; frozen D250 unchanged; no production or orders.

## New source-level finding
Inspected `entry_execution_manifest_gate_20261119.py`. It parses fee/funding with `float()` but does not require finite values. IEEE-754 NaN can bypass `min(fee_entry,fee_exit)<0`; funding NaN/Infinity passes the plain `float(funding)` conversion. Mark ranges and prices also lack a comprehensive finite-number check. This means a syntactically complete manifest can be declared replay-eligible despite undefined costs or marks. This is a deterministic input-validation flaw, **not** evidence of a corrupt historical Bybit trade.

## Reproducible mitigation
New standalone `finite_execution_manifest_gate_20261121.py` enforces finite entry/stop/liquidation/mark/fee/funding values, nonnegative fees, ordered event times, nonnegative and <=60s gaps, positive prices, proper stop-before-liquidation geometry, ordered mark range, and required stream counts. Nine synthetic assertions are included in the file; CI execution has not been verified. Existing replay baseline and original gate remain unchanged.

## Implications
Do not mark any of the 67 baseline trades as matched, cost-complete or liquidation-free solely on the old manifest gate. Apply the new finite supplement and original gates together, then independently verify source hashes, UTC quote/mark/L50/Public Trades tapes, event sequence, actual fills, funding timestamps, maintenance tiers and gap/slippage. NaN/Infinity must block the trade, never be zero-imputed. Missing L50/OI/liquidation must remain missing, not fabricated.

## Replay status
No matched 67-trade quote/mark event tape was established in this iteration. Therefore no new monthly net equity, MTM DD, stops, fills, MFE retention, liquidation count or independent forward claims. Baseline 67 sequential trades / 0.15% cost remains historical simulated evidence only, not execution validated. Rejected tight trails and flow/MFE overlays remain rejected.

## Next execution step
Locate source manifest with all 67 trade IDs, pair each with event-tape hash and causal first executable bid/ask, run original + finite gate, report matched/unmatched counts and only then compare fixed baseline with 0.25%-0.5% equity stop-risk and <=1% aggregate risk under identical fee/funding/slippage and no overlapping capital.
