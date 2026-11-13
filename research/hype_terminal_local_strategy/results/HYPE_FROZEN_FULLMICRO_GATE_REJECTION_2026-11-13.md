# HYPE frozen full-micro relation transfer audit — 2026-11-13

Research only; no orders. This checkpoint is a **new numerical comparison of existing frozen holdout results**, not a rerun of inaccessible raw Parquet.

## Verified artifacts
- research/hype_full_micro_202607/results/LOW_HIGH_RELATIONS_LATEST.json
- research/hype_full_micro_202607/results/GLOBAL_LOCAL_RELATION_LATEST.json
- research/hype_full_micro_202607/results/LATEST_MANIFEST.json
- research/hype_all_in_one/MANIFEST.json
- research/hype_full_micro_202607/results/RUN_STATUS.json

## Falsification of exact-extreme multivariate gates
LOW side-specific composite frozen test: 131 rows, 7 true terminal labels, threshold 0.347619, 44 accepted = 3 TP / 41 FP; 4 FN. Precision 6.82%, recall 42.86%, ROC AUC 0.5415; validation precision 6.45%, recall 100% (4/4). Thus the threshold fails the zero-false-first requirement, despite scanning 300 dimensions and 147 stable-weight dimensions.

HIGH side-specific composite frozen test: 120 rows, 5 true labels, threshold 0.203247, one accepted = 0 TP / 1 FP, 5 FN. Precision 0%, recall 0%, ROC AUC 0.5826; validation was 2 TP / 1 FP, 2 FN. Thus no defensible HIGH trading gate from this frozen composite.

Mirrored TERMINAL_SWING_EXHAUSTION composite frozen holdout: 220 rows / 9 true, 31 weighted dimensions; ROC AUC 0.7225, average precision 0.1242, true base rate 0.0409. Top 10% scores: 4 TP / 18 FP / 5 FN; precision 18.18%, recall 44.44%. Ranking better than random is not a safe trade signal.

## New derived test: operational gate rejection
At the actual frozen threshold the side-specific gates yield combined 3 TP, 42 FP, 9 FN across 251 rows and 12 true labels. Combined precision = 3/45 = 6.67%; combined recall = 3/12 = 25%; false discovery proportion = 42/45 = 93.33%. This is a **row-level classification audit**, not first-signal episode precision; no episode-level first-signal claim can be inferred. These thresholds MUST NOT authorize real or simulated local-to-local trades.

The July rich manifest reports 2,733 downloaded hourly files / 4,211,413,622 bytes, but raw_files_retained=false. Archived raw Parquet is not present in this branch, and `research/hype_historical_master/` contains only `build_master.py`. The manifest identifies missing liquidation hourly files; `missing_files` repeats some paths, so count unique missing hours before computing completeness. Source-file counts are not aligned snapshot coverage. Three input IDs 111-113 are unavailable. Latest July run 42660911066 status FAILED and contains zero artifacts when queried. Push workflow run 43388012666 also has zero artifacts. GitHub's public fetch endpoint rejects repo-wide /actions/artifacts; artifact inventory therefore remains incomplete, not empty.

## Next empirical step
Locate successful historic master/rich workflow run IDs through workflow-specific GitHub Actions history, then retrieve artifact IDs via `fetch_workflow_run_artifacts`. If binary artifact expired, rebuild compact M1 using existing scripts and source data; do not assume stored raw files. Evaluate the frozen one-shot 285m gate against episode-level strict H1 labels before comparing new features. Only promote features that survive chronological periods and preserve first-signal precision; compare recall and remaining MFE. Execute trades only in research simulator with actual timestamps, conservative costs and liquidation constraints. No profit or zero-liquidation claim from this checkpoint.
