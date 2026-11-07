# Full saved-history training result

All retained30-day source records were ingested:43,198 completed minutes, executed BUY/SELL notional/counts and concentration, mark/index43,200each, OI8,640 and funding90. Exactly two source minutes are absent. No raw orderbook/liquidation/receive-latency history was invented. The196 derived predictors use completed bars and conservative source-time joins; this is not116 legal model inputs. The canonical contract remains86 predictive /28 evaluation /2 metadata.

## Training completed

Both LOW/HIGH heads trained on every eligible ordinary minute state plus early extreme states. LOW used42,514 matured minute labels; HIGH42,535. These are correlated views of76 finalized strict teacher events (38each), not85,049 independent locals. The unfinished terminal strict event and ambiguous/missing teacher windows remain censored.

Two fixed candidates were evaluated: complete-source HGB and complete-source HGB plus the frozen JEPA representation. Two chronological folds use separate natural-prevalence calibration, delayed-label purging and a6-hour embargo. Architecture selection and side thresholds were fixed before historical final scoring. Quantum Champion and JEPA encoders were not retrained.

| Historical event pipeline | True /19 | False | Precision | Recall | F1 | Median delay on detected events |
|---|---:|---:|---:|---:|---:|---:|
| Previous Champion reference |5|18|0.217|0.263|0.238|180.0s|
|full_hgb|6|33|0.154|0.316|0.207|41.7s|
|full_hgb_jepa|4|30|0.118|0.211|0.151|32.4s|

**Near100% accuracy was not achieved.** The validation-selected `full_hgb` detects earlier in this research replay but increases false signals and has lower F1. It does not replace the previous Champion. Comparisons use the same dates/strict teachers but different complete proposal streams; the period was already inspected by earlier research and cannot prove independent forward superiority.

## Saved artifacts

- `artifacts/full_history_research/evaluated/local_analyzer.pkl`: frozen historically evaluated model, before final-holdout fitting.
- `artifacts/full_history_research/all_history/local_analyzer.pkl`: selected learner fitted once on every matured label across the whole30-day history, as requested. It includes old calibration dates, so its scores are not represented as independently calibrated probabilities. Old-fold calibration mapping/thresholds require fresh forward revalidation.
- `event_memory/`:370 durable representative cases including all76 finalized true locals. Retrieval excludes future-unmatured labels and the current event, groups repeated cases by hour and reports an empirical neighbor frequency with a confidence interval, never a fabricated certainty.
- `PLAN.json`, `FULL_HISTORY_RESULT.json`, `FEATURE_COVERAGE.json`, `CASE_MEMORY_SEED.json`: inputs, timing assumptions, fixed parameters, side/stage metrics, complete-source coverage and memory evidence.
- `features.npz` and frozen JEPA latent matrices are reusable local derivative caches, intentionally omitted from Git/ZIP to avoid duplicating24MB of reconstructible data. All underlying sources and learned models are included; missing caches rebuild in about5seconds without model retraining.

## Unified analyzer API

`unified_local_analyzer.py` accepts normalized closed-minute records and source-timestamped mark/index/OI/funding records. It distinguishes CONTINUATION, LOCAL_CANDIDATE, WARMUP, source-coverage WATCH and ABSTAIN. Authoritative matured H1 confirmation is a separate `accept_teacher` operation; a model candidate cannot flip the confirmed structural leg. It preserves state on restart and rejects a query overlapping model training/threshold selection. Cortex receives numerical evidence and case memory, not authority to inflate a forecast into near-certainty. Incoming target/evaluation point IDs never become fitted inputs.

Example on normalized new data, from `local_intelligence/`:

```bash
PYTHONPATH=src python -m research.hype_local_only.unified_local_analyzer \
  --root . --minutes /path/to/closed_minutes.jsonl.gz \
  --aux-dir /path/to/normalized_aux --as-of-ms ACTUAL_TIMESTAMP_MS \
  --output /path/to/analysis.json
```

Use actual new timestamps after the fitted history. No socket connection or live performance is claimed by this offline smoke test. New live source normalization/receipt times must match the training semantics; missing/stale sources remain explicit. Current cloud Bybit access still requires the previously saved network settings to be applied.

Reproduction/cache reuse:

```bash
PYTHONPATH=src OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 python -m research.hype_local_only.full_history_train
python scripts/validate_release.py --jepa
```

The completed fixed experiment took176.4s with2CPU threads. An unchanged completed result is reused; changed source hashes require a separate experiment directory. No parameter search or post-hoc architecture switch followed final scoring.

Prediction is not authoritative H1 confirmation. Final H1 points can be confirmed later, after the teacher has enough bars; that delay is explicit and is not scored as perfect early ML prediction. The best known independent-forward status remains unverified. Real orders OFF. MONITOR UNCHANGED: YES.

Delayed teacher replay emitted all76 finalized references strictly after maturity. Median final-reference delay was10.38hours. This is a deterministic definition check, not100% early forecasting.
