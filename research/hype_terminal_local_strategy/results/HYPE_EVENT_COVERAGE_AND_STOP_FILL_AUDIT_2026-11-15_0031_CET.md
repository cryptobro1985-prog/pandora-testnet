# HYPE execution-replay integrity checkpoint — 2026-11-15 00:31 Europe/Stockholm

Research only; no live orders, no detector retraining, no changes to frozen D250 thresholds.

## Inputs checked
Read original H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md, HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md, and event_ordered_exit_guard_20261114.py directly from the target branch.

## New reproducible integrity gate
Added causal_event_integrity_20261115.py. Six synthetic checks executed locally successfully: ordered coverage, absent entry coverage, >60-second gap, duplicate/out-of-order key, impossible receive timestamp, and conservative sizing arithmetic. It rejects missing evidence instead of treating a missing tick as a period without a stop hit. The 60-second threshold is a configurable research screening threshold, NOT proof that 60 seconds of missing trades is safe. The gate is only a preliminary integrity filter: it does NOT verify coverage all the way through the actual exit, websocket completeness, venue sequence semantics, stop fills, or executable liquidity. A full replay must require start-to-end coverage and cross-check source-specific sequence semantics.

## Baseline reconciliation / new arithmetic
Frozen 67-trade report: 49.25% positive closes, average winner +14.16% and loser -4.37% at 5x account exposure, 22 fixed-cut exits, 5x worst modeled trade -5.75%, closed DD 29.36%. These aggregate figures imply a descriptive arithmetic mean 0.4925*14.16 - 0.5075*4.37 = +4.756 percentage points of equity per trade (subject to rounding and differing compounding weights). This is NOT a new independently replayed expectancy, not a risk-normalized edge, and not an out-of-sample result.

The reported -5.75% worst trade equals 5x*(1% adverse-price cut + 0.15% round-trip fees), demonstrating that the reported bound embeds a stop-at-threshold fill assumption. At 5x account exposure, a modeled adverse gap beyond the 1% stop of 0.5%, 1%, 2%, and 5% would instead give -8.25%, -10.75%, -15.75%, and -30.75% equity respectively, before funding. These are hypothetical gap stresses, not observed Bybit fills.

For $100 equity, 0.5% equity stop-risk, 1% adverse-price cut, 0.15% round-trip fees and 1% adverse execution gap reserve, max notional = 0.5/(0.01+0.0015+0.01) = $23.26. At 0.25% risk it is $11.63. Actual losses can exceed the budget when gaps exceed the reserve.

## Required historical replay input contract
For each of the 71 accepted signals: original local side and timestamp; K2 or other causal availability timestamp; entry eligibility timestamp; execution timestamp and bid/ask; market trades with source sequence and received timestamps; L50 snapshots/deltas with freshness and sequence validation; liquidation/OI/CVD only when actually available; stop-order lifecycle; funding and fees; exact opposite-local availability; complete mark-to-market series; and final censored state for the four non-finalized cases. Enforce LONG only after LOW, SHORT only after HIGH, entry after information availability, no reused margin, and end-of-period open positions valued at mark. MFE ends at actual fill time, not at stop trigger or candle end. An opposite-local signal is not an executable fill.

## Decision
No promotion of any profit-protection overlay. Original 1% cut and hold-to-causal-opposite remain unchanged as comparison baselines, not live-verified strategies. Rich M1 event files and matched trade execution logs have NOT been retrieved in this iteration. Consequently monthly net equity, MTM DD, liquidation count, fill rate, and protected MFE are unverified. Next iteration must locate source artifacts and run this gate across matched trades, separately LOW->LONG and HIGH->SHORT, with complete interval coverage and identical costs.
