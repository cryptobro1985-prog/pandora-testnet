# Frozen D250: opposite-local ledger coverage correction
Date: 2026-11-22 UTC. Research only; no live orders.

## Actual code change
Updated `research/hype_terminal_local_strategy/d250_full_cohort_gate.py` on the existing research branch. Opposite-local ledger must now start at or before `local_extreme_utc`, not merely at `entry_utc`. The incomplete-window check uses the same extreme-origin requirement. The synthetic passing fixture now covers from original extreme. Two regression assertions cover (a) truncated ledger starting at D250 and (b) opposite-local event at T0+200m before entry T0+251m. These are synthetic checks only; execution of the tests and real cohort replay have not been verified in this run.

## Why this matters
The frozen entry rule explicitly requires that the opposite local has not occurred before D250. An event ledger beginning at D250 cannot prove that absence. Example: LOW at T0, opposite HIGH K2-available at T0+200m, D250 at T0+250m. A truncated ledger can falsely mark the LONG eligible. The new gate blocks such truncated coverage and separately blocks an explicitly recorded pre-entry opposite event. A self-reported COMPLETE coverage flag remains insufficient without independent tape validation.

## Unchanged research baseline
Frozen D250 thresholds rev_atr>2.0840049433824706, trade_ratio5>0.2727842248141979, side-normalized flow15<0.4504731635235635. Previously reported 71 accepted historical signals, 67 finalized opposite-local trajectories, four censored; no change to those claims. No new PnL, MTM DD, stop-fill, liquidation or MFE-capture results are claimed.

## Next reproducible step
Recover actual 71-row UTC cohort and exchange-derived opposite-local ledger from T0 through observation cutoff, independently verify file hashes and first opposite K2 availability, then run this gate and event-aligned bid/ask/mark replay with fee/funding/slippage and risk sizing at 0.25%-0.5% equity per trade. Block any cohort row without raw-data provenance. Do not promote rejected MFE overlays absent independent forward evidence.
