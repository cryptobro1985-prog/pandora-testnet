# HYPE D250 execution gate: fail-open stop / coverage audit — 2026-11-17 10:30 CET

Scope: existing frozen D250, no training, no orders, no production modifications.

## Source inspected
`research/hype_terminal_local_strategy/d250_trade_replay_manifest_gate.py` in the specified research branch (blob aef3998b5a661121fb315f22a6cc6298eb01e87d), and `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`.

## New reproducible finding (static executable-path audit)
The gate's REQUIRED fields include `entry_price` and `exit_price`, but **no stop_price, stop_order_utc, stop_trigger_utc, stop_fill_utc, mark_price evidence, execution fee, slippage, funding, position quantity, maintenance margin, or liquidation fields**. A row with exit_reason STOP, a positive arbitrary exit_price, and a claimed COMPLETE tape passes those specific checks. The gate does not check whether a stop was placed, crossed, filled, or priced on the correct side. The existing output label ELIGIBLE_FOR_EVENT_REPLAY must never be interpreted as validated stop execution.

Additionally `local_extreme_utc <= h1_confirmed_utc <= d250_signal_utc <= entry_utc <= exit_utc` accepts equality at signal/entry and entry/exit, while the opposite-local exit check enforces strict inequalities. A same-timestamp signal and fill can therefore pass without event-sequence evidence. `m1_coverage/public_trades_coverage/mark_coverage == COMPLETE` are unchecked claims.

## Reproduction (zero historical rows required)
Read the source and verify:
1. `REQUIRED` omits stop price and execution events.
2. `audit()` only checks exit_reason membership in STOP/OPPOSITE_CONFIRMED and entry/exit prices >0.
3. For STOP, no opposite confirmation is required (correct); **but no stop-trigger/fill evidence is required either** (not sufficient for replay).
4. All coverage assertions are literal strings, not independently matched tape hashes or coverage windows.

## Concrete risk consequence
A 1% adverse-price cut cannot be treated as a guaranteed maximum realized loss. With assumed 0.15% round-trip costs and 0.5% gap reserve, exposure for 0.25% equity risk is <= 0.25/(1+0.15+0.5)=0.151515x equity; for 0.5% risk <=0.303030x. These are scenario caps, not empirically validated fills. No liquidation count or MTM drawdown is estimable from this gate.

## Required next trade-level replay acceptance conditions
For each of the 67 candidate trades, join immutable UTC entry/exit intents to independent timestamped Bybit public trades, mark-price tape, L50 when available, fee/funding and position ledger; assert `signal_event_id < entry_fill_event_id`, monotonic exchange timestamps with tie-break sequence, no future features, and independently measured tape coverage. For STOP, record side-specific trigger and first executable fill, partial fills, gap/slippage, liquidation/maintenance threshold before fill. LONG stop triggers on adverse downward move; SHORT stop on adverse upward move. Enforce risk <=0.25%-0.5% equity per trade and aggregate <=1% stop risk, with capital reserved until close. Fail closed when evidence missing. Compare unchanged baseline and risk variants on identical verified trades, and report both closed and MTM equity.

## Outcome
This iteration completed a source-level audit, not a matched historical event replay. The original 67-trade simulation remains unverified at the fill level. No new PnL, MFE retention, MTM DD or liquidation claims. Frozen thresholds and rejected overlays unchanged.
