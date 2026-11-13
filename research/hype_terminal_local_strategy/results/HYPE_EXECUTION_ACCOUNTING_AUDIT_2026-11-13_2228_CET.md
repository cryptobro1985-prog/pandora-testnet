# HYPE execution-accounting audit — 2026-11-13 22:28 CET
Research only. No retraining, no production edits, no orders.

## Inputs verified in this run
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md: 67 sequential completed trades; 22 fixed-cut exits; 49.25% net-positive; 5x equity $100 -> $1308.86, closed DD 29.36%; 3x $100 -> $531.16, closed DD 18.56%; worst modeled 5x trade -5.75%; round-trip fee assumption 0.15% notional.
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md: frozen D250 71/71 first accepted, 67 fully finalized next opposite locals, median MFE giveback 61.2%, median MAE -0.414%, worst observed -1.958%, late-Aug causal-exit win rate 27.27%.
- HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md: rich inputs nonuniform; exit requires sustained opposite price-impact/control transfer, not counter-volume alone; rejected overlays remain rejected.

## New exact accounting reconciliation
49.25% of 67 is 33 net-positive trades (33/67=49.2537%), hence 34 nonpositive. Of the 67, 22 ended via fixed-cut; therefore **at least 12 of the 34 nonpositive trades were NOT fixed-cut exits**, even if all 22 fixed-cut exits were nonpositive. If any fixed-cut exits were positive, non-stop nonpositive count is larger. This is a strict lower bound, not a reconstructed trade ledger.

The 5x worst modeled trade of -5.75% account equity corresponds to -1.15% of position notional (ignoring position size drift within a trade), compatible with 1% adverse move plus 0.15% modeled round-trip fees. The published 3x worst -3.45% gives the same -1.15% per notional. This agreement tests arithmetic consistency but does not verify tick fills, mark-price liquidation, or intratrade equity DD.

## Counterfactual fixed-risk sizing, NOT a backtest
For a 1% adverse price stop plus 0.15% round-trip fee and no extra gap, cost is approximately 1.15% notional. To cap nominal planned equity loss at 0.25% / 0.50%, notional-to-equity = 0.25/1.15 = 0.21739x / 0.50/1.15 = 0.43478x. For a 1% additional adverse gap, 2.15% notional loss implies 0.11628x / 0.23256x. These are planning ceilings before actual maker/taker fees, funding, liquidity, and mark-price constraints; side-specific fees vary slightly with exit notional. Position leverage and isolated-margin liquidation buffer are independent of account exposure. At 25x isolated, risk of liquidation before a stop cannot be ruled out.

## Trade-level replay required (not performed in this checkpoint)
Recover an immutable ledger with trade_id, direction, local extreme timestamp, D250/earlier frozen authorization timestamp, entry decision timestamp, next executable quote timestamp, price, size, actual/assumed fee tier, funding timestamps, stop activation and fill, mark-price liquidation series, opposite-local K2 availability, MFE/MAE path and realized exit. Reconcile 67 unique sequential trades against the published aggregates before comparing any overlay. Reject periods missing trade timestamps or mark/quotes for liquidation conclusions; never zero-fill L50/OI/liquidation.

## Decision
No promotion. New hard evidence: >=12 nonpositive exits not explained by the 22 fixed-cut exits. The bottleneck is both causal exit and execution validation. Preserve 1% adverse cut and rejected overlay status until same-sample independent replay changes the evidence.
