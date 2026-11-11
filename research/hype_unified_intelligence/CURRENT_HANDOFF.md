# HYPE UNIFIED INTELLIGENCE — CURRENT HANDOFF

Date: 2026-11-11
Repo: cryptobro1985-prog/pandora-testnet
Branch: research/hype-h1-local-v5-oi-microstructure-20261104

## Current state

The project already contains multiple useful but fragmented intelligence layers:

- Online Quant learner:
  `research/hype_quant/learner.py`
- Fin-JEPA:
  `research/hype_local_only/train_fin_jepa_30d.py`
- Local relationship / Cortex layer:
  `research/hype_local_only/live_relationship_miner.py`
  `research/hype_local_only/cortex_daemon.py`
- Existing multi-expert Local ensemble:
  `research/hype_local_only/train_local_ensemble_30d.py`
- Existing entry/MFE contract:
  `research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md`
- New unified tri-brain prototype:
  `research/hype_local_only/train_unified_local_intelligence_v2.py`
- New unified workflow:
  `.github/workflows/hype-unified-local-intelligence-v2.yml`

## Latest verified old ensemble result

Source:
`research/hype_local_only/results/HYPE_LOCAL_ENSEMBLE_LATEST.json`

OOS:
- candidates 253
- true 19
- accepted 166
- TP 16
- FP 150
- FN 3
- precision 0.0963855422
- recall 0.8421052632
- F1 0.1729729730
- median delay 60s

Conclusion:
The old ensemble is high-recall / catastrophically low-precision.
The next research priority is false-positive suppression while preserving recall.

## Existing agent behavior

### Quantum
Good for:
- online adaptation;
- causal numerical relations;
- MFE/MAE/path targets;
- drift/champion-challenger.

### JEPA
Good for:
- temporal sequences;
- latent transition representation;
- multi-stage candidate evolution.

### Cortex
Current live LLM Cortex has degraded at times because the local model returned invalid JSON.
Therefore predictive Cortex in Unified v2 is deterministic relationship-memory.
LLM Cortex must remain explanation/hypothesis layer only.

## New commits

- `4acc9e0b98f15cb69806b8a8f0a96d9f2f672523`
  add unified Quantum + JEPA + Cortex local intelligence v2
- `6479fc984e5912c31ec9776286288166c6c8f59f`
  add unified training workflow over retained data
- `b455f627ca86e64e4b32156021158b8a9feff9ac`
  guard Cortex / extra-history merge against teacher leakage

## Important contract

116 points total:
- 86 causal/quality INPUT
- 28 TARGET_EVAL
- 2 METADATA_ONLY

Only legal causal/quality inputs and causal derived features may enter X.

## Important research boundary

The user wants one intellectual system that can:
1. identify meaningful LOW/HIGH;
2. find strong LONG/SHORT entry;
3. hold through minor corrections;
4. close/flip when the real trend changes;
5. maximize MFE capture.

Do not make Local the only trade trigger.
Use Local confidence as structural intelligence feeding path-quality and exit intelligence.

## Immediate next task

Execute the attached master prompt:
`research/hype_unified_intelligence/PROMPT_FOR_CODEX.md`

Do not restart from zero.
