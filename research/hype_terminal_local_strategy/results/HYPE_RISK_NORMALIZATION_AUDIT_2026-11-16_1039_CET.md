# HYPE post-local execution: risk-normalization audit — 2026-11-16 10:39 CET

Research only. No orders, production changes, detector retraining, or new thresholds.

## Directly inspected existing source files
- results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md
- results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md
- stop_risk_budget_replay_20261116.py

Frozen D250 unchanged: rev_atr > 2.0840049433824706, trade_ratio5 > 0.2727842248141979, side-normalized flow15 < 0.4504731635235635. LOW -> LONG; HIGH -> SHORT, after causal confirmation only.

## New numerical consistency audit (deterministic algebra, NOT historical replay)
For equity $100, round-trip fee reserve 0.15% notional, funding reserve 0.06%, gap/slippage reserve 1.00%, stop 1.00% from entry:
- unit budgeted loss = 1% + 0.15% + 0.06% + 1% = 2.21% of notional.
- risk 0.25% equity -> notional $11.312217; at 25x instrument leverage margin $0.452489.
- risk 0.50% equity -> notional $22.624434; at 25x instrument leverage margin $0.904977.
- 1% portfolio stop-risk permits at most four simultaneous 0.25%-risk positions or two 0.50%-risk positions **only if** their estimated stop losses are additive and funds/margin and liquidation constraints independently pass.
- At an actual 5% stop gap, total modeled loss per notional is 6.21%; 0.5%-budget position loses $1.405%, 0.25%-budget position loses $0.7025% equity. Gap loss is not capped by the stop-risk target.
- At a 3.14% structural stop, same reserves imply 4.35% unit budgeted loss; 0.5% risk -> $11.494253 notional. This is a separate candidate and must NOT silently replace frozen 1% adverse-price cut.

## Key comparability issue
The published 3x/5x *account exposure* simulations are NOT the same strategy as the 0.25%-0.5% risk-sized variant. At a 1% stop and 2.21% unit-loss budget, 3x account exposure would budget 6.63% equity loss, 5x would budget 11.05% equity loss (before larger gaps). Therefore reported $100->$531.16 or $1,308.86 and closed DD cannot be attributed to low-risk sizing. This is a mathematical normalization check, not a finding of actual losses.

## Execution/causality gate for next replay
Match each of the 67 sequential trade IDs to timestamped D250 confirmation, entry intent, earliest eligible quote/trade, stop placement and acknowledgement, M1 and available tick path, fee/funding, mark-price liquidation boundary, opposite-local K2 availability, and exit intent/fill. Record UNKNOWN rather than fabricate fills, book levels or order IDs. Require source hashes and explicit gaps. Compare unchanged 1% cut + opposite-local baseline to 0.25/0.5% risk-sizing using identical trade IDs and identical market costs; only then challenge staged entries or MFE overlays on chronological forward holdout. Rejected flow/MFE, K0/K1, and pyramiding overlays remain rejected.

## Outcome
This iteration provides a reproducible source-grounded algebraic audit and flags non-comparability of exposure versus stop-risk. It does NOT supply per-trade execution replay, monthly net equity, MTM DD, liquidation count, or unseen forward performance. Those remain UNKNOWN until source-matched execution paths exist.
