# HYPE causal OHLC replay execution-bias audit — 2026-11-19 07:31 CET
Research-only. No detector refit, no production edits, no orders.

## Source inspected
`research/hype_terminal_local_strategy/causal_exit_replay_research.py` on the requested branch, and frozen D250 / asymmetric-risk / unified-entry documents.

## Concrete source-level findings (reproducible from current code)
1. **OHLC intrabar ordering ambiguity**: code evaluates stop before opposite confirmation on each bar, without sub-bar timestamps. If both occur inside one bar, STOP is assumed even if the opposite event was available first. This is conservative for priority but does not reconstruct actual event sequence.
2. **Stop execution look-ahead**: on a touched stop, LONG exit = `min(stop, close)`; SHORT exit = `max(stop, close)`. A bar's *final close* is unknowable when a stop is first touched. Example LONG entry 100, stop 99, bar low 98.5, high 100.2, close 98.7: code fills 98.7 (-1.3% gross), whereas the tape only establishes that 99 was crossed; neither a 99 fill nor 98.7 fill is proven. With identical low/high but close 99.8, code fills 99 (-1% gross). Thus reported PnL depends on future close even when stop was touched earlier. SHORT mirrors this.
3. **Opposite-confirmation timestamp mismatch**: `available_ts_ms<=ts_ms` treats the OHLC bar's timestamp as the point when `close` is executable. If `ts_ms` is bar-open time, a close-price exit is not available until bar end; if bar-close time, high/low reflect earlier events. A strict event-time contract is missing.
4. **MFE/MAE leakage after exit**: the loop updates full-bar `high/low` before deciding STOP or OPPOSITE. If exit occurs intrabar, later favorable/adverse extremes are counted as though the position remained open. `giveback_fraction` can consequently be biased.
5. **Risk model is not a fill model**: `worst_intrabar_equity_pct` uses OHLC extrema and fixed `cost_pct`, but has no bid/ask, book depth, order quantity, mark-price liquidation, actual fees, funding timestamps, stop trigger type, gap fill or latency. It cannot establish no liquidations or execution-valid MTM drawdown.
6. **Missing consistency validation**: no explicit check that every row has the same side/entry, and no check that `available_ts_ms` corresponds to a valid event when `opposite_confirmed` is false.

## Concrete adversarial fixture
LONG entry 100, stop 99, exposure 0.2, cost 0.0025, OHLC low 98.5 high 100.2 close 98.7, opposite=false. Current code returns gross -1.3%, net equity -0.31% (0.2*(-0.013-0.0025)*100). Change only close to 99.8, keeping the stop crossing and extremes: gross -1.0%, net equity -0.25%. Both are assumptions, not executable fills. Stop gap/slippage needs time-stamped bid/ask/L50 or an explicitly labeled stress distribution.

## Corrective replay contract
- Freeze original D250 entry event and independent opposite-local confirmation event timestamps; LOW→LONG ask VWAP and bid exit; HIGH→SHORT bid VWAP and ask exit.
- Timestamp each market event, stop trigger, book snapshot, partial fill, fee, funding and mark price. At equal/ambiguous timestamps flag `ORDER_UNRESOLVED`, do not silently choose the favorable ordering.
- Update MFE/MAE only on observed executable quotes before exit; do not use full exit-bar extrema.
- Stop-market fill from subsequent executable quotes and depth with latency; if unavailable, report interval/stress bounds rather than invented fills.
- Maintain chronological equity/MTM ledger, nonoverlapping capital, side-specific stop distance, 0.25%-0.5% equity risk, <=1% aggregate planned stop risk, margin/liquidation buffers.
- Replay unchanged baseline and risk/staged-entry/profit-lock variants on exactly the same eligible event set; rejected overlays stay rejected pending independent forward evidence.
- Only then compute month-by-month net equity, MTM/closed DD, liquidation events, fill ratios, stops, MFE retention, and sealed forward results.

## Status
This run performs a source-level adversarial replay audit, **not** a 67-trade market-tape replay. Frozen thresholds and historical performance claims remain unchanged. Current replay function is NOT valid for verified stop execution or causal MFE accounting. Next task: repair the research-only replay implementation with explicit event-time and fill provenance, run deterministic adversarial tests, then join 67 trade IDs to raw UTC Bybit data. No live authorization.
