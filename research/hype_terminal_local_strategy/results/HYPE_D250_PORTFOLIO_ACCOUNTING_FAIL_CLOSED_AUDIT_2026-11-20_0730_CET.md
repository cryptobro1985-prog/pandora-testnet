# D250 portfolio accounting fail-closed audit — 2026-11-20 07:30 CET

Research-only; frozen entry and previously rejected exits unchanged. No orders, retraining, or production change.

## Directly inspected branch files
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`
- `portfolio_accounting_research.py`
- `portfolio_stop_risk_guard_20261114.py`
- `d250_trade_replay_manifest_gate.py`
- Previous `results/HYPE_D250_2026-11-20_0632_CET_RISK_CAP_AND_CAUSAL_AUDIT.md`

## New concrete accounting audit
`portfolio_accounting_research.evaluate()` uses `float(t.get("funding_fraction",0.0))`: missing funding is silently treated as zero. This violates the requested missing-data fail-closed policy and could inflate net returns. The same function accepts an arbitrary `account_exposure` without checking initial/maintenance margin, total available cash, or whether stop risk exceeds 1%. It compounds closed equity only and cannot claim mark-to-market drawdown or no liquidations. Its `roundtrip_cost_fraction` is supplied by the caller and not reconciled with fills. `portfolio_stop_risk_guard_20261114.authorize()` does enforce a modeled combined stop-risk cap when existing_stop_risk is supplied, but there is no demonstrated integration binding its output to the portfolio accounting input and open-position ledger. These are code-level findings, NOT measured trade outcomes.

## New numerical sensitivity: matched stop geometry, same provisional cost assumptions
Assumptions: $100 equity, 0.15% round-trip fee fraction of notional, gap reserve 2 percentage points, no funding. Modeled notional = equity*risk_fraction/(stop_distance+0.0015+0.02).
- 1% stop: at 0.25% equity risk $7.9365 notional; at 0.5% $15.8730.
- 3.14% structural stop: at 0.25% equity risk $4.7259; at 0.5% $9.4518.
- If actual gap exceeds the 2pp reserve by another 2pp, realized loss above budget equals $0.1587/$0.3175 for 1% stop at 0.25%/0.5% budgets; $0.0945/$0.1890 for 3.14% stop. This is excess over budget, not total loss. These are analytical stress examples, not Bybit observations.
- At risk 0.5% and 3.14% stop, the provisional account exposure is 0.09452x, not 3x/5x. Thus original compound returns cannot be transplanted to risk-limited sizing.

## Reproducible regression conditions for next implementation
1. Calling portfolio accounting with missing `funding_fraction` MUST return `BLOCKED_MISSING_FUNDING`, not a net-equity curve.
2. Trade notional/exposure MUST derive from a risk-guard authorization linked by trade ID, with fees, funding, stop geometry and gap reserve reconciled; arbitrary exposure must fail.
3. All trades must be replayed in event-time order with account-level cash, margin and stop-risk ledger; no capital double use.
4. A missing Mark Price or L50 sequence must result in unknown liquidation/fill status and no performance promotion.
5. Require matching original baseline and candidate trades with identical event tapes and cost assumptions; split LOW->LONG / HIGH->SHORT and chronological unseen forward. Do not optimize rejected exit overlays without independent new evidence.

## Status
No individual 67-trade UTC execution tape was recovered this iteration. No historical fills, monthly net equity, MTM DD, actual liquidations or MFE protection results established. This is a reproducible code inspection and algebraic stress audit, not an event replay. Frozen D250 and 1% baseline untouched.
