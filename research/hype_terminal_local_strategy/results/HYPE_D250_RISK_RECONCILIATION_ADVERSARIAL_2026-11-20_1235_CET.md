# D250 sequential risk reconciliation: adversarial execution-accounting audit
2026-11-20 12:35 CET. Research only; no real orders, no detector changes.

## Inputs verified directly from branch
- `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`: frozen D250 rule and 67 finalized opposite-local episodes; only 22.4% coverage; 61.2% median MFE giveback.
- `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`: 67 sequential modeled trades, 22 fixed-cut exits, 0.15% assumed roundtrip costs, 3x/5x account exposure. Not execution-replayed.
- `independent_risk_reconciliation_20261120.py`: code inspected in this iteration.

## New adversarial code-level findings
1. `reconcile_authorization` accepts a caller-provided `underlying_return_fraction`, `funding_fraction` and `actual_roundtrip_fee_fraction` without independent fills, side-aware entry/exit quotes or funding events. It can reconcile fabricated positive returns. Its status explicitly says SCENARIO_RECONCILED_CLOSED_ONLY, not evidence of actual trades.
2. `funding_fraction` is allowed negative and is subtracted from gross PnL; negative funding can be a legitimate credit, but without source, funding timestamps, notional basis and position direction it permits arbitrary manufactured profit. `actual_roundtrip_fee_fraction` is only checked nonnegative; the 0.15% assumption is not reconciled with actual fills.
3. The function checks only `authorized_notional <= maximum`; it does not ensure a fill occurred, that actual fill notional equals authorized notional, or that the same notional was used in fee/funding/return calculations.
4. `prior_open_stop_risk` defaults to zero in `reconcile_authorization`. The no-overlap check only works for fully represented sequential trades; omitted concurrent positions are not independently discovered.
5. `authorize` uses `stop_distance + fee + gap + funding_reserve` as an additive scenario stress. This is useful for sizing but not an upper bound on loss: market gaps may exceed the assumed gap, and liquidation may precede a stop fill.
6. `reconcile_authorization` accepts `actual_roundtrip_fee_fraction` independently of `fee_fraction` used for sizing, allowing actual cost to exceed risk budget without reclassification; similarly it accepts realized adverse returns worse than stressed loss.

## Reproducible numeric counterexample
At equity $100, LONG entry $100, stop $99, fee reserve 0.15%, gap reserve 2%, zero funding reserve, risk budget 0.5%, allowed notional = 0.5 / (0.01+0.0015+0.02) = $15.873015873.
- A 1% favorable underlying move with actual 0.15% roundtrip fees and zero funding yields modeled closed profit $0.134920635, equity $100.134920635.
- An adverse 5% move with the same fee yields modeled loss $0.817460317, **0.81746% of initial equity**, breaching the 0.5% intended stress budget.
- For a six-loss streak, if each loss exactly consumed 0.5% of current equity, the compounded drawdown would be 1-(0.995)^6 = 2.9627%. This is only a budget illustration, not a bound under gaps.

## Promotion gates for real event replay
Require a per-trade immutable record: signal/local ID, local-extreme timestamp, confirmation timestamp, side, entry decision timestamp, bid/ask and L50 provenance, order intent timestamp, fill timestamps/prices/quantities, Mark Price and maintenance tier path, stop trigger and actual exit fill, funding event IDs and debits/credits, net realized cashflow, equity+margin state and MFE/MAE path. Missing fields -> UNKNOWN/NOT VERIFIED, never zero-impute. Recompute gross return from signed fill prices and quantities; reconcile fee/funding from event records, not from claimed scalar PnL. Reject any exit using future opposite-local extreme before confirmation. Enforce portfolio-wide chronological ledger before computing 1% concurrent stop-risk and monthly net/MTM DD. Keep prior rejected MFE overlays rejected.

## Decision
No new execution-verified trades. Do not promote risk reconciler to a live-safety guarantee or extrapolate $100->$531.16 to 0.5% risk. Next step is finding timestamped original 67-trade ledger and matching quote/Mark/L50 tapes; if unavailable, explicitly report incomplete coverage rather than manufacturing monthly metrics.
