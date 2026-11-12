# HYPE ALL-IN-ONE — canonical research handoff

Branch: `research/hype-h1-local-v5-oi-microstructure-20261104`
Scope: research/paper only. Real orders OFF.

This directory is the single source-of-truth index for the HYPE H1 Local project.

## Objective
Detect a REAL H1 Local Low/High as early as causally possible, distinguish it from false/local continuation candidates without lookahead, and preserve as much Local-to-Local MFE as possible.

## Canonical feature contract
- 116 total contract points
- 86 causal/quality INPUT points
- 28 TARGET_EVAL points
- 2 metadata points
- Extra rich fields (L50 book, OI, liquidations, raw microstructure, market context, quality/freshness) are additive evidence and MUST NOT silently redefine the 116-point contract.
- Missing rich data is missing, never zero-imputed.

Source: `research/hype_quant/feature_contract.py`.

## Historical data map
- May 2026 sealed tape builder: `research/hype_full_micro_202605/build_base_may.py`
- June 2026 sealed tape builder: `research/hype_full_micro_202606/build_base_june.py`
- Jul 12–Aug 07 full micro: `research/hype_full_micro_202607/`
- Aug 08–Sep 01 builder: `research/hype_full_micro_202608_late/`
- Sep 01–Oct 01 builder: `research/hype_full_micro_202609/`
- Jul 12–Nov 03 preserved master builder/index: `research/hype_historical_master/`
- Canonical 30D 116-point candidate dataset is recovered by workflow artifact name `local116-HYPE`.
- Enriched historical gaps (mark/index/OI/funding where available): `HYPE-LOCAL-HISTORICAL-GAPS`.
- Rich strong-day / 7-layer / recent raw artifacts are enumerated by the all-in-one workflow and retained as provenance, not silently merged unless teacher/negative alignment is proven.

## Models / intelligence stack
- Local-Only: `research/hype_local_only/`
- Fin-JEPA adapter/training: `research/hype_local_only/fin_jepa_adapter.py`, `train_fin_jepa_30d.py`
- Quantum: `research/hype_quant/`
- Cortex relationship learner: `research/hype_local_only/train_unified_local_intelligence_v2.py`
- Unified Quantum + JEPA + Cortex workflow: `.github/workflows/hype-unified-local-intelligence-v2.yml`
- Latest model families retained as GitHub Actions artifacts:
  - `HYPE-LOCAL-ONLY-CHECKPOINT`
  - `HYPE-LOCAL-ENSEMBLE-30D-*`
  - `HYPE-UNIFIED-LOCAL-INTELLIGENCE-V2-*`

## Teacher / strict real Local
- State-machine contract: `research/hype_terminal_local_strategy/H1_TRUE_FALSE_LOCAL_STATE_MACHINE_2026-11-12.md`
- Zero-FP late teacher detector: `research/hype_terminal_local_strategy/h1_real_local_detector_v1.py`
- Latest plateau report: `research/hype_terminal_local_strategy/results/HYPE_STRICT_H1_REAL_LOCAL_ZERO_FP_PLATEAU_V1_2026-11-12.md`

The late detector is a teacher/reference only. It is NOT the desired trading entry because its median entry distance was ~2.47% from the exact H1 extreme.

## Current research target
Train the unified stack to recognize the same real terminal H1 Local much earlier:
1. LOW and HIGH are separate tasks.
2. Same-side more-extreme prints update/reset the same active H1 hypothesis.
3. Future bars are teacher/evaluation only.
4. First false activation is a hard failure.
5. Optimize lexicographically: false-first -> precision -> true captures -> early entry -> captured MFE.
6. Evaluate with chronological walk-forward and a genuinely fresh frozen forward period.
7. Never promote a rule just because it fits May/Jul/Aug/Sep/Oct after those periods have been inspected.

## Consolidation
Large historical tapes and trained model binaries should NOT be committed directly into Git history. The repository contains reproducible builders, contracts, code, reports, and a canonical artifact manifest. The workflow `.github/workflows/hype-all-in-one-bundle.yml` assembles the current retained data/model artifacts into one auditable bundle without bloating Git history.

See:
- `MANIFEST.json`
- `PROMPT_FOR_OTHER_AI.md`
