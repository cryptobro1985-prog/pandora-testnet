# HYPE Deep Local Signature Audit — 2026-11-09

Research/paper only. Real orders remain disabled.

## Scope
Reproduced HARD120 first-signal evaluation across four historical regimes, then enriched every accepted signal with a causal indicator/structure plane available at decision time. Teacher Local labels were scoring-only.

Periods:
- 2026-07-12..2026-08-07
- 2026-08-08..2026-09-01
- 2026-09-01..2026-10-01
- 2026-10-04..2026-11-03

Feature plane: ~678 numeric causal/indicator fields on 208 accepted HARD120 signals, including structure, multi-window returns/range position, EMA/SMA distances, RSI, MACD/PPO, Bollinger, Stochastic/Williams/CCI, ATR/ADX/DI, MFI/CMF, candle geometry, executed flow/trade concentration, volatility/statistics and causal post-extreme path metrics.

## Frozen HARD120 baseline

| Period | LOW true/false | LOW precision | HIGH true/false | HIGH precision |
|---|---:|---:|---:|---:|
| Jul-Aug | 22/2 | 91.67% | 15/5 | 75.00% |
| Late Aug | 17/2 | 89.47% | 19/4 | 82.61% |
| September | 28/4 | 87.50% | 28/5 | 84.85% |
| Oct-Nov | 26/3 | 89.66% | 27/1 | 96.43% |
| Total | 93/11 | 89.42% | 89/15 | 85.58% |

Combined: 182 true / 26 false, precision 87.50%, episode recall 41.18% over 442 completed episodes.

## Development-fit indicator ensembles

After inspecting all four historical regimes, zero-false OR ensembles can be constructed:

LOW:
- retains 87/93 baseline true LOWs
- retains 0/11 baseline false LOWs
- development precision 100%
- episode recall 39.37%
- baseline-true retention 93.55%

HIGH:
- retains 84/89 baseline true HIGHs
- retains 0/15 baseline false HIGHs
- development precision 100%
- episode recall 38.01%
- baseline-true retention 94.38%

Combined:
- 171 true / 0 false
- development precision 100%
- episode recall 38.69%
- retains 93.96% of baseline true signals

This is NOT untouched/OOS evidence. These rules were selected after seeing all four periods and are shadow-only candidates.

## Transferable signature

LOW:
- real LOWs show sustained displacement away from the recent low after structural survival;
- reversal efficiency/DI and short-horizon returns strengthen;
- max-share / largest-trade concentration tends to be lower than in false LOW corrections.

HIGH:
- real HIGHs show persistent downside displacement after the peak;
- negative CMF / selling money-flow context is repeatedly useful;
- low H1 range position, path persistence and M5 reversal efficiency repeatedly separate true from false HIGHs.

Architecture supported by the audit:
STRUCTURE FIRST -> CAUSAL PRICE/FLOW REACTION -> INDICATOR/MICROSTRUCTURE CONFIRMATION.

## Generalization audit

Single-month perfect rules do not generalize as perfect rules.

Chronological examples:
- LOW trained through late-Aug -> September: 22 true / 1 false = 95.65%
- HIGH trained through late-Aug -> September: 18 / 1 = 94.74%
- HIGH trained through September -> Oct-Nov: 20 / 1 = 95.24% for a 3-rule union
- more conservative rules sometimes reach 100% on a held-out block, but coverage collapses

Leave-one-period-out AUC:
- LOW ExtraTrees ~0.807, RandomForest ~0.801
- HIGH ExtraTrees ~0.810, RandomForest ~0.825

Nested high-precision ML:
- LOW: 17 true / 0 false but only ~18.3% retention of baseline true signals; one held-out period emitted no signals
- HIGH: 37 true / 6 false = 86.05%

Therefore the current transferable high-coverage precision ceiling is approximately 90-96%, not 99.9%.

## Statistical limit on a 99.9% claim

Even the 171/171 development result has a two-sided 95% Wilson lower bound of only ~97.80%.

With zero observed failures, approximately 3,838 independent forward successes are required before the two-sided 95% Wilson lower bound reaches 99.9%.

Current history cannot statistically substantiate a 99.9% future precision claim.

## Full-micro data-quality defects found

1. Crossed L50 books:
- 822/6260 Jul-Aug rich snapshots (~13.13%) had negative spread while fullmicro_book_valid=1.
- Old book-derived values on those rows are contaminated.

2. Liquidation missingness:
- absent hourly liquidation source files could be encoded like a genuine zero-liquidation interval.
- this makes missing data indistinguishable from zero activity without an explicit mask.

Fixes applied:
- crossed/locked book (best_bid >= best_ask) is masked invalid and no spread/depth family is emitted;
- fullmicro_book_crossed flag added;
- liquidation windows now require source-availability coverage and emit fullmicro_liq_stream_valid_*;
- missing liquidation source no longer becomes a real zero;
- regression tests added before the large full-micro rebuild;
- workflow checkout changed to triggering SHA semantics rather than a moving branch head;
- result-only status commits excluded from the workflow path trigger.

Old L50/liquidation-derived features MUST NOT be used for promotion until a clean rebuild is validated.

## Decision

- Keep INTERNAL_HARD120_CHECKPOINT_V2 frozen as the primary structural layer.
- Do not promote the 100% development ensemble to core.
- Freeze indicator signatures as SHADOW/FORWARD candidates only.
- LOW is the stronger side.
- HIGH has a real transferable signature, but 99.9% remains unproven and unsolved.
- Rebuild the corrected Jul-Aug rich dataset, then score frozen signatures on genuinely new terminal-forward episodes.
