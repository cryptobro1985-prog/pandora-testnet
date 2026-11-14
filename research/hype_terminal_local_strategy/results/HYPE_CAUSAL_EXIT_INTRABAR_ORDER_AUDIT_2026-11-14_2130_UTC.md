# HYPE causal exit intrabar ordering audit — 2026-11-14 21:30 UTC

Research only. Existing frozen D250 entry and 1% adverse cut unchanged. No real orders, no retraining, no production edits.

## New code-level analysis

Read `research/hype_terminal_local_strategy/causal_exit_replay_research.py`, `portfolio_accounting_research.py`, and `portfolio_stop_risk_guard_20261114.py` directly from the named research branch, together with frozen D250 and 67-trade reports.

**New execution-replay blocker:** `causal_exit_replay_research.py` updates MFE/MAE using the **entire OHLC bar before** testing whether the stop was hit. On a bar that reaches both the favorable extreme and the stop, this credits favorable excursion even when the stop may have happened first. That creates an ungrounded MFE captured/given-back estimate. It is not an observed price path.

The script also uses `min(stop, close)` for LONG stop fills and `max(stop, close)` for SHORT. The bar close is not a valid proxy for the first executable quote after a stop trigger: it can overstate or understate realized stop loss depending on event ordering, gap, and liquidity. OHLC alone cannot certify an actual stop fill.

`available_ts_ms <= ts_ms` is necessary but insufficient when `ts_ms` is a candle **open** timestamp and the same row's high/low/close become available only at candle close. This may admit a same-bar opposite-local exit at a close that was not yet observable at the row timestamp.

## Deterministic illustrative counterexamples (not historical trades)

LONG entry 100, stop 99, one OHLC bar low 98, high 105, close 104: the script can record MFE +5% even if the actual event sequence was 100 -> 98 (stop first) -> 105 -> 104. The alternative ordering 100 -> 105 -> 98 -> 104 yields the same OHLC but different pre-stop MFE. The code's stop fill is min(99,104)=99 although executable fill after a trigger below 99 cannot be inferred.

SHORT entry 100, stop 101, bar low 95, high 102, close 96: similarly, full-bar favorable MFE +5% is counted even if stop 101 occurred before the low; stop fill max(101,96)=101 is not verified.

For both sides, a gap through stop requires executable bid/ask/mark trigger history and queue/slippage assumptions, not candle close.

## Mandatory event-level replay contract

1. Record local extreme timestamp, D250 signal timestamp, availability timestamp, entry order submission, acknowledgment, first eligible fill and price; never enter before causal availability.
2. For each trade, process exchange events in monotonic exchange timestamp + sequence order. On ambiguous identical timestamps, report bounds or fail closed. No full-bar MFE credited after exit.
3. Compute MFE/MAE only from executable post-fill events **before** actual or modeled exit; calculate giveback from the maximum reached before exit. Missing event tape => UNKNOWN, not zero.
4. Record stop placement/acknowledgment/cancel-replace and remaining protected quantity, trigger basis (mark/last), stop execution with side-specific gap/slippage; reject claims of continuously protected risk without lifecycle evidence.
5. Require position liquidation threshold under actual margin tier and available equity; track intratrade MTM equity and portfolio reserved stop-risk, including the four right-censored D250 signals.
6. Same 71 signals (67 completed + 4 censored) and identical fee/funding/slippage for unchanged 1% baseline and 0.25%/0.5% risk challengers. No overlap or future opposite extreme.
7. Test sustained opposite price-impact efficiency/control transfer only as a separately frozen challenger on untouched forward data; rejected MFE/trailing overlays remain rejected.

## Verdict

**No new net-equity, MTM drawdown, liquidation or MFE-retention number is warranted.** This is a new code-path audit identifying a specific MFE timing defect, not a historical execution replay. The existing 67-trade 3x $531.16 / 5x $1308.86 results remain simulated closed-equity only. D250 zero false-first is an entry-classification result, not a fill guarantee.

Next executable task: locate event tape and 71 immutable signal timestamps, then rerun event-ordered LONG/SHORT fills; keep OHLC-only metrics as bounded/unverified. No real orders.
