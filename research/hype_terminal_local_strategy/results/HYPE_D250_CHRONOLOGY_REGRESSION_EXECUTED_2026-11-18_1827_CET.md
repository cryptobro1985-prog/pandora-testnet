# HYPE D250 chronology regression — 2026-11-18 18:27 CET

Scope: research-only. No detector retraining, frozen-threshold changes, production deployment or orders.

## Execution performed
Fetched the branch's `research/hype_terminal_local_strategy/d250_trade_replay_manifest_gate.py` (blob cc54a485197ead36bc200e62dac7ad61e198e5b4), reproduced its `audit` and `stamp` functions verbatim in a local Python harness, and executed ten deterministic unittest cases using synthetic rows. Command: `python -m unittest -v test_gate.py`. **10 tests passed (0.001s).** This tests gate behavior, not the 67 historical trades or real exchange execution.

Cases tested: same-timestamp STOP/opposite blocks; earlier opposite blocks; strictly earlier STOP passes the ordering check; opposite before entry blocks; opposite-confirmed exit at same timestamp blocks; exit after opposite passes; feature as-of later than signal blocks; SHORT/HIGH passes; SHORT/LOW blocks; STOP with no opposite timestamp passes.

## New concrete finding
The current manifest gate allows a STOP row with no `opposite_confirmed_utc` (test 10). This is **not proof** that STOP preceded the opposite-local event; the field is optional by design and absence is not evidence of no earlier opposite event. The gate also trusts `COMPLETE` coverage flags without independently matching raw exchange events. Therefore a passed manifest cannot be reported as validated trade chronology or safe execution.

## Reproduction recipe
In a Python 3 environment, import `audit` from the existing gate module and construct rows with: extreme 00:00Z, H1 confirmation 01:00Z, D250 signal 05:00Z, entry 05:01Z, feature as-of 05:00Z, `rev_atr=2.5`, `trade_ratio5=0.3`, `flow15=0.4`, positive prices, and all three coverage assertions COMPLETE. Set STOP exit 12:00Z. With opposite=12:00Z expect STOP_NOT_PROVEN_BEFORE_OPPOSITE_CONFIRMATION; with opposite=11:59Z expect same; with opposite=12:01Z expect no reasons; omit opposite entirely and current code returns no reasons. Repeat side SHORT/local_kind HIGH. This checkpoint records actual local execution of a copied source function, not a GitHub Actions run.

## Next replay gate
Do not change the frozen D250 detector. Before crediting STOP exits, require an independently reconstructed chronological opposite-local event ledger for the full trade holding window (including verified coverage and UTC event ordering). Treat missing ledger as `UNVERIFIED_OPPOSITE_EVENT_COVERAGE`, not as no opposite event. Then recover the original May-inclusive 67-trade identifiers and matched Bybit trades/mark/L50/funding/stop execution. Compare unchanged baseline against 0.25%-0.5% stop-risk sizing on the exact same non-overlapping trade cohort. No new PnL, liquidation count, MTM DD or MFE retention can be claimed from these tests.
