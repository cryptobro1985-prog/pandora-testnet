# D250 M1 continuity v2 — audit correction (2026-11-18 05:35 CET)

Research only. Existing branch; frozen D250 thresholds unchanged. No orders, no detector retraining.

## Concrete new finding
The preceding `d250_m1_continuity_audit_20261118.py` computes missing minutes by differences between *adjacent rows*. This is not an order-independent coverage measurement. Example timestamps [00:00, 00:02, 00:01, 00:02] for window 00:00–00:02: all three minutes exist, but the old algorithm reports a missing minute because it sees the first 00:00→00:02 jump. It also counts only adjacent duplicates, missing repeated timestamps separated by other rows. Consequently missing-minute totals from the old script must not be trusted when records are out of order.

## Correction
Added `d250_m1_continuity_audit_v2_20261118.py` to compute exact set-based missing minutes, global duplicate count, out-of-order transitions, outside-window rows, and bounded missing-interval examples. It includes five deterministic synthetic regression cases and a CLI `--selftest`. A true continuity verdict requires zero missing, duplicates, out-of-order transitions and outside-window rows.

## Execution status
Source code committed; the selftest and historical file audit have NOT been executed in this run. No real M1 CSV, matched 67-trade UTC journal, or per-trade L50/trades/OI execution data was fetched in this iteration. Thus no historical trade replay, fills, MTM drawdown, funding, liquidation count or MFE retention can be claimed. Do not infer execution validity from M1 timestamp coverage alone.

## Next empirical gate
Run the v2 scanner against each *actual* archived HYPE M1 file, record SHA256 and UTC coverage, recover exact 71 signals and 67 completed trades with timestamps, then run separate LONG/SHORT matched event replay with frozen D250, 1% baseline adverse-price cut, and conservative 0.25%/0.5% stop-risk sizing under identical costs and capital accounting. Missing execution evidence must remain UNKNOWN rather than be zero-filled. Rejected MFE overlays remain rejected pending independent forward evidence.
