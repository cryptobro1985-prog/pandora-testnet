# HYPE D250 known-opposite vs STOP ordering gate — 2026-11-18 16:30 CET

Research only; no orders, production edits or detector retraining.

## Concrete finding
Direct source inspection of `d250_trade_replay_manifest_gate.py` found that `opposite_confirmed_utc` was parsed and checked only when `exit_reason=OPPOSITE_CONFIRMED`. A STOP row could therefore be accepted even when its supplied opposite-local confirmation occurred before entry or before its stop exit. This violates the baseline's first-causal-exit chronology: a known confirmed opposite-local event should terminate the position before a later stop.

## Change
- When supplied, parse `opposite_confirmed_utc` for BOTH exit reasons.
- Reject opposite confirmation at/before entry with `OPPOSITE_PRECEDES_SIGNAL`.
- Reject STOP exit strictly after a known opposite confirmation with `STOP_AFTER_OPPOSITE_CONFIRMATION`. Same-timestamp events are deliberately not ordered without finer event evidence.
- Preserve STOP before a future opposite confirmation as eligible; preserve requirement of opposite timestamp for OPPOSITE_CONFIRMED.
- Added three synthetic chronology regression cases to existing test file. Tests are committed but **not independently executed in this run**. No claim of passing suite.

## Evidence and limits
Frozen D250 thresholds unchanged. The original 67-trade May-inclusive UTC ledger, May M1 data and matched event tape remain missing, so the gate fix does not establish actual execution PnL, fills, MFE retention, liquidation or MTM drawdown. Manifest-provided timestamps and COMPLETE labels are not independently verified exchange evidence.

Next: execute regression suite; recover immutable signal/position ledger and matched tape, replay identical May-inclusive cohort with stop-first uncertainty bounds and realistic fees, funding, gap/slippage, liquidation distance and risk-based sizing (0.25–0.5% per trade, <=1% aggregate stop-risk). Do not promote previously rejected MFE overlays without new unseen-forward evidence.
