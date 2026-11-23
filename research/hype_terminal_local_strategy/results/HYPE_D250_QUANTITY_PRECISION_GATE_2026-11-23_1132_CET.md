# HYPE D250 — quantity precision and minimum order gate (2026-11-23 11:32 CET)

Research only; no live orders, no detector retraining, no baseline changes.

## Verified existing inputs
Read frozen walk-forward report and current `d250_side_exact_stop_risk_v2.py` and `d250_full_cohort_gate.py` from the specified branch. The side-exact risk module returns a continuous quantity and reserves entry fee, but does not enforce exchange quantity step or minimum order thresholds. This can create a theoretically risk-compliant position that cannot be submitted.

## New executable check
`d250_quantity_precision_gate.py` applies decimal ROUND_DOWN quantity quantization and checks minimum quantity, minimum notional, cash including entry fee, and modeled stop loss after rounding. It refuses to certify liquidation safety. Exchange step, minimums, fees and leverage are REQUIRED inputs; no Bybit instrument metadata is invented.

Seven deterministic cases were independently exercised in the local research environment (round-down; zero quantity; minimum quantity; minimum notional; insufficient margin; excess stop risk; SHORT) and passed. The checked local prototype and committed module implement the same seven cases, but GitHub CI execution of the committed module is not verified.

Illustrative LONG: raw quantity 0.00499 HYPE, quantity step 0.001 -> 0.004 HYPE. At price $100, notional $0.40. If minimum notional is $1, the order must be rejected; these values are synthetic, NOT claimed Bybit HYPEUSDT filters. Never round UP to satisfy minimum order size because that can violate the risk budget.

## Status and next data gate
No 71-row UTC D250 cohort or matched raw Bybit Public Trades/CVD/L50/OI/liquidation/mark/quotes tape was replayed in this iteration. No new net equity, drawdown, liquidation or MFE evidence. Next: obtain actual historical instrument filters and matched UTC signal/quote/mark records; only then compare unchanged baseline against risk-based sizing, stop execution and exit overlays on exactly the same sample. Preserve rejected trails as rejected. No future exact local extrema as executable exits.
