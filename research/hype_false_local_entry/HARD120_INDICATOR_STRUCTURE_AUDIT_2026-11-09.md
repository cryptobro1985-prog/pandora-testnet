# HYPE Local Indicator + Structure Audit — 2026-11-09

## Scope
Historical HYPE blocks already collected:
- 2026-07-12..2026-08-07 (rich/full-micro discovery block)
- 2026-08-08..2026-09-01
- 2026-09-01..2026-10-01
- 2026-10-04..2026-11-03

Primary structural gate: INTERNAL_HARD120_CHECKPOINT_V2. All added features are causal at the signal timestamp. Teacher/evaluation fields were excluded from the final clean search. A temporary leakage bug (`true_first` entering the numeric feature list) was detected and rejected before final scoring.

## Baseline HARD120 across four regimes
LOW: 93 true / 11 false = 89.42% precision; 93 / 221 episodes = 42.08% recall.
HIGH: 89 true / 15 false = 85.58% precision; 89 / 221 episodes = 40.27% recall.

Per period baseline:
- Jul/Aug: LOW 22/24 = 91.67%; HIGH 15/20 = 75.00%
- Late Aug: LOW 17/19 = 89.47%; HIGH 19/23 = 82.61%
- September: LOW 28/32 = 87.50%; HIGH 28/33 = 84.85%
- Oct/Nov: LOW 26/29 = 89.66%; HIGH 27/28 = 96.43%

## Best development-fit zero-false rules
These rules were generated from Jul/Aug thresholds and then selected after comparing performance across all four historical regimes. Therefore they are DEVELOPMENT-FIT / META-SELECTED, not untouched OOS evidence.

### LOW zero-false development rule
- `eff_720 <= 1.0116805654`
- `dist_low_bps_15 >= 22.1449844491`

Historical result:
- Jul/Aug: 15 true / 0 false
- Late Aug: 5 / 0
- September: 15 / 0
- Oct/Nov: 10 / 0
- Pooled: 45 / 45 = 100% historical precision
- Episode recall: 45 / 221 = 20.36%
- 95% Wilson lower confidence bound on precision: ~92.13%, not 99.9%.

### HIGH zero-false development rule
- `ret_90 <= -0.0016653972`
- `eff_3 >= 0.0026877313`

Historical result:
- Jul/Aug: 11 / 0
- Late Aug: 8 / 0
- September: 18 / 0
- Oct/Nov: 10 / 0
- Pooled: 47 / 47 = 100% historical precision
- Episode recall: 47 / 221 = 21.27%
- 95% Wilson lower confidence bound: ~92.44%, not 99.9%.

## Best balanced development points
LOW ~98%: `pos_15 >= 0.4877138606` AND `volume_1m >= 280.982`: 60 true / 1 false = 98.36%, recall 27.15%.
LOW ~95% higher coverage: `eff_90 >= 0.0126544473` AND `pos_180 >= 0.6419060230`: 81 true / 4 false = 95.29%, recall 36.65%.
HIGH ~98%: `eff_3 >= 0.0026877313` AND `volatility_30 >= 0.0006134745`: 48 true / 1 false = 97.96%, recall 21.72%.
HIGH ~95% higher coverage: `align_1440 >= -0.0002175378` AND `ret_90 <= -0.0016653972`: 66 true / 3 false = 95.65%, recall 29.86%; late-Aug remains weak at 86.67%.

## Chronological transfer test (selection uses Jul/Aug only)
LOW: `flow_90 <= 0.2677349479`.
- Jul/Aug 21/21 = 100%
- Later periods combined 66 true / 7 false = 90.41%
- Late Aug 88.24%, September 90.00%, Oct/Nov 92.31%

HIGH: `volatility_20 >= 0.0004932918` AND `pos_180 <= 0.4938243744`.
- Jul/Aug 14/14 = 100%
- Later periods combined 60 true / 7 false = 89.55%
- Late Aug 88.24%, September 86.67%, Oct/Nov 95.00%

Conclusion: the apparent 100% historical rules do not constitute a proven 99.9% detector. Proper transfer remains around ~90% precision at useful coverage.

## Rich Jul/Aug full-micro findings
LOW candidates: `sell_300s_log <= 13.14547` gives 19 true / 0 false among matched HARD120 LOWs.
HIGH candidates: `rev_ret_180s <= 0.00074769` gives 13 true / 0 false; `sell_30s_log >= 9.66575` gives 12 true / 0 false.
These are development-only because later compact periods do not expose the identical full-micro plane.

## System audit
1. Market structure remains the strongest first-stage filter.
2. Indicators are most useful as a precision filter after structural survival, not a replacement for structure.
3. LOW generalizes better than HIGH in older regimes.
4. Zero-false historical filters exist but cover only ~20–21% of all local episodes.
5. Current sample sizes cannot statistically establish 99.9% precision.
6. Freeze discovered rules; future full-116 live episodes must score them without retuning.
7. Recommended shadow tiers: baseline HARD120, balanced precision tier, and zero-false development tier. Real orders remain off.
