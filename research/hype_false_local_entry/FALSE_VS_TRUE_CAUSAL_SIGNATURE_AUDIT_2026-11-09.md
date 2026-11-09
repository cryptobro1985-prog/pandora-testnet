# HYPE False vs True Local — causal rerun, 2026-11-09

## Scope
Re-run over all four preserved periods (Jul–Aug, late-Aug, September, Oct–Nov) using STRICT H1 L6/K2 terminal labels.
Candidate definition: current M1 breaks the extreme of the six previous fully completed H1 bars. A candidate is discarded at a 5/10/15m checkpoint if a more-extreme same-side price appears before that checkpoint. Features use completed/causal data only.

## Main result
The only relationship that survives every regime cleanly is **price response after the candidate**, preferably normalized by recent range. Raw buy/sell flow alone is not a reliable terminal-local classifier.

### LOW
True LOW reacts faster than false LOW.
- 5m: retrace/range60 AUC by period = 0.760 / 0.718 / 0.731 / 0.668.
- 10m: retrace/range60 AUC = 0.756 / 0.703 / 0.680 / 0.701.
- At rich snapshots, 60s reversal return AUC transfers Jul–Aug -> Oct–Nov: 0.762 -> 0.699.
- Median 60s reversal return: Jul–Aug true 0.1344% vs false 0.0396%; Oct–Nov true 0.1412% vs false 0.0687%.
- Median reversal flow at 60s: Jul–Aug true 0.304 vs false 0.051; Oct–Nov true 0.481 vs false 0.123.
- Median reversal efficiency at 60s: Jul–Aug true 0.00855 vs false 0.00324; Oct–Nov true 0.01275 vs false 0.00783.

Interpretation: a true LOW is not merely “many buyers”. Buyers must move price away from the low quickly and efficiently. If buy flow appears but price barely reacts, the LOW is usually provisional/false.

### HIGH
True HIGH separates more slowly.
- 15m raw retrace AUC by period = 0.664 / 0.663 / 0.688 / 0.684.
- 15m retrace/range60 AUC = 0.661 / 0.698 / 0.678 / 0.679.
- Rich 300s reversal return AUC Jul–Aug -> Oct–Nov = 0.816 -> 0.693.
- Median 300s reversal return: Jul–Aug true 0.1991% vs false 0.0334%; Oct–Nov true 0.2212% vs false 0.1389%.
- Median 180s reversal return: Jul–Aug true 0.1506% vs false 0.0295%; Oct–Nov true 0.1681% vs false 0.1009%.

Interpretation: a true HIGH needs persistent downward price response for several minutes. A short burst of sellers at the top is insufficient.

## Full-micro mechanism (Jul–Aug rich data)
These are development findings because identical L50/liquidation history is not available for every preserved period.

### True LOW: liquidation climax -> exhaustion -> bid recovery
- 30s rolling long-liquidation notional (60s window): median true ~3103 vs false ~909.
- 30s 300s-window long liquidations: true ~9673 vs false ~4049.
- By +5m, the 180s liquidation exhaustion ratio (value at +300s / value at +30s) is median **0.00018 true vs 0.0415 false**, AUC ~0.692.
- L10 order-book imbalance change +180s -> +300s: median **+0.494 true vs -0.0075 false**, AUC ~0.688.

Meaning: a real LOW often arrives after a liquidation flush. The flush then stops, and near-book liquidity recovers toward bids. A false LOW more often keeps liquidation pressure alive and lacks a clean bid-side recovery.

### True HIGH: squeeze exhaustion
- Short-liquidation 180s exhaustion ratio +30s -> +300s: median **0.00219 true vs 0.0564 false**, AUC ~0.627.
- 300s-window short-liquidation change +30s -> +300s: median **-177 true vs -6 false**, AUC ~0.623.
- At +60s, L10 book imbalance median is approximately **-0.137 true HIGH vs +0.058 false HIGH** in Jul–Aug.

Meaning: after a true HIGH, the short squeeze stops feeding the move and ask-side pressure starts to dominate. If shorts continue being liquidated after the supposed HIGH, the HIGH is more likely false and price can extend upward again.

## What failed
- Absolute fixed retrace thresholds do not transfer consistently between regimes.
- Simple 2–3 feature rules selected on Jul–Aug + late-Aug lose precision on September/Oct–Nov.
- ExtraTrees / HistGradientBoosting / Logistic models trained on Jul–Aug and calibrated on late-Aug do not produce stable high-precision 5–15m classification on both later periods.
- Therefore there is no honest single formula yet that converts the 0.3–0.7% early candidate zone into 90–99% terminal-local precision.

## Best causal signature to use now
### LOW score should increase when:
1. no new lower low appears;
2. retrace grows quickly relative to 60m range;
3. 1m/3m/5m reversal returns are positive and persistent;
4. buyer-side flow is positive **and price efficiency is high**;
5. long-liquidation burst is followed by strong exhaustion;
6. near-book imbalance recovers toward bids.

### HIGH score should increase when:
1. no new higher high appears;
2. 3m/5m/15m downward retrace is persistent relative to 60m range;
3. sell-side pressure actually moves price down;
4. short-liquidation squeeze decays strongly after the candidate;
5. near-book shifts toward ask pressure / stops supporting the squeeze.

## Engineering conclusion
Do not classify early candidates from raw flow alone. Use a **causal transition signature**:
`STRUCTURAL EXTREME -> PRICE RESPONSE -> FLOW EFFICIENCY -> LIQUIDATION EXHAUSTION -> BOOK RECOVERY/TRANSFER`.
If the chain is incomplete, remain UNCERTAIN. Same-side extension immediately resets the candidate.

This is a research/shadow result. Real orders remain OFF. No future guarantee is claimed.
