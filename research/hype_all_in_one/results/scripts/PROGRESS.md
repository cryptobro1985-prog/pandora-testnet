# PROGRESS v2 (update after each step)
Branch: research/hype-early-local-v2-20261112 (PR draft into research/hype-h1-local-v5-oi-microstructure-20261104)
DONE:
- artifacts inventory -> /workspace/data/ARTIFACT_INVENTORY.json; downloads in /workspace/proj_art (58 + release assets)
- teacher on project compact M1 = 312/101/101/0 exact (/workspace/data/teacher_project_repro.json)
- core.py M1 fix (core_v1.py = old); align -> /workspace/data/align_project_vs_bybit.json
- dataset.pkl rebuilt v2 (v1 copy in /workspace/data/v1/); teacher_continuous rerun (461/152/150/2)
- latency audit -> /workspace/data/latency_audit.json (rerun after liq download for archive part)
- p116 snapshots rebuilt (forward_116.py) 100% match artifact -> p116_alignment.json
- project checkpoints forward -> /workspace/data/project_ckpt_forward.json
- v2a training (no liq) -> /workspace/data/v2a/ (+aggregate)
RUNNING: fetch_liq.py (nohup) -> /workspace/data/liq_raw, resumable
NEXT:
1. when liq done: PYTHONPATH=.:/workspace/pandora-testnet python liq_features.py -> liq_feat_rows.pkl
2. LIQ=1 python train_walkforward.py (OUTDIR default /workspace/data) ; python aggregate.py ; python atlas.py
3. python liq_align.py ; rerun latency_audit.py ; compare_versions.py
4. build_results_v2 (write v2 deliverables into results/), charts, pytest (tests/ incl. test_liquidation_causality.py)
5. RU docs: EARLY_REAL_H1_LOCAL_REPORT.md, RESULT_SUMMARY_RU.md, HYPE_EARLY_LOCAL_FULL_SUMMARY_AND_STRATEGY_RU.md
6. zips v2 + docs zip; commit/push; mark PR ready
PR: https://github.com/cryptobro1985-prog/pandora-testnet/pull/27
PIPELINE: nohup run_v2_pipeline.sh (markers /workspace/data/v2_steps, logs /workspace/data/v2_*.log); rerun same script to resume

## STATUS 2026-11-12: STOPPED by user
- Compute stopped by user instruction. fetch_liq covers 2026-04-24..2026-10-10 14h UTC (3491 hourly files). liq features, LIQ=1 training, liq atlas, v2 zips were NOT run.
- v2a (aligned tape/labels, no liquidations) completed: see v2_alignment/v2a_metrics_raw.json and v2a_mfe_raw.json.
- Final summary: results/HYPE_EARLY_LOCAL_FULL_SUMMARY_AND_STRATEGY_RU.md. PR #27 stays DRAFT (do not mark ready).
