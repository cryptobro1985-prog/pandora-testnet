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
