# HYPE D250 — execution manifest false-positive audit (2026-11-20 15:30 CET)

Research-only. No retraining, live orders, or production changes. Frozen D250 unchanged.

## Verified source files (same branch)
- `research/hype_terminal_local_strategy/d250_trade_replay_manifest_gate.py`
- `research/hype_terminal_local_strategy/entry_execution_manifest_gate_20261119.py`
- `research/hype_terminal_local_strategy/results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`
- `research/hype_terminal_local_strategy/results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`

## New source-code adversarial audit: manifest acceptance is not execution proof

The 2026-11-19 `entry_execution_manifest_gate_20261119.py` accepts rows when `quote_event_count`, `mark_event_count`, `l50_event_count` are merely >=2, max reported gaps <=60,000 ms, `source_hash` length >=16, and `funding` parses as a float. These are user-supplied manifest assertions, not checks against independently sourced exchange events.

Reproducible counterexample: the script's built-in `base` row passes `audit([base])['replay_eligible']==1` although it contains only fabricated 100-300 millisecond timestamps, arbitrary quote/mark/L50 counts, and the literal `source_hash='0123456789abcdef'`. Thus `replay_eligible` must NEVER be reported as an actual fill, actual liquidation-free trade, or independently verified funding.

Additional independent defects identified by reading the code:
1. No `rev_atr`, `trade_ratio5`, `flow15` values or as-of timestamps are checked by the 2026-11-19 gate; a manifest can pass with no frozen D250 eligibility proof.
2. No quantity, tick/step, minimum order notional, executable bid/ask, or L50 depth/queue is checked. `entry_vwap` is a self-reported number.
3. `float(funding)` accepts literal zero without any funding-rate timestamps or source. Fee amounts need no independent reconciliation to fills.
4. `source_hash` is only length-checked; it is not recomputed from bytes. It can be any 16-character string.
5. The mark extrema and liquidation price are supplied assertions, not independently reconstructed mark and maintenance-margin schedules.
6. No portfolio-wide 1% risk cap, margin reservation, or sequential non-overlap is checked.
7. The gate does not verify opposite H1 confirmation/availability or distinguish confirmed K2 timestamp from future opposite extreme.
8. `max_quote_gap_ms<=60000` alone cannot establish dense quote coverage across the actual lifetime; two events can be declared alongside a fabricated maximum gap.

The separate `d250_trade_replay_manifest_gate.py` does check frozen thresholds, timestamps and asserted opposite-local ledger, but explicitly labels output `MANIFEST_ONLY_NOT_EXECUTION_REPLAY`. Passing the two gates still does not independently authenticate the underlying raw tape.

## Consequence for historical claims
The 67 simulated trades, 22 modeled fixed cuts, 3x $100->$531.16 and 5x $100->$1308.86 remain scenario-level findings, not verified execution. No newly proven fills, mark-to-market DD, stop gaps, liquidations, funding-adjusted monthly equity, or MFE capture in this iteration. The original baseline remains unchanged; no rejected exit overlay is promoted.

## Required next replay contract
For each trade independently hash the exact raw Bybit data bytes, verify file digest and timestamp coverage, rebuild bid/ask/L50/mark/funding from raw events, validate D250 as-of timestamps and local availability, simulate stop execution at adverse executable prices and liquidation tiers, then run the same chronologically ordered capital ledger for baseline and risk 0.25/0.5% variants. If any component is absent, status must be `UNVERIFIED`, not `PASS`.

## Reproduction
Read `entry_execution_manifest_gate_20261119.py`, execute `python research/hype_terminal_local_strategy/entry_execution_manifest_gate_20261119.py` to run its synthetic built-in assertions; inspect its `base` row and `audit` function. The logical counterexample follows directly from the published source; the script was inspected here, but no remote GitHub Actions execution or real Bybit replay was claimed.
