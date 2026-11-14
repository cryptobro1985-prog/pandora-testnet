# HYPE event-order stop-first guard — 2026-11-14 22:35 UTC
Research only; frozen D250 unchanged; no production edits or live orders.

## New reproducible implementation
Added `research/hype_terminal_local_strategy/event_ordered_exit_guard_20261114.py` to the EXISTING research branch. This is an executable, isolated event-ordered guard for a pre-existing confirmed LOW->LONG or HIGH->SHORT entry, not a detector or snapshot classifier. Inputs: entry timestamp/price and ordered exchange observations. It stops processing immediately on the first observed stop crossing or opposite-local availability notification. Therefore it does not credit any subsequent high/low to MFE. It explicitly returns UNKNOWN for stop fill price, net PnL and liquidation count: a trade print alone is not executable bid/ask or stop acknowledgment.

## Reproduction
`python research/hype_terminal_local_strategy/event_ordered_exit_guard_20261114.py`
Includes four deterministic synthetic assertions: LONG stop-first, SHORT stop-first, causal opposite notification, rejection of future-available observation. These assertions are provided but **not claimed executed in GitHub CI**.

## Scope and blockers
This is not the requested matched historical replay: no raw rich event tape or immutable 71-signal event manifest was supplied to this run. The module does not infer fees, funding, slippage, liquidity, stop lifecycle, or liquidation distance. A real replay must pair confirmed entry events with trade/L50/mark, stop order acknowledgment/cancel-replace and time-resolved funding; use identical 71-signal cohort for frozen baseline and risk-sized challengers, include four right-censored cases, report MTM and closed DD monthly and OOS. An opposite-availability event is an exit decision only, NOT an observed fill.

## Result
New reproducible code path prevents the previously audited full-bar post-stop MFE credit on event-ordered input. It is not evidence of positive trading expectancy, successful fills, or no liquidation. Original 67-trade simulated 3x/5x figures and rejected trailing overlays remain unchanged. No retraining, new branch, or real orders.
