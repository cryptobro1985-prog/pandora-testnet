# D250 trade replay gate: opposite confirmation / ledger consistency — 2026-11-19 00:26 CET

## Concrete investigation
Fetched the actual gate and both existing regression suites from the requested research branch. Found a fail-open inconsistency: for STOP exits, a supplied `opposite_confirmed_utc` could disagree with `opposite_ledger_first_utc` (including explicit NONE) and still pass when the confirmation was after the STOP. The optional confirmation could also be outside the ledger's claimed coverage window. This is a trade chronology/evidence integrity defect, not detector classification.

## Changes
- Gate now blocks any nonempty `opposite_confirmed_utc` inconsistent with the first opposite event declared by the ledger, for STOP as well as OPPOSITE_CONFIRMED.
- Gate blocks confirmations outside ledger_start..ledger_end.
- Added five synthetic regression cases: STOP with unlisted opposite, STOP with mismatched event, confirmation outside coverage, and consistent opposite exits for LONG and SHORT.
- No changes to frozen D250 thresholds, detector, position execution, production, or orders.

## Verification
Source changes and tests committed to the existing branch. Tests **not executed**: direct git checkout in execution container failed DNS resolution of github.com. The GitHub connector allowed fetching and writing files. Run:
```bash
python -m unittest discover -s research/hype_terminal_local_strategy -p 'test_d250*.py' -v
```
Do not interpret synthetic tests as historical replay. The gate remains a manifest-only assertion, not independently verified exchange event coverage.

## Still blocked
Matched 67-trade UTC event manifest, May M1, independent opposite-local event ledger, Bybit public trades, mark, L50 and actual fills/costs remain necessary for same-sample stop/entry/profit-protection comparisons. No new verified PnL, MTM DD, liquidation count, fill rate or MFE captured. Maintain 0.25–0.5% *planned* equity stop risk per trade, <=1% combined, and stress gaps/slippage; actual loss may exceed budget. Previously rejected overlays remain rejected without unseen forward evidence.
