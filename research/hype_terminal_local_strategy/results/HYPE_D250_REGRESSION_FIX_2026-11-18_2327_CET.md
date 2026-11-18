# D250 chronology suite repair — 2026-11-18 23:27 CET

## Concrete change
Updated `test_d250_trade_replay_manifest_gate.py` in this existing research branch, without changing detector, frozen thresholds, execution logic, or production. Legacy fixture now supplies mandatory opposite-ledger coverage, first event (or explicit NONE), and ledger interval spanning entry through exit. Replaced obsolete STOP error assertion with current `STOP_NOT_PROVEN_BEFORE_OPPOSITE_CONFIRMATION`. Added same-timestamp STOP vs opposite-ledger regression that must fail closed.

## Verification status
Source-level comparison against current `d250_trade_replay_manifest_gate.py` and `test_d250_ledger_window.py` completed. **Tests NOT executed**: execution environment could not resolve github.com for a checkout; connector file access/write succeeded. No 16/16 or 24/24 claim. Next run should execute:
```bash
python -m unittest discover -s research/hype_terminal_local_strategy -p 'test_d250*.py' -v
```
Capture exact failures and correct only test drift, never relax the gate to make tests pass.

## Trade safety and evidence
Manifest COMPLETE is an assertion, not proof of full Bybit trade/mark/orderbook tape. Still missing matched original 67-trade UTC journal, opposite-local event ledger, May cohort, fill and gap slippage, fee/funding ledger. Therefore no credible new net PnL, mark-to-market DD, liquidations, fill rate, MFE protection, or independent forward outcomes. Continue with 0.25–0.5% hypothetical planned equity risk and <=1% combined planned stop risk, with gap risk explicitly unbounded. Frozen D250 thresholds unchanged. No real orders, retraining, or production changes.
