# D250 execution safety — regression-suite drift audit (2026-11-18 22:26 CET)

## New concrete source-level finding
Read directly from the requested branch:
- `d250_trade_replay_manifest_gate.py`
- `test_d250_ledger_window.py`
- `test_d250_trade_replay_manifest_gate.py`

The **older 15-test** `test_d250_trade_replay_manifest_gate.py` is now incompatible with the stricter gate: its fixture omits mandatory `opposite_ledger_coverage`, `opposite_ledger_first_utc`, `opposite_ledger_start_utc`, `opposite_ledger_end_utc`. Its assertions of `audit(row()) == []` cannot pass against the current gate. It also asserts the obsolete reason `STOP_AFTER_OPPOSITE_CONFIRMATION` whereas the current gate emits `STOP_NOT_PROVEN_BEFORE_OPPOSITE_CONFIRMATION` for that case. This is **test drift**, not evidence of strategy failure. Do not report 15/15 passing.

The newer 8-test `test_d250_ledger_window.py` includes the ledger fields and explicitly checks incomplete windows, out-of-window events, and opposite-before-stop, but its `COMPLETE` coverage is still synthetic and asserted. No independent exchange event validation.

## Exact regression work required
1. Update the older fixture to include ledger coverage COMPLETE, ledger start <= entry, ledger end >= exit, and ledger first NONE for STOP tests. For opposite-confirmed tests set ledger first to the same causal confirmation UTC, and ensure exit follows it.
2. Update obsolete reason assertions and explicitly test identical STOP/opposite timestamps fail closed.
3. Run `python -m unittest discover -s research/hype_terminal_local_strategy -p 'test_d250*.py' -v` in a checkout with no orders or training; record stdout, commit SHA and test count. This checkpoint does **not** claim those tests were executed.
4. Keep frozen D250 thresholds unchanged. Gate eligibility is not matched execution replay.

## Trade-level evidence still required
The 67-trade original UTC journal, independently reconstructed opposite H1 event ledger, synchronized Bybit M1/Public Trades, bid/ask/L50, mark, funding, and May cohort remain unverified in this run. Therefore no new net PnL, MTM DD, liquidations, MFE capture, forward performance or reliable stop fill estimates are claimed. No production changes or live orders.

## Risk implication
Until chronology tests are synchronized and event tapes independently verified, the manifest gate must **not** be treated as proof that any LONG/SHORT trade is safely executable. Continue sizing only as hypothetical 0.25%-0.5% planned equity risk, with total planned open stop risk <=1%; gaps can exceed this budget.
