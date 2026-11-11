# HYPE Unified Intelligence — Architecture and evidence, 2026-11-11

## Scope and invariant

This is research/shadow only. No broker connector, order key or real-order path is permitted.

The intelligence layer is **not** a local-trigger-only trading strategy.

- **QUANTUM**: tabular, nonlinear and causal numeric scores; can train online on matured labels.
- **JEPA**: causal temporal-sequence representation and candidate evolution.
- **CORTEX**: train-only deterministic relationship-memory as a predictive expert, plus an optional LLM explainer that cannot alter predictive scores.
- **META**: calibrated score arbitration, respecting candidate-group and label-maturity chronology.

Primary engine: `research/hype_local_only/train_unified_local_intelligence_v2.py`.
Reproducible GitHub workflow: `.github/workflows/hype-unified-local-intelligence-v2.yml`.

The experimental policy adapter lives in `research/hype_unified_intelligence/state_machine.py` and provides FLAT/LONG/SHORT/HOLD/CLOSE/FLIP. It is not connected to live broker execution.

## Reused work

- `research/hype_quant/learner.py`
- `research/hype_local_only/fin_jepa_adapter.py`
- `research/hype_local_only/train_local_ensemble_30d.py`
- `research/hype_local_only/live_relationship_miner.py`
- `research/hype_local_only/cortex_daemon.py`
- `research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md`

## Data and ground truth

Canonical HYPE contract: **116 points = 86 causal/quality INPUT, 28 TARGET_EVAL, 2 METADATA_ONLY**. Future teacher labels are NEVER predictive features.

The preserved HYPE master archive spans Jul12–Nov03 2026 with known missing calendar segments Aug07–Aug08 and Oct01–Oct04. July–Aug rich micro has 83/86 causal source points observed or derived; October compact lacks historical L50/OI/liquidations for many periods. Never fill missing source families with zero or label them as measured.

Unified v2 trains only from causally compatible 30D candidate rows; retained other artifacts are inventoried but not silently concatenated. The data-recovery workflow now falls back to `HYPE-HISTORY-20260712-20261103-MASTER` (artifact ID 13650399622) if `local116-HYPE` is not retained.

## Baseline OOS evidence

The existing five-expert local detector, previously evaluated on Oct27–Nov03, had 253 candidates / 19 true, accepted 166, TP 16, FP 150, FN 3, precision **9.64%**, recall **84.21%**. This is REJECTED for trading despite the high recall.

The separate local-free price/flow benchmark on retained master minute bars:
- Jul train: 7,068 eligible 5m samples;
- Aug development: 6,696;
- Sep validation: 8,424;
- Oct previously inspected holdout: 8,480.
- Price+flow on Sep: only 2 accepted events (both favorable-first) — far too little validation support.
- Price+flow on Oct: 12 favorable-first / 18 events, against price-only 9 / 19.
- All results concern **event classification**, NOT executable PnL. A 12bps idealized roundtrip barrier proxy is not an execution model.

Source: `research/hype_unified_intelligence/CAUSAL_PATH_BENCHMARK_V1_REPORT.json`.
Code: `research/hype_unified_intelligence/causal_path_benchmark_v1.py`.
Ledger: `research/hype_unified_intelligence/EXPERIMENT_LEDGER.jsonl`.

## Correctness repairs completed

1. Meta fit/calibration now use distinct chronological candidate groups and a 3h purge; no repeated 60/180/300 stages across the split.
2. Meta calibration support requires at least five positives and 30 independent candidates; inadequate support fails closed.
3. 6h/8h regime windows require contiguous completed 1m history, not adjacent array rows across data gaps.
4. Extra snapshots with incompatible teacher generations cannot be silently merged or labeled false; extra sources are quarantined until validated.
5. Predictive Cortex is deterministic; an invalid LLM JSON must not alter numeric predictions.
6. Paper policy requires causal edge and plausible favorable/adverse ratio before entry, ignores isolated MFE recoil, and waits for persistent opposing price impact to CLOSE/FLIP.
7. Unified training workflow queues rather than cancelling overlapping runs.
8. Historical master is an available recovery route if an older local116 artifact expires.

## Verified CI

Fast paper policy smoke: GitHub Actions run **42970456491**, conclusion **success**; test marker `research/hype_unified_intelligence/SMOKE_LATEST.json`.

Earlier Unified v2 run **42970078877** ended **failure before training** due unavailable `local116-HYPE`. Master fallback patch is commit `519eebea788d182c57467dff124a03a12996273a`. This is NOT a trained result.

Do not report Unified v2 as validated until its actual JSON report and model artifact are available, with LOW/HIGH precision/recall, false-first rates, ablations, and historical OOS recorded.

## Next priority

1. Verify the post-fallback workflow finishes and publishes its report; fix blocking tests or missing corpus files only if documented.
2. Evaluate all tri-brain ablation arms with grouped meta splits and honest calibration support.
3. Quantify repeated false-positive patterns separately LOW/HIGH; do not retune using the already-inspected historical OOS.
4. Fit separate entry-path and MFE-protection models on full micro where source families are actually available.
5. Evaluate the frozen resulting state machine on a genuinely unused chronological forward period using realistic orderbook execution.
6. Promote only to paper/shadow on reproducible benefit. **REAL ORDERS OFF**.
