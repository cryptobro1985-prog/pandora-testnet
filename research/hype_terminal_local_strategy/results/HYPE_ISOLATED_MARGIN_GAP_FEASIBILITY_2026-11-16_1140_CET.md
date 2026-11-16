# HYPE post-local trades — isolated-margin gap feasibility, 2026-11-16 11:40 CET

Research-only algebraic checkpoint. No historical fill claims, new detector thresholds, live orders, or production changes.

## Source audit
Read `HYPE_RISK_NORMALIZATION_AUDIT_2026-11-16_1039_CET.md`, `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`, and `stop_risk_budget_replay_20261116.py` on the existing research branch. Frozen D250 and original 1% adverse-price cut remain unchanged.

## New consistency finding: stop-gap scenario can exceed isolated margin
For $100 equity, LONG entry $100 / stop $99 (or symmetric SHORT stop $101), risk target 0.5% equity, fee reserve 0.15% notional, funding reserve 0.06%, gap reserve 1%:
- budget unit loss 2.21% of notional; position notional $22.624434; initial margin at 25x $0.904977 (4% notional).
- A *scenario* of 5% additional gap past the 1% stop implies 6.21% of notional adverse move-plus-cost = $1.4050; this is 155.25% of the posted initial margin, or 1.405% of equity. The calculation does NOT prove the position could actually remain open to that fill under isolated 25x margin.
- Ignoring maintenance margin and mark/last differences, a 4% adverse move from entry consumes the entire 4% initial margin even before fees. Actual liquidation boundary is generally *closer* after maintenance margin and fees; exchange risk tiers, mark price, collateral mode, and funding must be loaded before declaring any stop fill feasible.
- The modeled stop at 1% is inside the simplistic 4% initial-margin distance, but a 5% gap *beyond the stop* is not. Liquidation may precede hypothetical stop execution. Therefore the prior gap-loss dollar amounts are **unsecured stress loss arithmetic**, not verified stop executions or proof of zero liquidations.
- Even with risk-sized notional, leverage 25x does not make stop execution guaranteed. Require liquidation price/mark-price path and collateral/margin-mode provenance for every matched trade. If unavailable, liquidation count = UNKNOWN, never zero.

## Causal trade-level gate
Keep distinct LOW->LONG and HIGH->SHORT records. Require timestamped D250 confirmation, earliest permissible entry quote, acknowledged protective stop, tick/mark path to stop or causal opposite-local confirmation, costs, and no capital overlap. A minute-bar extreme cannot resolve ordering of stop versus profit. Do not promote rejected tight-trail or K0/K1 overlays.

## Outcome
New analytical finding: the 5%-gap stress scenario at 25x exceeds the isolated initial margin budget, so an execution replay must model liquidation precedence rather than assume the stressed stop fills. Historical matched executions: 0 newly verified in this iteration. Monthly net equity, MTM DD, MFE capture, liquidation count and independent forward results remain UNKNOWN. No new model training.
