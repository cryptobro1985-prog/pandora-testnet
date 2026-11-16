# HYPE M1 execution replay boundary audit — 2026-11-16 02:26 CET
Research only. No new detector training, no production changes, no orders.

## New concrete work
Read the frozen D250 and asymmetric-risk reports and inspected the actual M1 stop replay source. Added deterministic regression fixture `tests/test_m1_stop_replay_boundary_20261116.py` at commit edb2e46f272bef0b20b584e65ac8a44110d4cbe7.

## Two specific replay defects
1. **Intrabar entry silently accepted.** For entry_ts_ms=30000 and first M1 bar starting at 0, the existing check `if t==t0 and t0%60000` never runs because `t` is a minute start, not 30000. The pre-entry portion of the first bar cannot be used to prove a post-entry stop or MFE. The current replay skips the first bar and can return NO_STOP_TOUCH_IN_M1 without resolving the unknown first 30 seconds.
2. **Missing last minute silently accepted.** For entry=0, exit=180000 and bars only at 0 and 60000, the check `bars[-1].ts_ms >= exit_ts_ms` is false; current code can return NO_STOP_TOUCH_IN_M1 even though 120000–180000 is absent. Need enforce contiguous coverage of every minute intersecting [entry, exit), with explicit boundary uncertainty.

## Repro
`python research/hype_terminal_local_strategy/tests/test_m1_stop_replay_boundary_20261116.py`
Fixture assertions encode observed behavior of the inspected source; GitHub Actions execution has **not** been verified. These are logic counterexamples, not historical executions.

## Correct next research gate
For entry within an M1 candle, require event tape or mark path from the entry timestamp, otherwise UNKNOWN_ENTRY_INTRABAR. For final candle require full interval coverage, otherwise UNKNOWN_EXIT_BOUNDARY/GAP. Do not treat NO_STOP_TOUCH as verified fill or liquidation proof. Match the 67 individual episodes to M1/public trades, bid/ask, mark and L50; compare identical event intervals and costs with frozen D250. LOW->LONG and HIGH->SHORT must remain separate. Maintain baseline unchanged and 0.25–0.5% equity stop-risk variants with total <=1%. Prior rejected profit-protection overlays remain rejected.

## Status
No real matched per-trade execution replay in this iteration; no new monthly net equity, MTM drawdown, stop fill, liquidation or MFE metrics can be honestly reported. Frozen thresholds and baseline unchanged.
