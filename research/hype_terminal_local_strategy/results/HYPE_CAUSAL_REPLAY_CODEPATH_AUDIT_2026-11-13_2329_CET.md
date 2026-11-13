# HYPE causal replay code-path audit — 2026-11-13 23:29 CET

Research-only checkpoint. No detector retraining, orders, or production changes.

## Directly inspected code
- research/hype_terminal_local_strategy/causal_exit_replay_research.py (blob aee58ed45b96e3839aee009414820e31c9f073e7)
- research/hype_terminal_local_strategy/portfolio_accounting_research.py (blob 29f428557db3ef5d169a17f2ec2e718b1a933376)
- research/hype_terminal_local_strategy/frozen_regime_equity_audit_20261113.py (blob cf3726e767dda28af87e0542b232a05200a4bd89)
- Frozen D250 and 67-trade source reports (2026-11-12).

## New concrete execution-path findings
1. **OHLC path is not a tick execution replay.** The causal_exit_replay_research.py loop evaluates intrabar high/low and opposite confirmation in a single row. A candle with both stop and a valid opposite confirmation is always stopped first. This is a conservative ordering convention, not observed trade order. A bar with a stop touch and close through the stop fills at close, rather than next executable quote; actual stop-market slippage remains unknown.
2. **Pre-entry contamination is not rejected.** The first tape row supplies side and entry_price, but there is no explicit entry_ts_ms check. If any rows precede executable entry, their high/low enter MFE/MAE, worst equity and stop testing. This can change exit and giveback without any detector error. Require first eligible event timestamp >= next executable quote timestamp and reject earlier rows.
3. **Mark-to-market estimate is not a liquidation replay.** worst_intrabar_equity_pct applies the full bar adverse extreme and flat cost even on the stop-triggering bar; the ordering of stop versus extreme is unknown. No mark-price series, maintenance margin, funding, queue depth, or liquidation threshold is present. Thus neither zero liquidations nor MTM drawdown can be inferred from this helper.
4. **Exit availability needs stricter causality.** The condition available_ts_ms <= ts_ms verifies availability by bar timestamp but does not establish that the opposite confirmation was available before the executable exit quote inside the bar. Need event timestamp, signal availability timestamp, next executable bid/ask timestamp, and strictly ordered event processing.
5. **Portfolio helper expects reconstructed events but does not reconstruct them.** portfolio_accounting_research.py rejects overlapping entries, computes closed equity and calendar-month grouping from supplied trade rows, but cannot verify stop fills, signal timing, liquidity, funding, or actual MFE. frozen_regime_equity_audit_20261113.py merely checks published period-end equity, not the 67 fills.

## Required deterministic acceptance tests (before claiming replay)
- Pre-entry OHLC with extreme adverse movement must have **no effect** on a post-entry trade.
- Same-bar stop and opposite confirmation must be marked **ambiguous** without ordered tick events, not presented as verified execution.
- Stop touched but next executable bid/ask gaps past stop: fill at executable quote and log gap, not ideal stop price.
- LONG after LOW and SHORT after HIGH must both use bid/ask correctly, separate maker/taker fees, mark-price liquidation buffer, and observed funding.
- Missing L50/OI/liquidations/mark-price must be tagged unavailable, never zero-filled or inferred.
- Trade IDs unique; non-overlap; entry >= frozen D250 authorization and next executable quote; no opposite-local oracle.
- Compare original frozen 67-trade baseline and alternatives only on identical reconstructed event sample and costs; forward partition sealed.

## Status
This iteration is a **source-code execution audit**, not a new market-data replay. No immutable 67-trade timestamp ledger or matched rich tick/mark tape was supplied to these scripts in this run. No new performance, MTM DD, stop fill, or liquidation claims. Preserve rejected profit-protection overlays as rejected. Next iteration should prioritize locating immutable 67-trade timestamps and matching rich tape, not additional algebraic leverage grids.
