# HYPE D250 fail-closed closed-equity accounting gate — 2026-11-20 08:28 CET

Research-only, no retraining, production edits or orders. Frozen D250 and original baseline unchanged.

## Sources directly read on branch
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md
- HYPE_D250_PORTFOLIO_ACCOUNTING_FAIL_CLOSED_AUDIT_2026-11-20_0730_CET.md
- portfolio_accounting_research.py
- portfolio_stop_risk_guard_20261114.py

## Concrete new deliverable
Added `portfolio_accounting_failclosed_gate_20261120.py`, a separate input gate around existing closed-equity evaluator. Missing funding is blocked instead of implicitly zero; missing trade IDs, risk authorization inputs, or invalid time/overlap are blocked. Notional/exposure consistency and authorized stress loss <= 0.5% of stated entry equity are checked. Results are explicitly labeled scenario-only; MTM DD, liquidations and MFE remain unknown. Five synthetic assertions included in code; **not executed in this GitHub iteration**, so no test pass is claimed.

## Important unresolved consistency caveat
The new gate checks caller-provided authorization numbers, not a cryptographically/provenance-linked risk-guard decision. It also does not reconcile each trade's entry_equity to prior closed equity, nor does it simulate intratrade MTM, liquidation or capital reservations. Thus this is an incremental fail-closed safeguard, NOT an execution replay or complete portfolio ledger. The new gate must not be used to promote historical performance.

## Research status
- Frozen D250 thresholds: unchanged (rev_atr > 2.0840049433824706; trade_ratio5 > 0.2727842248141979; flow15 < 0.4504731635235635).
- Existing historical 67-trade 3x/5x curves: remain unverified as execution outcomes.
- No reconstructed individual UTC fill tapes this iteration; 0 new confirmed historical executions.
- Monthly net equity, MTM/closed DD on matched event tape, stop gaps, funding, liquidations, MFE and unseen forward execution results: NOT ESTABLISHED.
- Rejected exit/profit overlays remain rejected.

## Next experiment
Recover 67-trade event ledger and matched Bybit trade/quote/mark/funding tapes. Link each stop-risk authorization to real entry equity and event-time margin ledger; run original baseline and conservative 0.25%/0.5% stop-risk policies on identical tapes. Separate LOW/LONG and HIGH/SHORT; report unfilled or missing-data episodes rather than imputing them. Never use future opposite exact extreme for exits.
