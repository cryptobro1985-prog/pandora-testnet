# Numeric JEPA: completed bounded experiment

Полный проход по всей сохранённой истории и новый анализатор: [FULL_HISTORY_RESULTS.md](FULL_HISTORY_RESULTS.md).


**Champion remains `linear_temporal_ensemble`. JEPA promotion and forward activation are OFF. MONITOR UNCHANGED: YES. Real orders OFF.**

Implemented an independent CPU JEPA:32-unit GRU context encoder;16-dimensional latent; detached EMA target; horizon-conditioned residual predictor; temporal masking and variance/covariance regularization. Context is60 completed minutes, pooled over fast/medium/structural scales; targets are1/3/5 minutes. Total21,352 parameters including EMA. Source ideas/licenses and pinned reference commits: `docs/JEPA_REFERENCES.json`. No external model code/weights copied.

The retained minute archive is reused. Labels never enter SSL. Features have a fixed16-field numeric candle/flow allowlist and explicit observation masks. Missing flow/L50/liquidations/latency are not fabricated. Normalization and encoder fitting stop before20October; supervision, calibration, threshold selection and historical holdout remain separate. No old Quantum training was repeated. Subminute targets cannot be supported by this minute archive.

## Results

One fixed run:8 epochs,4,497 training windows,143 disjoint validation windows,2CPU threads,9.25seconds measured fitting/screening. Training objective fell0.02960→0.00557 (exact history in `JEPA_SCREEN.json`). Mean latent MSE0.00545 vs persistence0.00638 and train-mean0.04377. Across-sample latent std0.173; effective rank3.48/16. Aggregate screening passed; the1-minute horizon alone was worse than persistence. This short-window result does not establish robust market understanding.

Exactly two frozen probes were tested using two chronological folds. Choice was fixed by validation event F1 then Brier before scoring the historical holdout. No larger model, fine-tuning, visual JEPA or hyperparameter search followed.

| Historical holdout | Precision | Recall | Event F1 | False signals | Brier |
|---|---:|---:|---:|---:|---:|
| Existing Champion |21.7%|26.3% (5/19)|0.238|18|0.1049|
| JEPA linear |17.1%|31.6% (6/19)|0.222|29|0.1101|
| Quantum + JEPA linear (selected before OOS)|18.2%|31.6% (6/19)|0.231|27|0.1231|

**Local improvement gate failed.** Scaling stopped. Per-side/stage precision/recall, PR-AUC, calibration, false signals/hour, delays, missed locals, confidence intervals and paired-day Brier comparisons are in `artifacts/jepa_research/JEPA_COMPARISON.json`. The period was used by prior studies and remains historical evidence, not a new independent forward result. The encoder sees future windows only as detached SSL targets within its training cutoff.

## HIGH78.5515 replay

Archived stage300 HIGH probability was0.9971. A higher candidate78.5575 followed53.995seconds later; all three delayed old labels were false. New runtime explicitly supersedes the prior candidate and invalidates its signal; `expected_side` stays governed by the authoritative teacher.

The saved feature-state contains M1 candles for this event. A retrospective closed-minute reconstruction was run with frozen models: stage300 JEPA+Quantum HIGH0.0578, CONTINUATION0.7798; its validation-fixed local threshold0.1658 would reject HIGH. Missing original receipt/tape history prevents a faithful live replay. This selected incident cannot establish general quality; the overall detector gate still fails. Exact sources, old/new probabilities, future latent predictions, evaluation-only errors and limitations are saved in `INCIDENT_SOURCE.json` and `INCIDENT_REPLAY.json`.

## Saved state and operation

- `artifacts/jepa_research/ssl_checkpoint/`: coherent generations holding context/target/predictor weights, optimizer, normalization, config, training cutoff, dataset hash, RNG, completed epochs, probe references and promotion status.
- `jepa_linear.pkl`, `quantum_jepa_linear.pkl`: frozen calibrated three-class probes (0CONTINUATION/1LOW/2HIGH) with SHA-256.
- `jepa_online.py`: isolated challenger-only learner; future targets wait for availability; pending contexts and exactly-once event IDs survive restart. Encoder changes invalidate old heads for promotion. No live learning process was enabled after the failed gate.
- `jepa_research.py`: research-only leg policy, MFE/MAE/gross cost-unmodelled statistics, delayed error memory and causal Cortex diagnostic filter. Live entry/exit/PnL quality is unverified.
- Cortex can receive additive latent diagnostics; immature forecast errors are redacted. It cannot promote a model. The current failed challenger is not connected to live decisions.

From `local_intelligence/`:

```bash
python -m pip install -r requirements-dev.txt -r requirements-jepa.txt
python scripts/validate_release.py --jepa
PYTHONPATH=src python -m research.hype_local_only.jepa
PYTHONPATH=src python -m research.hype_local_only.jepa_probe
```

Completed runs reuse the checkpoint/report and refuse changed input hashes. An interrupted SSL run resumes remaining epochs with its optimizer/RNG. Corrupt-current generation uses a verified fallback. New research datasets require an explicitly separate challenger directory. Do not repeatedly train on, or tune to, this holdout.

Next valuable work is new independent source-timestamped paper evidence or a new preregistered research hypothesis. Keep the simpler Champion; do not activate JEPA forward promotion on this result.
