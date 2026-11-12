# HYPE strict-H1 post-local minimal rule — walk-forward audit
Date: 2026-11-12
Research only. No live-order authorization.

## Objective
Detect a high-confidence entry AFTER a strict H1 local has already formed, rather than predict the exact extreme. LOW implies LONG; HIGH implies SHORT. Same-side extension invalidates the candidate. The first accepted signal is scored; later correct signals do not erase an earlier false-first.

## Data and limitation
Preserved periods: sealed May 2026, Jul12–Aug07, Aug08–Sep01, Sep01–Oct01, Oct04–Nov03.
The full 116+ rich microstructure schema is not uniformly present on every historical minute. Therefore the transferable minimal rule uses causal fields present across all periods. Rich L50/OI/liquidation/funding are confirmation/veto evidence where present, never zero-imputed.

## Frozen minimal entry rule
Checkpoint = 250 minutes after the local candidate/extreme, only if no more-extreme same-side print has invalidated it and the next opposite strict H1 local has not already occurred.

1. rev_atr > 2.0840049433824706
2. trade_ratio5 > 0.2727842248141979
3. flow15 < 0.4504731635235635

LOW -> LONG; HIGH -> SHORT.

Definitions:
- rev_atr = side-normalized displacement from local/candidate divided by H1 ATR14.
- trade_ratio5 = last-5m trade count / expected 5m activity from pre-local 60m baseline.
- flow15 = LOW: (buy_notional15-sell_notional15)/(buy+sell); HIGH: (sell-buy)/(buy+sell).

## MFI
MFI14 calculated causally from M1 typical price × volume.
- base: 71 true / 0 false
- + side-normalized MFI delta > 0: 66 / 0
- + MFI on new-side of 50: 43 / 0
- + positive 5m MFI slope: 31 / 0
MFI therefore does not create the minimal edge; it can be an optional conservative confirmation. Requiring MFI delta > 0 reduces coverage without observed precision gain.

## Walk-forward / OOS
Selection/ranking:
- train Jul12–Aug07
- validation Aug08–Sep01, zero-FP required
- untouched OOS Sep01–Oct01
- untouched OOS Oct04–Nov03
- untouched sealed OOS May

Frozen-rule results:
- Jul train: 9 / 0
- late-Aug validation: 12 / 0
- September OOS: 23 / 0
- Oct-Nov OOS: 12 / 0
- sealed May OOS: 15 / 0
Total 71 accepted / 71 true / 0 false, coverage ~22.4% of 317 scored episodes.
OOS-only: 50 / 50, coverage ~23.7%.

At D250 the unfiltered surviving-candidate baseline was 194 true / 65 false (~74.9% precision).
Descriptive Fisher/binomial significance versus baseline was ~1e-8 to 1e-9 overall; OOS-only binomial ~8.3e-7. These p-values are not multiplicity-adjusted for rule screening.
Exact 95% binomial lower confidence bound: ~94.9% for 71/71, ~92.9% for OOS 50/50.

## Swing geometry (oracle next-local extreme, not causal exit)
67 entries had a fully finalized next opposite Local:
- 67/67 positive gross to exact next Local extreme
- mean +2.906%, median +2.046%, p10 +0.519%, p90 +5.490%, max +20.779%
- median full local-to-local swing 5.256%
- median captured fraction after entry 41.62%, mean 42.69%
With diagnostic structural stop = 0.25 H1 ATR beyond original local:
- median price risk 3.140%
- mean target potential 0.989R, median 0.611R, p90 2.070R
- median MAE -0.414%, worst observed -1.958%

The high-precision rule is late and does not capture the whole swing.

## Causal exit audit
Exit when next opposite strict H1 Local becomes K2-available:
- n=67
- winrate 67.16%
- mean PnL +1.297%, median +0.781%
- mean realized R +0.412R, median +0.261R
- median hold 7.43h
- median MFE giveback 61.2%
- at 1% equity risk/trade, sequential closed-trade max DD ~4.36%, max loss streak 4

Late-Aug failure: winrate 27.27%, mean PnL -0.727%, mean R -0.361R.
Therefore this exit is not robust enough for promotion.
MFI+flow exit was negative expectancy and rejected. Fixed ATR trailing grids were also rejected because late-Aug remained negative.

## Rich-data fail conditions / vetoes
Core causal chain supported by rich history:
STRUCTURAL EXTREME -> PRICE RESPONSE -> FLOW EFFICIENCY -> LIQUIDATION EXHAUSTION -> BOOK RECOVERY / CONTROL TRANSFER.

Reject/cancel when:
- new same-side extreme prints;
- next opposite Local occurs before D250;
- rev_atr <= 2.0840;
- trade_ratio5 <= 0.27278;
- side-normalized flow15 >= 0.45047;
- M1/H1 gaps or invalid calculations;
- live old-side liquidation cascade is still accelerating;
- L50 is stale/crossed/invalid;
- OI + funding strongly expand in old-trend direction while price response fails.

Rich vetoes do not get universal hard numeric thresholds because identical L50/liquidation/OI history is not available across every preserved period.

## Risk
No rule guarantees no liquidation. Hard stop must be before liquidation. Diagnostic stop is 0.25 H1 ATR beyond original local; entry is already >2.084 ATR away, so median stop distance from entry is ~3.14%. Leverage must be derived from stop distance + maintenance margin + gap/slippage buffer, not chosen first.

## Verdict
One simple post-local entry pattern transferred with 0 observed false-first signals across three untouched OOS periods, but only ~22% coverage and a late ~250m confirmation. Entry edge supports shadow/paper forward testing. A robust universal profit-protection/exit layer is not yet demonstrated, so this is not a completed live strategy.
