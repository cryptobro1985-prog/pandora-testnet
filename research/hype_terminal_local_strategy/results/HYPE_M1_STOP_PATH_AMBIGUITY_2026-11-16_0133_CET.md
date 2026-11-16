# HYPE M1 stop-path ambiguity checkpoint — 2026-11-16 01:33 CET

Research only; no orders, no detector retraining. Frozen D250 unchanged.

## New executable result
Added `research/hype_terminal_local_strategy/m1_stop_order_ambiguity_replay_20261116.py` (commit `1ad3f5eeaf859e08300d285ba7aacee3101a3c71`). This is a **fail-closed M1 replay adapter**, not a claim of real execution. It accepts time-stamped individual episodes with M1 OHLC, distinguishes LONG stop below entry and SHORT stop above entry, detects stop touch and opening price beyond the stop, reports MFE/MAE **upper bounds**, rejects missing minute coverage, and refuses to invent fill price or intrabar ordering. Input contract and four synthetic cases are embedded in the file. Local/GitHub Actions execution of the committed file is **not verified** in this checkpoint.

## Concrete analysis
For a synthetic LONG entered at 100 with stop 99, M1 O=100 H=103 L=98 C=102 touches both favorable high and adverse stop in the same minute. An OHLC-only engine that reports +3% MFE **before** the stop or executes the stop at exactly 99 assumes an unknown event order/fill. Correct classification is STOP_TOUCHED_FILL_UNKNOWN. A minute opening at 98 with stop 99 is a gap-through scenario: an exact 99 fill is unsupported. A missing minute invalidates continuous replay; an untouched stop is only NO_STOP_TOUCH_IN_M1, not proof of a successful opposite-local fill. Symmetric SHORT logic uses high>=stop and open>stop.

## Provenance and constraints
Read existing frozen D250 walk-forward and asymmetric-risk reports and `event_path_provenance_gate_20261116.py`. The 67 simulated closed trades remain unjoined to per-trade Bybit event tape. The earlier 157,375-row M1 artifact with five missing minutes is not bid/ask, private fills, L50 or mark-price event evidence. Therefore exact fill, stop slippage, liquidation distance, funding, MTM DD, net monthly equity, and realized MFE capture are **UNKNOWN**, not zero. The 71/71 historical accepted-local statistic is not 71 proven trade executions; May sealed holdout is not later chronological forward.

## Next executable action
Locate the original episode ledger and recovered M1 artifact, map entry and exit times by episode ID and direction, and run the adapter only on uninterrupted matching windows. Separate stop-touched and no-stop-touch cases, then require event-tape proof before assigning execution prices. Compare original 1% stop baseline and risk-sized 0.25%–0.5% variants on identical episodes and fees; do not revive rejected MFE overlays without independent forward evidence.

No new branch, production changes, live orders, or new thresholds.
