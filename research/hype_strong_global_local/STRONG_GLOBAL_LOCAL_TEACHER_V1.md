# HYPE Strong Global Local Teacher V1 — 2026-11-10

## Goal
Replace over-fragmented 402 strict H1 L6/K2 pivots with a stronger alternating teacher suitable for trading the major leg LOW -> HIGH -> LOW.

## Source
Historical strict teacher: 402 finalized pivots = 202 LOW + 200 HIGH across May-Nov 2026.

## Collapse rule
Iteratively inspect every alternating triple H-L-H or L-H-L.
If either adjacent leg is smaller than 2.0%, treat the middle reversal as intrawave noise and keep the more-extreme same-side endpoint:
- H-L-H: retain the higher HIGH;
- L-H-L: retain the lower LOW.
Repeat until no collapsible triple remains.

This is a teacher construction rule only. It is not a live predictor and uses no future-derived feature as an input to a trading decision.

## Result
- Strong/global locals: 326
- LOW: 164
- HIGH: 162
- Median alternating swing: 4.782%
- Median local-to-local duration: 8.58h
- Approximate density across preserved calendar span: 1.77 locals/day

Per preserved block:
- May: 52
- June: 78
- Jul12-Aug07: 38
- Aug08-Sep01: 45
- Sep01-Oct01: 57
- Oct04-Nov03: 56

Sensitivity:
- 1.75% collapse -> 348 locals, median swing 4.60%
- 2.00% collapse -> 326 locals, median swing 4.78%
- 2.25% collapse -> 292 locals, median swing 5.19%
- 2.50% collapse -> 264 locals, median swing 5.54%

2.0% is the current V1 teacher floor because it reduces density below ~2/day without arbitrarily forcing a daily count and preserves substantially more legs than 2.5%.

## Preliminary post-local signature on available structural extfeatures
Available candidate table: 486 rows / 74 terminal targets in Oct-Nov structural research. A target is treated as strong when both incoming and outgoing completed legs are >=2.0%.
Strong targets in this dataset: 53 total = 36 discovery + 11 OOS + 6 warmup.

### LOW strong Local vs false candidates in the same strong episodes
Median values:
- new-side efficiency +3m: 0.783 vs 0.364
- new-side efficiency +5m: 0.835 vs 0.381
- new-side efficiency +10m: 1.230 vs 0.521
- retrace +5m: 0.664% vs 0.214%
- retrace +10m: 0.645% vs 0.229%
- retrace +45m: 0.973% vs 0.240%

Paired against the earliest false candidate in the same leg:
- eff_new_3 true > earliest false in 86.4% of comparable strong LOW legs
- eff_new_5 true > earliest false in 77.3%
- price persistence is also higher, but weaker than efficiency itself.

### HIGH strong Local vs false candidates in the same strong episodes
Median values:
- new-side efficiency +3m: 0.481 vs 0.326
- new-side efficiency +5m: 0.638 vs 0.335
- new-side efficiency +10m: 0.850 vs 0.377
- new-side efficiency +45m: 1.824 vs 0.390
- retrace +5m: 0.343% vs 0.214%
- retrace +30m: 0.697% vs 0.188%
- retrace +45m: 0.971% vs 0.219%

Paired against the earliest false candidate:
- eff_new_5 true > earliest false in 78.9% of comparable strong HIGH legs.

## Strongest relationship so far
A powerful terminal Local is best described by a sequence, not one indicator:

STRONG STRUCTURAL EXTREME
-> NO SAME-SIDE EXTENSION
-> PRICE DISPLACEMENT AWAY FROM EXTREME
-> NEW-SIDE PRICE-IMPACT EFFICIENCY RISES
-> CURRENT ATTEMPT OUTPERFORMS EARLIER FAILED ATTEMPTS IN SAME LEG
-> PRICE PERSISTENCE / RETRACEMENT SURVIVES
-> TRADE DIRECTION: LOW -> LONG, HIGH -> SHORT

Raw buy/sell imbalance alone is not a reliable discriminator.

## Small-support zero-FP observation — NOT promoted
For strong HIGH in the Oct-Nov structural extfeatures, a 45m stateful gate with roughly:
- retrace >= 1.0%
- retrace fraction >= 20%
- price persistence >= 55%
- new-side efficiency >= prior candidate efficiency
scored 4/4 discovery and 4/4 OOS with 0 false-first, but support is only 8 signals. This is evidence for the relationship, not a production threshold.

LOW has small zero-FP pockets at ~20m, but coverage is too small to promote.

## Next exact scoring target
Re-label the full preserved history with Strong Global Local V1 and run causal first-signal scoring using only legal 86/116 causal inputs at 30s/60s/180s/300s/5m/10m/15m/30m/45m/60m.
Optimize in this order:
1. minimize false-first;
2. maximize strong-local recall;
3. minimize entry distance from the strong local;
4. preserve remaining swing.

The critical stateful feature is relative evidence versus earlier failed attempts in the same active leg, especially new-side price efficiency + price persistence. L50/liquidation/OI are incremental evidence only where valid and present.
