# HYPE STRICT H1 Real Local — Zero-FP Plateau V1
Date: 2026-11-12
Research/paper only. Real orders OFF.

## Objective
Identify REAL terminal H1 Local High/Low without future leakage. Intrahour same-side extensions update the same H1 hypothesis; they are not independent semantic Locals. Strict H1 L6/K2 terminal labels are teacher/scoring only.

## Data / replay
Causal compact M1 history:
- sealed May 2026
- Jul12-Aug07
- Aug08-Sep01
- Sep01-Oct01
- Oct04-Nov03

Strict H1 teacher was rebuilt directly from compact M1 with:
- lookback L6 completed H1 bars
- lookahead K2 for offline scoring only
- alternating same-side collapse
- only finalized terminal pivots scored

Candidate origin:
- new 6h trailing extreme from causal M1
- more-extreme same-side candidate resets the active lineage
- one-shot checkpoint; no late threshold crossing after the checkpoint
- first accepted candidate inside an episode is scored; later correctness cannot erase an earlier false-first

## Main finding
After exhaustive search over the stable survival/retrace family and comparison with the 116-point causal/rich families, the most robust cross-regime solution was a broad zero-FP plateau, not a narrow rich-feature rule.

### LOW full-size TRUE trigger
- checkpoint age: 285 minutes
- minimum retrace: 130 bps
- minimum retrace fraction versus causal pre-move-180: 0.80
- same-side more-extreme extension before checkpoint: reset / prior hypothesis invalidated

### HIGH full-size TRUE trigger
- checkpoint age: 285 minutes
- minimum retrace: 130 bps
- minimum retrace fraction versus causal pre-move-180: 0.75
- same-side more-extreme extension before checkpoint: reset / prior hypothesis invalidated

The rule family was selected by zero-FP plateau robustness on May+Jul+Aug+Sep rather than maximum TP at one knife-edge point. October was then replayed with the frozen parameters.

## Results
| Side | Period | Episodes | TRUE accepted | False-first |
|---|---:|---:|---:|---:|
| LOW | May | 31 | 12 | 0 |
| LOW | Jul | 21 | 6 | 0 |
| LOW | Aug | 31 | 6 | 0 |
| LOW | Sep | 35 | 11 | 0 |
| LOW | Oct | 37 | 11 | 0 |
| HIGH | May | 31 | 9 | 0 |
| HIGH | Jul | 22 | 10 | 0 |
| HIGH | Aug | 31 | 7 | 0 |
| HIGH | Sep | 36 | 14 | 0 |
| HIGH | Oct | 37 | 15 | 0 |

Combined:
- scored strict-H1 episodes: 312
- accepted: 101
- true-first: 101
- false-first: 0
- observed precision: 100%
- coverage: 32.37%
- LOW coverage: 29.68%
- HIGH coverage: 35.03%
- two-sided exact 95% lower bound for precision with 101/101 successes: ~96.41%

## Entry geometry
Across the 101 accepted signals:
- median distance from exact H1 extreme at entry: ~2.47%
- p90 entry distance: ~4.18%
- worst observed entry distance: ~5.96%
- median remaining move to the next opposite strict H1 Local: ~2.04%
- mean remaining move: ~3.38%
- p10 remaining move: ~0.70%

Therefore this is a high-precision detector, not an early 0.4% detector.

## 0.25%-0.40% early research result
A separate H1-aware replay of 11,324 causal early snapshots was built at first 0.25/0.30/0.35/0.40% reversal. Models/rules were selected from Jul+Aug and calibrated on Sep, then challenged on May/Oct.

Result:
- fixed early TRUE classifiers from price/flow/MFI did not transfer cleanly;
- selected sparse early rules failed one or more later regimes;
- exact early 0.4% TRUE classification is therefore NOT promoted;
- high-confidence FALSE rejection transfers better than TRUE confirmation;
- rich L50/OI/liquidation evidence explains control transfer but did not yield a universal early numeric gate across the available regimes.

## Why the 116-point data still matters
All 86 causal/quality INPUT points remain logged and analyzed:
- structure / price response
- aggressor flow and CVD
- buyer/seller efficiency
- L50 state and liquidity dynamics
- OI / price-OI relationship
- funding/basis/holder ratio
- liquidation burst and exhaustion
- freshness/continuity masks

The strongest physical TRUE-local mechanism remains:
STRUCTURAL EXTREME -> PRICE RESPONSE -> FLOW EFFICIENCY -> LIQUIDATION EXHAUSTION -> BOOK RECOVERY / CONTROL TRANSFER.

However the rich fields are NOT promoted as hard thresholds because their sign/threshold was not stable enough across regimes. They remain shadow diagnostics and future coverage-expansion features. Missing rich data must never be zero-imputed.

## Production research state machine
WATCH
- current H1 approaches/breaks six completed H1 structure.

FORMING
- active H1 creates a candidate extreme.
- every more-extreme same-side print updates the same H1 hypothesis and resets age/retrace.

FALSE/RESET
- more-extreme same-side print invalidates the previous attempted reversal.

TRUE
- only when the side-specific frozen 285m / 130bps / retrace-fraction rule passes.

WAIT
- candidate is neither invalidated nor confirmed.
- no full-size trade.

This deliberately prefers missed Locals over false full-size entries.

## Important limitation
101/101 on preserved history does NOT guarantee future 100% precision. October had already been inspected in earlier exploratory project work, so it is chronological replay rather than a pristine never-seen sealed experiment. A new untouched period is still required for final promotion.

## Next step
Do NOT change this V1 threshold during forward scoring.
Run it shadow on new unseen HYPE data. In parallel, continue searching for an earlier TRUE_RICH path that can raise coverage / reduce entry distance without introducing any false-first signal.
