# HYPE Strong Global Local — Final Historical Cascade Checkpoint — 2026-11-10

## Objective
Detect a powerful GLOBAL/TERMINAL Local after the extreme has already happened and authorize:
- Local LOW -> LONG
- Local HIGH -> SHORT

Priority: minimize false-first confirmations, then maximize coverage. Exact-extreme entry is not required.

## Corrected strong teacher
The original 402 strict H1 L6/K2 labels over-fragment the market for this trading objective.

Offline teacher construction: iteratively collapse alternating H-L-H / L-H-L triples when either adjacent leg is < 2.5%, retaining the more-extreme same-side endpoint. This is teacher construction only, never a live predictor.

Result:
- 268 powerful/global locals
- 135 LOW / 133 HIGH
- median local-to-local move ~5.52%
- median duration ~9.68h
- approximate density ~1.45 locals/day over the preserved calendar span

Compact historical data allowed exact causal matching of 253 inter-local episodes:
- 126 LOW
- 127 HIGH

## Stable causal relationship
STRONG STRUCTURAL EXTREME
-> NO SAME-SIDE EXTENSION
-> PRICE DISPLACEMENT AWAY FROM EXTREME
-> NEW-SIDE PRICE-IMPACT EFFICIENCY
-> PERSISTENCE
-> CURRENT ATTEMPT STRONGER THAN PREVIOUS FAILED SAME-LEG ATTEMPTS
-> CONFIRMED
-> LOW=LONG / HIGH=SHORT

Raw buy/sell imbalance alone is not a reliable discriminator.

On the 2.5% teacher, true strong locals vs false same-leg candidates:
- +5m reversal median ~0.542% vs ~0.282%
- +60m ~1.279% vs ~0.753%
- +120m ~1.825% vs ~0.824%
- +240m ~2.348% vs ~0.926%
- +300m ~2.435% vs ~1.025%

## Historical zero-false cascade

### LOW
- L90_REL: 90m; candidate_ord >=20; retrace >=70 bps; rel_eff >=0.5; persistence >=0.60
- L120_EFF_REL: 120m; eff >=12.5594; leg_age_h >=11.9795; rel_eff >=1.0
- L240_EFF_PERSIST: 240m; eff >=18.23735278; persistence >=0.48
- L300_EFF_PERSIST: 300m; eff >=24.13994198; persistence >=0.44333333

### HIGH
- H60_REL: 60m; retrace >=200 bps; rel_eff >=0.9; persistence >=0.60
- H90_RETRACE: 90m; retrace >=350 bps
- H120_REL: 120m; candidate_ord >=5; retrace >=225 bps; rel_eff >=1.1; persistence >=0.50
- H180_EFF_PERSIST: 180m; eff >=16.9135327; persistence >=0.51666667
- H240_EFF_PERSIST: 240m; eff >=16.67592198; persistence >=0.51666667
- H300_EFF_PERSIST: 300m; eff >=17.0954571; persistence >=0.50666667

Sequential evaluation uses the FIRST passing candidate in each strong leg. An earlier false accepted candidate counts as failure.

## Result on matched May-Nov history
Combined:
- matched episodes: 253
- correct first confirmations: 118
- false-first confirmations: 0
- observed historical precision: 100%
- recall/coverage: 46.64%
- median confirmation latency: 180.1 min
- p90: 240.9 min
- max: 301.0 min
- median price distance from true extreme: 3.227%
- p90 distance: 4.848%
- median remaining fraction of next strong swing: ~42.2%

LOW:
- 51/126 detected
- 0 false-first
- recall 40.48%
- median latency 240.9m
- median entry distance 3.576%
- median remaining swing fraction ~41.2%

HIGH:
- 67/127 detected
- 0 false-first
- recall 52.76%
- median latency 120.9m
- median entry distance 3.148%
- median remaining swing fraction ~47.8%

Signals by period (LOW/HIGH):
- May 6/12
- June 22/26
- Jul12-Aug07 6/1
- Aug08-Sep01 5/9
- Sep01-Oct01 6/12
- Oct04-Nov03 6/7

## OI / liquidations / L10-L50
The rich Jul12-Aug07 full-micro block was re-scored under the 2.5% strong teacher.

Available rich evidence includes Public Trades, OI, liquidation stream, L10/L50 book features and mark/index basis.

Result: rich features carry incremental information but did not outperform the stable price-response/efficiency core strongly enough to become mandatory gates. At +300s on the rich block:
- reversal flow AUC ~0.642
- reversal return AUC ~0.632
- L10 book change AUC ~0.583
- strongest tested old-side liquidation-change signal ~0.578
- OI/basis weaker or inconsistent in this sample

Therefore OI/L50/liquidations remain confidence boosters where valid and present. Missing rich data stays missing, never zero-filled.

## Important residual finding
The only false-first in the unguarded LOW 120m efficiency+maturity rule had deteriorating evidence versus the prior failed same-leg attempt. Adding block #12 relative efficiency (`rel_eff >= 1.0`) removed it while retaining 19 historical true passes in that branch. This is not a new indicator; it is the frozen same-leg comparison block.

## Statistical status
118/118 with zero observed historical false-firsts is a strong historical finding, not a future guarantee. Several thresholds were discovered/inspected retrospectively across preserved history. Freeze this cascade and score genuinely new forward data without retuning before calling it production-proven.
