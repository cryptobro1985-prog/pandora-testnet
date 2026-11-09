# Prompt for GPT-6.1 Sol / Work — HYPE early terminal Local research

You are continuing an existing HYPE Local-only research program in:
repo: cryptobro1985-prog/pandora-testnet
branch: research/hype-h1-local-v5-oi-microstructure-20261104

FIRST read:
1. research/hype_work_handoff_2026-11-09/MASTER_HANDOFF.md
2. research/hype_work_handoff_2026-11-09/DATA_ARTIFACT_INDEX.json
3. research/hype_work_handoff_2026-11-09/AUDIT_INDEX.md
4. research/hype_quant/feature_contract.py
5. research/hype_false_local_entry/first_signal_objective.py
6. research/hype_strict_h1_guard/terminal_local_state_machine.py

Do not restart from zero and do not re-derive already-settled facts unless you find a concrete contradiction.

## Budget / anti-stall execution protocol — MANDATORY

The objective is not to spend the entire Work/Codex allowance. Preserve budget for later iterations and sealed validation.

### A. Never start with the expensive search
Always work in this order:
1. REUSE: inspect existing reports, cached features, score files and artifacts.
2. CHEAP: vectorized descriptive tests, correlations, quantiles, simple causal thresholds.
3. MEDIUM: small LOW/HIGH models and compact ablations.
4. EXPENSIVE: only the best surviving 1-3 hypotheses may receive ensemble / broad trajectory / heavy-model work.

Do not run a large hyperparameter sweep merely because compute is available.

### B. Limit simultaneous hypotheses
At any research cycle:
- maintain at most 3 active hypothesis families per side;
- rank them before running expensive work;
- kill a branch immediately if it is dominated on first-signal precision, recall AND distance/latency;
- do not resurrect a rejected branch unless new data or a concrete bug changes the premise.

### C. Early-stop rules
Stop an experiment before expensive continuation when ANY of these is true:
- causal leakage or teacher contamination is detected;
- first-signal precision is materially below the existing comparator;
- improvement is only in AUC/accuracy but not first-signal trading metrics;
- improvement exists only on the development block and disappears on chronological validation;
- coverage collapses to a trivial sample with no meaningful gain;
- the result duplicates an already-audited rule/model;
- data quality for required inputs is invalid or missing.

Do not spend more compute trying to rescue a failed hypothesis by repeated threshold retuning.

### D. Progressive sample sizing
Use progressively larger data:
- sanity slice first;
- one development block second;
- chronological transfer third;
- all development regimes only for finalists;
- sealed/OOS only after the exact rule/model is frozen.

Never repeatedly rescore sealed data while tuning.

### E. Reuse expensive intermediate work
Before rebuilding anything:
- search for an existing feature matrix, cached compact M1, full-micro snapshot, labels, artifact or model;
- verify checksum/contract;
- reuse it when valid.

Do not redownload or regenerate the Jul-Nov master, May sealed, June sealed or full116 captures unless the existing artifact is unavailable/corrupt or a documented data-quality fix requires a rebuild.

### F. Checkpoint so a stopped Work session can resume
After every meaningful milestone, commit/update:
research/hype_work_handoff_2026-11-09/WORK_PROGRESS.json

It must contain at minimum:
- current objective;
- current branch/head SHA;
- completed experiments and verdicts;
- rejected hypotheses and WHY;
- active hypotheses ranked 1..N;
- exact command/scripts used;
- artifact/result paths;
- frozen thresholds/model hashes;
- next cheapest useful action;
- expensive actions NOT YET justified;
- known blockers.

Also append concise experiment results to:
research/hype_work_handoff_2026-11-09/EXPERIMENT_LEDGER.jsonl

Never recompute an experiment already present in the ledger unless:
- code/data contract changed;
- the prior run was invalid;
- or a deliberately new holdout is being evaluated.

### G. Token/allowance conservation behavior
Prefer:
- reading targeted files instead of recursively dumping the whole repository;
- concise summaries of large artifacts;
- one script that evaluates several nearby hypotheses vectorially;
- batched/parallel independent cheap checks;
- deterministic cached outputs;
- small interpretable models before heavy ensembles.

Avoid:
- repeatedly rereading the same large files;
- unbounded repository archaeology;
- exhaustive Cartesian grids;
- repeated model retraining with tiny threshold changes;
- multiple expensive models that answer the same question;
- generating long prose before metrics are known.

### H. Per-cycle stopping point
A Work cycle should stop successfully when it has done ONE of these:
- found and validated a materially better frozen candidate;
- rejected the current top hypotheses with evidence;
- produced the next reusable feature/data layer;
- identified a concrete data-quality blocker.

