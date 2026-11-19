# D250 execution risk: reference-entry versus actual-fill stop anchoring — 2026-11-19 04:27 CET

Research only; frozen detector, production and orders unchanged.

## Sources checked in this run
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md (frozen D250; 67 causal exits, median MFE giveback 61.2%).
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md (1% cut **below/above entry**, 67 simulated sequential trades; only 0.15% round-trip cost assumed).
- HYPE_D250_ENTRY_AND_EXIT_SLIPPAGE_BUDGET_2026-11-19_0329_CET.md (4.49% reference-entry stress budget).

## New consistency finding
The 1% adverse-price cut is defined relative to **actual entry fill** in the frozen loss-cut description. The latest 4.49% budget adds 0.25% entry-side slippage on top of a 1% distance from actual fill, which is conservative for reference-price accounting but **double-counts** entry slippage if the stop itself is anchored to the actual fill. Never mix these two conventions.

For actual-fill anchored stop, stress loss fraction of filled notional is 1% adverse fill-to-stop + 0.15% round trip fees + 0.09% funding + 3% stop gap = 4.24%. At $100 equity:
- 0.25% risk => $0.25 / 0.0424 = $5.8962264151 notional.
- 0.50% risk => $0.50 / 0.0424 = $11.7924528302 notional.

For reference-price anchored budget, explicitly reserve 0.25% adverse entry fill versus reference: total 4.49%; notional $5.5679287305 / $11.1358574610 respectively. These numbers are **not competing empirical estimates**: they have different accounting anchors. Realized PnL must always be computed from actual fills; the pre-fill risk budget must use an explicit reference/expected-fill price.

## Executable invariant for matched replay
1. Signal timestamp <= order arrival <= first eligible book quote <= actual fill; stop price computed from fill and tick-rounded **against** the position.
2. LONG fill from ask-side liquidity, stop exit bid-side; SHORT fill bid-side, stop exit ask-side.
3. Record both `reference_mid` and `fill_vwap`, and compute realized signed price PnL from `fill_vwap` only. Do not subtract the same entry slip again as an additional PnL charge.
4. For a pre-fill reference-based budget, account for expected reference-to-fill loss once and recompute actual remaining stop-risk immediately after fill. If risk > budget, reduce/skip; no increasing size.
5. Mark-price liquidation boundary, minimum quantity/notional, step/tick, available margin, funding schedule and stop gap require actual contemporaneous data. Missing values => UNKNOWN/REJECT, not zero.
6. Apply both accounting conventions to the **same** 67 UTC trade rows once the underlying tape and timestamps exist; compare unchanged 3x baseline and 0.25%-0.5% risk-sizing variants without overlapping capital reuse.
7. Causal opposite-local exits must use confirmation availability, never future exact opposite extreme. Rejected trailing/MFI-flow overlays remain rejected.

## Result and limits
This is a new cross-document execution-accounting audit with reproducible arithmetic, not a 67-trade matched replay. The 67-trade compound, monthly net equity, fills, liquidation counts, mark-to-market DD and MFE capture remain unverified at event level. No new OOS performance claim.
