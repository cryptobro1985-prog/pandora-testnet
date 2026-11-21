# HYPE D250 — opposite-local OHLC close availability audit — 2026-11-21 03:34 CET

Research only. Frozen detector and rejected overlays unchanged. No real orders.

## Directly inspected source
`research/hype_terminal_local_strategy/causal_exit_replay_research.py` on this branch, plus frozen D250 and asymmetric-risk reports.

## New causal defect
The replay iterates `ts_ms`, `low`, `high`, `close`, `available_ts_ms` and closes at `close` when `opposite_confirmed` and `available_ts_ms <= ts_ms`. There is no definition/validation of whether `ts_ms` is candle open or close. If `ts_ms` is M1 open, the OHLC close is not known until the next minute, and the replay may use a future close for an earlier opposite-local decision. Even if `ts_ms` is candle close, this is not an executable bid/ask fill at that price. Thus the check is necessary but insufficient for causal execution.

## Reproducible boundary counterexamples (synthetic, NOT Bybit fills)
Assume 1-minute bars are open-stamped and latency is zero:
- LONG entry 100; bar timestamp 12:00:00, opposite confirmation available 12:00:00, bar close 102 at 12:01:00. Current code can close at 102 at the 12:00 signal despite this price only being known at 12:01. It assigns +2% gross, or +1.85% notional after frozen 0.15% round-trip cost. Neither is a causal 12:00 fill.
- SHORT entry 100; bar timestamp 12:00:00, opposite confirmation available 12:00:00, bar close 98 at 12:01:00. Current code can assign the same +2% gross and +1.85% net notional prematurely.
- Signal available at 12:00:30, bar open 12:00:00: current code refuses the exit for that bar, but a real trade could execute after 12:00:30. This creates opposite timing bias in the other direction. Neither outcome is recoverable from OHLC alone.

Arithmetic verification: LONG 102/100-1 = .02; SHORT 1-98/100 = .02; .02-.0015=.0185.

## Mandatory replay contract
1. Declare each bar's open and end UTC, not ambiguous `ts_ms`. An OHLC close is usable for signal computation only at bar_end + data latency.
2. Opposite-local `available_utc` must refer to confirmed event publication, strictly after entry event, and never be inferred from final future pivot extremum.
3. Find first independently recorded executable quote/event after `max(signal_available_utc, entry_utc)`; LONG sells at bid, SHORT buys at ask; apply latency, depth/size, fees, funding and gap. Do not fill at the OHLC close retroactively.
4. If only M1 bars exist, label execution `UNRESOLVED` or compute explicitly optimistic/pessimistic bounds; never promote as verified matched fill.
5. Reuse exact 67-trade manifest and unchanged legacy 0.15% cost baseline. Compare risk budgets 0.25/0.5% only after stop execution uncertainty and actual quote-side cost are measured.
6. Stop and MFE event order within a bar remains unresolved absent finer tape; never credit post-stop highs/lows. Preserve OPEN capital occupancy and separate closed/MTM equity.
7. Keep previously rejected exit overlays rejected pending independent chronological forward evidence.

## Outcome
New source-level temporal causality defect with two-sided reproducible counterexamples. No actual 67-trade quote replay; no new performance, DD, liquidation or MFE claim. No code, production, or detector change.