Do not continue spending allowance just because more experiments are possible.

### I. Preserve reserve
Treat roughly the final 25-35% of the available session allowance as reserve for:
- verification;
- tests;
- sealed/OOS scoring;
- writing reproducible results;
- committing checkpoint state.

If the environment does not expose exact remaining allowance, behave conservatively as though the reserve has already begun once the main candidate search is complete.

### J. Anti-hang rule
If a computation, download, workflow or model job fails/stalls:
- do not retry the identical expensive action more than once;
- diagnose the failure;
- switch to a smaller/local/cached path if possible;
- record the blocker in WORK_PROGRESS.json;
- continue with another independent useful task rather than looping.

### K. Final priority order under budget pressure
If the allowance becomes tight, prioritize in this exact order:
1. correctness / anti-leakage;
2. first-signal scoring;
3. LOW/HIGH validation;
4. checkpoint + reproducibility;
5. sealed/OOS test of the single best frozen candidate;
6. only then additional model exploration.

A partial but reproducible result is better than exhausting the allowance on unfinished brute force.

## Mission
Find a causal early signature that distinguishes FALSE H1 Local candidates from TRUE terminal H1 Locals
as close as possible to the extremum, ideally 0.3%-0.7%, with materially better first-signal precision and useful recall than the current early layer.

LOW and HIGH MUST be modeled separately.

## Critical rules
- Never use TARGET_IDS 83-110 as predictors.
- Never use future K2/lookahead information in a predictor.
- Labels are scoring-only.
- Earlier false accepted signal counts as failure even if a later true candidate appears.
- Same-side more-extreme extension resets/replaces the candidate.
- Freeze thresholds/model before any sealed/OOS evaluation.
- Report development, chronological validation, sealed and forward separately.
- Do not call 100% historical precision a future guarantee.
- Real orders stay OFF.

## Current strongest facts you must beat or complement
- Early true-local distance is already near 0.3%-0.7%, but raw precision is poor.
- Strongest causal chain:
  STRUCTURAL EXTREME -> PRICE RESPONSE -> FLOW EFFICIENCY -> LIQUIDATION EXHAUSTION -> BOOK RECOVERY/TRANSFER.
- HARD120 four-regime baseline: 87.5% combined first-signal precision.
- Ultra Survival V2:
  LOW age 215m, retrace >=130bps, >=52% prior-180m recovery.
  HIGH age 250m, retrace >=65bps, >=50% recovery.
  Development 167/167, sealed May 31/31, but late and low recall.
- The main open problem is bringing similar reliability much earlier.

## Research design
Prefer state-transition / trajectory features over static snapshots.

Build causal sequences at:
30s, 60s, 90s, 180s, 300s, 5m, 10m, 15m, 30m.

Explicitly derive:
- reversal-return slope/acceleration;
- price-impact efficiency slope;
- old-side vs new-side efficiency ratio;
- liquidation decay / half-life / burst-to-exhaustion;
- L10/L50 imbalance delta, replenishment, cancellation and absorption transition;
- OI delta x price response;
- trade concentration / max-trade-share transition;
- candidate survival duration and hazard;
- pre-move strength normalized by range/ATR/realized volatility;
- distance-to-extreme normalized by regime volatility;
- whether price fails to extend despite same-side aggressive flow.

Try:
- interpretable sequential rules;
- survival/hazard models;
- monotonic/logistic models;
- tree ensembles;
- calibrated abstaining classifier;
- state machine / HMM-like transition logic if causal and auditable.

Do NOT optimize only accuracy/AUC.
Primary metric: FIRST ACCEPTED SIGNAL per completed swing.

## Required result table
For every serious candidate, LOW and HIGH separately:
- episodes;
- accepted signals;
- TP / FP;
- precision;
- recall / coverage;
- median/p90/worst distance from true extremum;
- median/p90 latency;
- false-local continuation distance;
- by-period stability;
- development vs OOS vs sealed vs forward;
- exact frozen rule/model hash.

## Selection
Return:
1. BEST EARLY LOW.
2. BEST EARLY HIGH.
3. BEST BALANCED LOW/HIGH.
4. BEST MAX-PRECISION LOW/HIGH.
5. Whether any candidate materially improves the 0.3%-0.7% problem.
6. Failure analysis of false positives.
7. Code + tests + reproducible report committed to the same branch.

Do not promote to live-money trading. Shadow/paper only until enough forward terminal episodes exist.
