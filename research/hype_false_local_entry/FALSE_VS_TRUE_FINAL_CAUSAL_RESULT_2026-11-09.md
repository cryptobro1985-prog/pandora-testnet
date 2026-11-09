# HYPE False-vs-True Local — final causal result after sealed May

## Strongest transferable causal chain
STRUCTURAL EXTREME -> PRICE RESPONSE -> FLOW EFFICIENCY -> LIQUIDATION EXHAUSTION -> BOOK RECOVERY/TRANSFER.

### LOW
A true LOW:
- stops printing lower lows;
- retraces faster relative to the recent 60m range;
- has persistent positive reversal return over 1m/3m/5m;
- buyer flow has high price-impact efficiency, not just high notional;
- often follows a long-liquidation climax that then collapses;
- L10/L50 book recovers toward bid support.

False LOW:
- buyer flow may appear but price response is weak;
- long-liquidation pressure remains alive;
- bid recovery is absent/weak;
- another lower low is more likely.

Observed rich-data medians:
- 60s reversal return: Jul-Aug true LOW 0.1344% vs false 0.0396%; Oct-Nov 0.1412% vs 0.0687%.
- 60s reversal flow: Jul-Aug 0.304 vs 0.051; Oct-Nov 0.481 vs 0.123.
- 60s reversal efficiency: Jul-Aug 0.00855 vs 0.00324; Oct-Nov 0.01275 vs 0.00783.
- Jul-Aug long-liquidation 180s exhaustion ratio at +5m: true 0.00018 vs false 0.0415.
- Jul-Aug L10 imbalance change +180s -> +300s: true +0.494 vs false -0.0075.

### HIGH
A true HIGH:
- stops printing higher highs;
- downward retrace persists for several minutes;
- selling pressure actually moves price down;
- short-liquidation squeeze decays sharply;
- near-book shifts toward ask pressure / stops supporting the squeeze.

False HIGH:
- seller burst is not enough;
- price does not sustain downside response;
- short-liquidation stream remains alive;
- another higher high is more likely.

Observed rich-data medians:
- 300s reversal return: Jul-Aug true HIGH 0.1991% vs false 0.0334%; Oct-Nov 0.2212% vs 0.1389%.
- 180s reversal return: Jul-Aug 0.1506% vs 0.0295%; Oct-Nov 0.1681% vs 0.1009%.
- Jul-Aug short-liquidation exhaustion ratio +30s -> +300s: true 0.00219 vs false 0.0564.
- Jul-Aug +60s L10 book imbalance: true HIGH about -0.137 vs false HIGH +0.058.

## Sealed transfer result
Frozen HYPE_LOCAL_ULTRA_SURVIVAL_V2 was scored unchanged on the untouched May 2026 tape:
- 118 completed episodes.
- 31 accepted first signals.
- 31 true / 0 false.
- Observed precision 100%.
- Recall 26.27%.
- LOW 17/17, recall 28.81%.
- HIGH 14/14, recall 23.73%.

This is the strongest untouched-period evidence currently available. It does not prove that future precision is mathematically guaranteed.

## Operational conclusion
For early 0.3-0.7% candidates, do not use raw flow alone. Score the transition chain. If any required link is missing, remain UNCERTAIN. Same-side extension resets the candidate immediately. Ultra Survival V2 is the current maximum-confidence fallback, while the 1m/3m/5m layer remains a sensor/probe until forward false-positive suppression improves.
