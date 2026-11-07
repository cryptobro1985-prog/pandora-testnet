# Quantum audit and completed experiment

## Baseline and defects

The archived Local-only core used six River StandardScaler + logistic-regression heads (LOW/HIGH × 60/180/300 seconds). It was a linear snapshot learner, without a learned nonlinear sequence representation. Positive repetition altered posterior class priors; thresholds did not make those scores calibrated probabilities. Persistence, delayed-label and source-clock defects are addressed by the runtime/feature modules. The archived broader hype_quant learner is legacy support, not a trading decision authority.

All original 6261 snapshots are retained. They are repeated views of 1797 candidates, not independent events. Only 77 strict teachers exist, of which 76 have a finalized following opposite swing. The original 5-second and minute-bar snapshot inputs were contaminated by unfinished bars. No model comparison treats those inputs as causal. New causal inputs were rebuilt once from retained completed minute OHLC; gaps and unknown historical receipt latency remain explicit.

## Implemented alternatives and selection

The frozen research model is a regularized linear + temporal histogram-gradient-boosting ensemble, selected by minimum mean walk-forward Brier before final scoring. Alternatives are the causal River logistic baseline, regularized snapshot logistic regression, snapshot HGB and temporal HGB. No GPU is required. The temporal model uses completed price paths and past candidate-stage deltas; this is not a trained Transformer/GRU. Three folds use purged delayed labels and a six-hour embargo. Calibration is a separate chronological segment; candidate groups cannot cross partitions. Features include missing indicators or native tree missing handling. Targets, future observations and unverified historical live-only microstructure never enter the fitted feature matrix.

A first experiment incorrectly allowed some validation outcomes to mature inside the final holdout. It is retained as SUPERSEDED_INVALID_SELECTION_REPORT.json and must not be quoted as valid evidence. The corrected run changed only causal label eligibility, preserved the model-selection rule, and completed before this continuation. No retraining was needed during continuation. The historical holdout was already used by older exported studies; genuinely new forward data is still required.

## Corrected historical holdout comparison

Event metrics deduplicate first accepted side/hour and count all 19 finalized strict teachers in the holdout. Sample PR-AUC/Brier are calculated on 490 stage rows and are not 490 independent events.

| Architecture | Brier | PR-AUC | Event precision | Event recall | Event F1 | True / accepted |
|---|---:|---:|---:|---:|---:|---:|
| causal_river_logistic | 0.1294 | 0.1753 | 0.0000 | 0.0000 | 0.0000 | 0 / 2 |
| snapshot_linear | 0.1212 | 0.1944 | 0.2174 | 0.2632 | 0.2381 | 5 / 23 |
| snapshot_hist_gradient_boosting | 0.1036 | 0.1735 | 0.2000 | 0.3158 | 0.2449 | 6 / 30 |
| temporal_hist_gradient_boosting | 0.1030 | 0.2016 | 0.2500 | 0.0526 | 0.0870 | 1 / 4 |
| linear_temporal_ensemble | 0.1049 | 0.2053 | 0.2174 | 0.2632 | 0.2381 | 5 / 23 |

Selected model: 5/19 true locals detected; 14 missed. Precision 95% interval [0.09663978026586204, 0.4190348301626401]; recall interval [0.11806412346782508, 0.487915508978151]. The recognition objective is not achieved. Lower Brier does not establish useful early Local detection. Architecture is not reselected after viewing final holdout metrics.

Complete per-side/stage results, false signals/hour, event delays and interval uncertainty, regime slices, calibration bins, measured p50/p95/p99 model-call timings, process RSS and paired day bootstrap are saved in HISTORICAL_TRAINING_REPORT.json. These are offline CPU measurements, not live end-to-end latency. API cost is zero for the numerical run; machine cost and paid model price were not measured.

## Saved models and limitations

- champion/local_only_model.pkl is the frozen evaluated research seed; it excludes final OOS training and requires forward validation.
- linear_alternative.pkl and nonlinear_alternative.pkl retain alternatives. A better-looking final metric does not authorize post-hoc selection.
- online_challenger.pkl is an adaptable numerical challenger; online updates do not mutate frozen inference weights.
- full_history_research_only.pkl uses all matured history and is explicitly independent_oos=False. It is not the evaluated champion.
- Side/hour/stage outcomes are deduplicated; ambiguous and terminal labels are censored. Cold starts, missing/stale causal prices, invalid probabilities/thresholds and inference failures abstain.
- Archive coverage is 77 strict/123 internal teachers, but 28 internal teachers lacked retained proposals. Recognition claims concern the strict target, not every possible visual swing.
- The research classifier fits completed-minute features only. L50, liquidation, OI/funding and receive latency remain availability-aware research inputs, not proven predictive improvements.
- Cortex validated zero of 72 hypotheses and contributes no demonstrated accuracy gain. Real-time proposal changes outside the historical six-hour population remain watch-only.

MONITOR UNCHANGED: YES. Real orders remain disabled.
