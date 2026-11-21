# HYPE D250 execution replay: tracked artifact inventory — 2026-11-21 15:28 CET

Research only. No orders, retraining, production changes, or threshold changes.

## Concrete inspection
Read branch HEAD 0c0cb350a6148b28371937b78e88cec8204bc939 and recursively enumerated its Git tree (1,091 tracked paths, GitHub tree response not truncated). Reviewed original frozen D250 and asymmetric-risk reports, the previous structural-stop audit, and the actual frozen eligibility and trade replay manifest gate source.

The tracked tree contains **no CSV, Parquet, JSONL, SQLite, gzip, or ZIP trade-level Bybit Public Trades/L50/OI/liquidation tape under research/hype_terminal_local_strategy/**. There is no tracked real 67-trade CSV manifest in that directory. CSV trade files elsewhere under research/hype_movement_signature are for a different experiment and MUST NOT be silently substituted. The tree has a handful of compressed false-local signatures under research/hype_work_handoff_2026-11-09, which are not execution tapes. This is a **tracked Git tree observation**, not proof that historical data do not exist in GitHub Actions artifacts, Git LFS, external storage, or a database. No such external archive was fetched here.

## New causal coverage gap found in source
The frozen eligibility gate (frozen_d250_trade_eligibility_audit_20261116.py) explicitly requires same_side_extreme_before_signal == False and opposite_local_before_signal == False. By contrast d250_trade_replay_manifest_gate.py checks only the entry-to-exit opposite-local ledger and does **not** require independently reconstructed pre-entry same-side-extreme and opposite-local ledgers. Consequently an otherwise complete-looking manifest can be declared ELIGIBLE_FOR_EVENT_REPLAY even if a newer LOW before LONG entry or newer HIGH before SHORT entry invalidated the D250 candidate. This is a **source-level logical coverage gap**, not an observed erroneous historical fill. Do not treat a manifest PASS as proof of frozen D250 eligibility.

## Unchanged frozen facts
D250: 71 accepted historical episodes, 67 with finalized opposite local; OOS 50/50 on tested periods; median causal opposite-local MFE giveback 61.2%. These are not execution-verified fills. Asymmetric paper baseline: 67 sequential simulated trades, 22 modeled fixed-cut exits, 3x $100 to $531.16, closed DD 18.56%; 5x closed DD 29.36%. No MTM, tick stop fills, funding reconciliation, or independent live result.

## Replay blocker and next concrete action
1. Recover original 67 timestamped frozen entries and local identifiers plus exact immutable data locations; do not synthesize them.
2. Reconstruct both pre-entry local-state ledgers through D250 and opposite-local ledger through exit. Require absence of same-side invalidation and premature opposite local from independently time-stamped events.
3. Join Bybit Public Trades, quote/L50, mark, liquidation and funding evidence per trade. Missing source => UNKNOWN, not zero.
4. Replay the same chronology with original 1% cut baseline and 0.25%-0.5% equity stop-risk alternatives; enforce 1% aggregate stop-risk, no overlapping capital; separately report LONG/SHORT, fills, stop gap, liquidation precedence, monthly net equity, closed and MTM DD, MFE retention, and genuinely unseen forward.
5. Keep prior rejected profit overlays rejected unless genuinely independent data support a frozen alternative.

No performance claim or liquidation count is made in this checkpoint. No event-level replay could be validly run from the identified tracked files alone.
