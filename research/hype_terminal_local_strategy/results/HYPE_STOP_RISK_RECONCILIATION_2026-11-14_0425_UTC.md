# HYPE stop-risk / exit-sample reconciliation — 2026-11-14 04:25 UTC

Research-only checkpoint. No orders, no detector retraining, no production changes.

## Evidence read in this iteration
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md
- HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md
- causal_event_tape_guard_research.py
- causal_exit_replay_research.py
- portfolio_accounting_research.py

## Concrete reconciliation
The 67 fully finalized opposite-local geometries are **not** a 67-trade verified execution tape. The minimal-rule causal opposite-local exit has 67.16% positive (~45/67), whereas the separately developed 1%-cut simulation has 49.25% positive (~33/67), 22 cut exits, and a distinct execution/accounting contract. These cannot be merged into one confusion matrix or used to claim that 12 specific opposite-local exits lost money. The original simulation's 5x exposure ($100 -> $1,308.86; closed DD 29.36%) and 3x ($100 -> $531.16; closed DD 18.56%) are NOT 0.25%-0.5% risk-per-trade tests.

## Stop risk stress, analytically reproducible
Let E be current equity; r=0.0025 or 0.005 target equity loss; d=0.01 adverse trigger distance; c=0.0015 roundtrip notional fees; g=additional adverse gap after trigger. Worst-case modeled loss per notional = d+c+g. Max notional/E = r/(d+c+g). These are scenario calculations, NOT Bybit observed fills.

| gap after 1% trigger | risk 0.25%: notional/equity | risk 0.50%: notional/equity | 5x original exposure equity loss |
|---|---:|---:|---:|
| 0% | 0.217391x | 0.434783x | 5.75% |
| 0.5% | 0.151515x | 0.303030x | 8.25% |
| 1.0% | 0.116279x | 0.232558x | 10.75% |
| 2.5% | 0.068493x | 0.136986x | 18.25% |

For 0.5% risk sized against a 1% gap (0.232558x), a realized 2.5% gap yields 0.232558*(0.01+0.0015+0.025) = 0.84884% equity loss. A stop-market is a trigger, not guaranteed price. Liquidation may precede the desired stop fill at high leverage, depending on mark price, tier, and maintenance margin.

## Independent new code-path finding
portfolio_accounting_research.py accepts already-computed signed underlying_return_fraction and roundtrip_cost_fraction; it does not check that the input trade was generated after a frozen D250 signal, that a stop was triggered before liquidation, that a stop fill was executable, or that funding and fees were observed. It explicitly reports only closed-equity DD, not MTM DD. causal_exit_replay_research.py processes complete OHLC rows without a fill timestamp and cannot resolve entry-bar pre-fill extremes. causal_event_tape_guard_research.py now fails closed for equal fill timestamp, but returns statuses rather than executable bid/ask fills. Therefore the three modules do not yet form an end-to-end matched execution replay.

## Required next artifact
A frozen per-trade manifest with trade_id, side, anchor_local_ts, signal_available_ts, order_submit_ts, fill_ts, entry_fill_price, stop_trigger_ts, stop_order_ack_ts, stop_fill_ts, exit_ts, exit_fill_price, position_notional, fees, funding, mark-price path, event-source references and data-coverage flags. Match each trade to Public Trades + executable bid/ask/L50 events and sequence IDs; if missing, mark UNVERIFIED rather than fabricate. Re-run the unchanged 67-trade baseline and alternatives on exactly the same chronological eligible trades, with capital locked until fill/exit. Report separately LOW/LONG and HIGH/SHORT, monthly net equity, MTM/closed DD, MFE retention, stop gaps, fills and liquidation proximity. Truly unseen forward must remain sealed.

## Decision
Do not promote break-even, trailing or price-impact exit overlays without independent evidence; existing rejected overlays remain rejected. The current verified result is a **model-risk reconciliation**, not new historical performance. No production or real trading authorization.
