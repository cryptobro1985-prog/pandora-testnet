# HYPE execution manifest provenance adversarial audit — 2026-11-14 11:26 UTC

Research only; existing branch; no live orders or production changes.

## Inputs inspected directly
- `research/hype_terminal_local_strategy/trade_manifest_gate_research.py`
- `research/hype_terminal_local_strategy/portfolio_stop_risk_guard_20261114.py`
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`

## New concrete adversarial analysis: manifest provenance is not verified
The current `gate(row)` tests `coverage_complete is True` and nonempty *strings* for `entry_fill_source`, `exit_fill_source`, `mark_path_source`, `l50_path_source`, `public_trades_source`, `event_sequence_source`, and `protective_stop_order_source`. It never opens these sources, hashes bytes, verifies time-window continuity, checks actual private execution records, or cross-checks the order/fill IDs.

**Constructive counterexample A:** the module's own `self_test()` constructs synthetic `base` with `entry_fill_source="private-fill"`, `mark_path_source="mark"`, `l50_path_source="l50"`, `public_trades_source="tape"`, `event_sequence_source="sequence"`, `protective_stop_order_source="order-log"`, and `coverage_complete=True`. The asserted result is `EXECUTION_FIELDS_COMPLETE_NOT_LIQUIDATION_VERIFIED`, even though those strings are labels rather than checked artifacts. Thus the current status must never be interpreted as a verified historical fill.

**Constructive counterexample B:** replace each of those strings with any other nonempty fabricated label, keep the same numeric fields and `coverage_complete=True`. The source-coverage branch of `gate` is unchanged; there is no source-level verification. This is a code-path deduction, not an executed historical replay.

## Material implication for the 67-trade experiment
The published 67-trade equity curves remain simulated and do not establish a historical matched execution tape, real protective stop activation, mark-to-market DD, liquidation count, or fill gap. Do not use synthetic `gate` status to promote the strategy.

## Frozen decisions preserved
D250: `rev_atr>2.0840049433824706`, `trade_ratio5>0.2727842248141979`, `flow15<0.4504731635235635`; 1% adverse cut; rejected MFE overlays remain rejected. Separate LOW/LONG from HIGH/SHORT. The earlier 67-trade 3x and 5x results are **not** independently revalidated here.

## Required next reproducible data-backed step
For each of the 67 chronological entry IDs, resolve a real immutable artifact URI, SHA-256, event-time interval and schema, and distinguish public-trade observations from actual/private fills. Join by event time with explicit ordering for same-millisecond collisions. For every candidate, return one of VERIFIED_REPLAY, INSUFFICIENT_SOURCE, or AMBIGUOUS_ORDER. Only then compute bid/ask-aware cost, stop-gap, liquidation buffer, net monthly equity, mark-to-market DD, and MFE giveback on a common sample. A missing L50/OI/liquidation field is UNKNOWN, never zero.

## Outcome of this iteration
Completed direct source-code adversarial analysis. No newly matched trade tape, real execution replay, or new net return claim. No thresholds fitted and no orders placed.
