# Frozen D250 — strict opposite-local execution ordering (2026-11-17 06:31 CET)

## Scope
Existing branch only. No retraining, production modification or orders. This is a causal manifest-gate correction, **not** an event-level execution replay.

## New audit finding
The prior gate accepted `opposite_confirmed_utc == entry_utc` and `exit_utc == opposite_confirmed_utc`. Timestamp equality does not establish that an opposite-local signal was known before an executable fill. At coarse timestamp resolution, simultaneous observations are ambiguous; treating them as guaranteed fills introduces zero-latency lookahead bias. This is especially material for MFE protection where an exit at the instant of opposite confirmation can overstate capture.

## Changes
- For OPPOSITE_CONFIRMED, require `entry_utc < opposite_confirmed_utc < exit_utc` (strict temporal ordering); STOP remains allowed without any opposite-local confirmation.
- Added tests rejecting equality at entry and exit and a positive-control test with exit strictly after confirmation.
- D250 frozen thresholds and previously rejected MFE overlays remain unchanged.

## Limitations / execution requirements
- Strict timestamps are necessary, not sufficient. If timestamp granularity is only 1 minute, next-tick/next-event execution must be enforced; no assumed fill at signal price.
- Existing `COMPLETE` coverage flags are self-reported and do not prove matching Public Trades, L50, mark-price, liquidation or funding events.
- No individual 67-trade UTC manifest or matched exchange event tape was loaded in this iteration. Therefore no verified fills, stop gaps, liquidation count, net monthly equity, mark-to-market DD, MFE capture/giveback or independent forward result is reported.
- Risk-based sizing should be tested at 0.25% and 0.5% of equity per stop, maximum 1% concurrent stop-risk; notional must include stop distance, fees, gap/slippage reserve and liquidation proximity. These are **test requirements**, not measured performance.
- Baseline remains 1% adverse cut, no tight trail, exit on causal opposite local. Previously rejected flow/MFE/K0/K1/pyramiding overlays remain rejected until new unseen evidence.

## Reproduce
```bash
cd research/hype_terminal_local_strategy
python -m unittest -v test_d250_trade_replay_manifest_gate.py
```
The test command is supplied for reproduction; test execution has **not** been independently verified in this iteration because this environment cannot resolve github.com for a checkout. Changes were written via the connected GitHub API.

## Next concrete replay milestone
Extract the actual 67 entry/exit records with timestamps, join to Bybit Public Trades/M1/mark-price (and L50/OI/liquidations where present), flag the five known M1 gaps, compare LONG vs SHORT stop paths and the frozen baseline against risk-sized mandatory-stop alternatives on the same ordered capital ledger. Do not infer unobserved fills.
