# HYPE — H1-close joint 12+7 audit (2026-11-11)

## Contract
- Research only, no live trading code changed.
- Exactly the existing twelve strategic groups plus seven historical rich overlay sources.
- H1 close: candidate recognized at completed hourly candle, relative to six previous completed H1 candles; not a separate 6-hour trading timeframe.
- Future K2/opposite pivot used as labels only. No future fields as signals.
- No fixed percent retracement triggers, new indicators, strategies, score tiers, or H1-close-position decision features.
- Full local report and JSON diagnostics delivered in conversation as H1_12plus7_Joint_Audit_2026-11-11.zip.

## Sample
12 selected UTC days: SEP03 SEP10 SEP17 SEP18 SEP30 OCT05 OCT08 OCT12 OCT22 OCT26 OCT27 OCT30.
140 complete-H1 structural candidate bars, not 140 confirmed locals or trades; 25 terminal final (13 LOW 12 HIGH); 114 nonfinal; 1 censored.
Chronological split first six days train n71; last six test n68 including 13 true terminals, 55 other candidate bars.

## Chronological holdout: fixed research-only regularized logistic diagnostic
| Existing data family | TP | FP | FN | TN | Precision |
|---|---:|---:|---:|---:|---:|
| Core H1 + executed flow / impact | 10 | 22 | 3 | 33 | 31.3% |
| Market only, no candle-position | 13 | 35 | 0 | 20 | 27.1% |
| All available 12+7 | 13 | 35 | 0 | 20 | 27.1% |
| All except L50 snapshot | 11 | 21 | 2 | 34 | 34.4% |
| Only rich | 12 | 42 | 1 | 13 | 22.2% |

All available families, same split, shallow ExtraTrees: TP6 FP19 FN7 TN36. Neither demonstrates near-perfect H1 close decision.
Model probabilities and 0.5 diagnostic split are not intended as live trading thresholds.

## The concrete observed distinctions
- L50 at H1 close: valid 21/25 true, 82/114 other. New-side book top-10 imbalance positive in 16/21 true and 31/82 other. LOW: 9/11 vs 15/36. HIGH: 7/10 vs 16/46. Informative but not unique.
- Opposite-side price response + same-side aggressive 5m flow: 6/25 true vs 32/114 other. Add valid positive book balance: 2/21 true vs 11/82 other. These cannot act as universal fixed gates.
- OI 5m delta positive: 11/23 true vs 55/112 other; no uniform sign.
- Valid 180s public liquidation count positive: 4/16 true vs 30/101 other; absence does not indicate terminal.
- A fixed model's permutation sensitivity on the later-days test was strongest for L50 snapshot (mean ROC-AUC drop ~.109); then flow efficiency ~.036; mark-index-funding ~.030; liquidations ~.028; activity ~.027; aggressor flow ~.025; OI ~.005. Correlated features and sparse data limit causal interpretation.

## Actual seven-block historical limitations
1. Continuous L50 replenishment/cancellation windows are valid at H1 close in 11/139 scored candidate bars, but **0/25 true terminal locals**. Only snapshots in 103/139.
2. Liquidation validity partial.
3. OI delta/notional available when fresh, cannot identify individual opening/closing.
4. Mark/index/funding valid in most; bad derived basis field explicitly excluded.
5. Long/short holder ratio unavailable for historical selected days.
6. Server clock/instrument metadata fetched on collection day are not historical state and are excluded.
7. Gap/freshness masks are quality signals, not directional confirmations.
The seven overlays overlap original groups; they are not seven independent extra predictors.

## Verdict
The evidence of H1 control transfer is real but does not separate every terminal from every nonterminal at the H1 closing moment on held-out days. No “ideal” 25/25 with zero false positives is supported. No extra trading filter or modified live logic was deployed. A truthful future test needs actual valid L50 event dynamics near hour close and untouched later days, rather than projecting absent signals onto history.
