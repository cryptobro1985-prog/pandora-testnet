# HYPE D250 — unresolved terminal position / opposite-confirmation timestamp audit
Date: 2026-11-21 01:30 CET. Research only; no orders.

## Sources actually inspected
- `research/hype_terminal_local_strategy/causal_exit_replay_research.py`
- frozen D250 walk-forward and asymmetric-risk reports dated 2026-11-12
- every-local robust report and unified entry/MFE contract

## New concrete replay audit (source-level deterministic fixtures)
The existing `replay(rows)` returns `exit_reason='OPEN'` but **also** sets `exit_price=close`, computes `net_equity_pct` as if a round-trip trade were completed, and subtracts the full round-trip `cost_pct`. Thus an unresolved position can contaminate closed-trade PnL if callers aggregate the returned field without filtering.

Fixture A: one valid LONG row, entry=100, low=100, high=105, close=104, `opposite_confirmed=false`, `ts_ms=60000`, `available_ts_ms=60000`; `exposure=.2`, `cost_pct=.0025`. Current code yields `OPEN` and `net_equity_pct=0.75` (20% exposure × (4%-0.25%)), despite no observed exit. Correct state is OPEN, with *unrealized* mark-to-market +0.8% equity before hypothetical exit fees, and closed PnL undefined. For SHORT entry=100, low=95, high=100, close=96, the same erroneous +0.75% closed-like figure arises.

Fixture B: LONG entry=100, first row ts=60000, low=100, high=101, close=100.5, `opposite_confirmed=true`, `available_ts_ms=1`. Current code exits `OPPOSITE` at 100.5 even though `available_ts_ms` is long before the entry bar; it only checks `available<=ts`, not the origin/provenance of the opposite confirmation. A stale opposite confirmation could therefore close a new trade. The correct implementation must require a unique opposite-local ID, signal generation/availability time strictly after entry fill, and a tradable quote at or after availability, with no lookahead to the bar close.

Fixture C: LONG entry=100, one bar ts=60000, low=98, high=102, close=101, stop_pct=.01. The current replay reports STOP, uses exit price min(99,101)=99, and reports MFE=2% even though OHLC cannot establish whether 102 occurred before or after the stop. The previous intrabar audit noted this; it is included here as an interaction test with terminal accounting.

## Explicit separation required
- CLOSED: actual stop/exit event plus executable bid/ask fill, fee/funding, timestamp.
- OPEN: unrealized MTM and margin/liquidation exposure; *never* count as a closed fill.
- UNRESOLVED: incomplete quote/mark continuity, uncertain stop/exit order, or absent fill; exclude from claimed observed liquidation-free performance.
- OPPOSITE: strictly later causal confirmation tied to a different anchor, and first executable quote after signal availability.
- Carry forward capital reserved by OPEN/UNRESOLVED positions; do not reallocate it to the next candidate.

## Conservative risk sizing (illustrative, not a Bybit replay)
If adverse stop distance is 1%, assumed round-trip fee 0.15% of notional, and reserved gap 2%, budgeted loss per notional is 3.15%. At 0.25% equity risk max notional/equity = 0.0025/0.0315 = 0.079365x; at 0.5% risk = 0.158730x. Gap reserve is not a guaranteed loss cap. A structural stop with median 3.14% price distance requires lower notional for the same budget. Instrument leverage must be checked separately against liquidation and maintenance margin.

## No promotion
No new historical fills, matched UTC L50/Mark tape, independent forward trades, MTM DD, stop counts, or observed liquidation count were produced. Do not infer these from deterministic fixtures. Preserve frozen D250, 1% cut baseline, and previously rejected MFE overlays. Do not retune thresholds or touch production.

## Next executable research action
Locate the 67-entry event ledger and matching raw UTC Mark Price, bid/ask/L50, Public Trades, OI, liquidations, funding tapes. Fail closed if a tape is absent. Replay each trade as an event state machine; separately report LONG and SHORT, open/unresolved counts, intrabar ambiguities, true closed fills, risk-budget sizing, and monthly MTM/closed equity on the same chronological sample.
