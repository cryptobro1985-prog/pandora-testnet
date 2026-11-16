# HYPE M1 stop-bar MFE and window scope — 2026-11-16 04:34 CET

Research-only checkpoint. Existing branch; no detector retraining, production change or orders.

## Concrete code change
Updated `m1_stop_order_ambiguity_replay_20261116.py` to evaluate continuity ONLY for bars within [entry_ts_ms, exit_ts_ms). Previously the loop checked the gap from an archival bar before entry to the entry bar, even when every held minute was present, producing false UNKNOWN_GAP. The explicit expected-minute coverage gate remains unchanged and fail-closed.

The module previously returned `mfe_upper_bound` including the high/low of the very candle that touched the stop. That extreme could have occurred after the stop, and must not be interpreted as obtainable pre-stop MFE. For stop-touched episodes it now returns `mfe_upper_bound: null`, and separately `pre_stop_bar_favorable_upper_bound` as a non-executable envelope, with an explicit warning. For non-stop episodes, the old M1 favorable upper bound remains a proxy, not an executable fill.

## Regression fixtures added
1. Bars at -180000, 0, 60000, 240000 ms with holding interval [0,120000) must yield NO_STOP_TOUCH_IN_M1 despite archival gaps outside holding.
2. LONG entry 100, stop 99, first bar high 110/low 98 must yield STOP_TOUCHED_FILL_UNKNOWN, null mfe_upper_bound, and favorable candle envelope >=10%; no ordering or captured MFE asserted.

Commits: replay `705809b1307addc7501402e7ad6d71083fe5f1ea`; regression `0a87ac9faacfa5d37f65bd04ec25e67b643ec1a4`.

## Verification and evidence limits
Source and regression expectations reviewed; remote CI/test execution not confirmed. No new Bybit event-tape matches, execution fills, liquidation proof, net PnL, mark-to-market DD, or independent forward results. Historical D250 and 67-trade metrics are not upgraded to verified execution evidence.

## Next reproducible replay
Recover 67 individual trade timestamps and identifiers; join Bybit M1 plus trade tape, mark, and book evidence using source hashes and timestamps. Mark absent execution evidence UNKNOWN, keep LONG/SHORT separate. Freeze original D250 and original baseline. Compare 0.25% and 0.5% stop-risk sizing (aggregate <=1%), staged entries and protection only on identical matched episodes, fees, funding, realistic stop-gap and no capital overlap. Report monthly net equity, closed/MTM DD, stop outcomes, fill uncertainty, liquidation distances and MFE captured/given back. Previously rejected overlays remain rejected pending unseen forward evidence.
