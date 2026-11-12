# PROMPT FOR OTHER AI — HYPE EARLY REAL H1 LOCAL

You are continuing an existing research project. DO NOT restart it, rename the problem, or invent a new trading strategy.

Repository:
`cryptobro1985-prog/pandora-testnet`

Branch:
`research/hype-h1-local-v5-oi-microstructure-20261104`

Start by reading:
1. `research/hype_all_in_one/README.md`
2. `research/hype_all_in_one/MANIFEST.json`
3. `research/hype_terminal_local_strategy/H1_TRUE_FALSE_LOCAL_STATE_MACHINE_2026-11-12.md`
4. `research/hype_terminal_local_strategy/results/HYPE_STRICT_H1_REAL_LOCAL_ZERO_FP_PLATEAU_V1_2026-11-12.md`
5. `research/hype_quant/feature_contract.py`
6. `research/hype_local_only/train_unified_local_intelligence_v2.py`
7. `research/hype_local_only/train_local_ensemble_30d.py`
8. `research/hype_local_only/fin_jepa_adapter.py`
9. `research/hype_quant/learner.py`
10. `research/hype_local_only/cortex_daemon.py`



## IMPORTANT: WHERE THE DATA ACTUALLY LIVES

Do not assume every dataset is a normal Git tree file.

There are TWO storage classes:

A) NORMAL REPOSITORY FILES — directly readable in the branch:
- research/hype_all_in_one/**
- research/hype_quant/**
- research/hype_local_only/**
- research/hype_terminal_local_strategy/**
- research/hype_full_micro_202605/**
- research/hype_full_micro_202606/**
- research/hype_full_micro_202607/**
- research/hype_full_micro_202608_late/**
- research/hype_full_micro_202609/**
- research/hype_historical_master/**

B) LARGE DATA / MODEL BINARIES — stored as GitHub Actions artifacts, NOT as ordinary files:
- local116-HYPE
- HYPE-LOCAL-HISTORICAL-GAPS
- HYPE-HISTORY-20260712-20261103-MASTER
- HYPE-LOCAL-ONLY-CHECKPOINT
- HYPE-LOCAL-ENSEMBLE-30D-*
- HYPE-UNIFIED-LOCAL-INTELLIGENCE-V2-*
- HYPE-LOCAL-RAW-*
- HYPE-RICH-STRONG-*
- HYPE-7LAYER-*

If your GitHub tool cannot read Actions artifacts, DO NOT report that the files are missing and stop.
Instead:
1. Rebuild May from research/hype_full_micro_202605/build_base_may.py
2. Rebuild June from research/hype_full_micro_202606/build_base_june.py
3. Use the preserved code/manifests in research/hype_historical_master/ to reconstruct or identify Jul-Nov sources.
4. Use existing committed reports and code to continue analysis.
5. Explicitly list which artifact-only datasets your tool cannot access.
6. Never invent their contents.

The all-in-one workflow is an assembly convenience, not a prerequisite for understanding the project.


## Mission

Build the earliest possible CAUSAL detector of REAL terminal H1 Local Low / Local High for HYPE.

The trading geometry is Local-to-Local:
- confirmed/early Local Low -> LONG
- hold while the Local-to-Local move remains valid
- protect MFE when evidence of the opposite Local begins
- opposite Local High -> close/reverse SHORT
- opposite Local Low -> close/reverse LONG

A late detector that is "100% accurate" after price has already moved 2–5% is NOT a solution. The existing late zero-FP plateau is a teacher/reference and must be used to learn the earlier signature.

## Ground truth / teacher

Use the strict terminal H1 Local labels only as offline teacher/scoring.

Current strict teacher logic is H1 L6/K2 terminal/alternating semantics. Future H1 bars may be used ONLY to decide the offline label after the fact. Future information MUST NEVER enter model features, candidate state, threshold selection at prediction time, or live replay.

Intrahour same-side extensions are NOT independent semantic Locals. A more-extreme same-side print updates/resets the active H1 hypothesis.

The existing late detector produced on preserved history:
- 312 strict H1 episodes
- 101 accepted
- 101 true-first
- 0 false-first
- ~32.37% coverage
- median entry distance ~2.47%

Treat that detector as a high-confidence teacher, NOT the final entry rule.

## Data

Use every causally aligned source that can be proven compatible:
- May 2026 sealed tape
- June 2026 sealed tape
- Jul–Nov historical master
- canonical `local116-HYPE` candidate snapshots
- historical enrichment (mark/index/OI/funding where available)
- full-micro/rich sources
- L50 order book
- executed public trades / aggressor flow / CVD
- price response / impact efficiency
- open interest and price/OI relationship
- liquidations and liquidation exhaustion
- funding/basis/holder ratios where available
- raw microstructure / market context
- quality/freshness/continuity masks

Canonical contract:
- 116 total points
- 86 causal/quality INPUT
- 28 TARGET_EVAL
- 2 metadata

TARGET_EVAL and metadata must NEVER enter X.

Extra rich fields may be used only if their timestamp alignment is causal and their missingness is explicitly represented. NEVER replace missing rich values with zero.

If an artifact comes from a different teacher generation or has incompatible candidate IDs/negative construction, quarantine it until alignment is proven. Do not silently concatenate datasets.

## Intelligence stack

Use and compare the existing stack:
1. Quantum — nonlinear/tabular causal learner.
2. Fin-JEPA — sequential latent representation of market state.
3. Local-Only — causal stage heads / online learner.
4. Cortex — relationship/synergy memory over TRUE vs FALSE behavior.
5. Meta-controller — combines experts only using validation-era data.

Train LOW and HIGH separately where beneficial. Do not force symmetry if transfer tests reject it.

## What you must discover

For every real H1 Local and every false candidate, reconstruct the causal state BEFORE and immediately AFTER the extremum and determine:

1. What TRUE LOWs share with other TRUE LOWs.
2. What TRUE HIGHs share with other TRUE HIGHs.
3. What TRUE candidates have that false candidates do not.
4. What false candidates have that reveals continuation before the model enters.
5. Which feature interactions are stable across market regimes, not just one month.
6. Which signatures appear at 0s / 30s / 60s / 180s / 300s and at first retrace anchors 0.25% / 0.30% / 0.35% / 0.40%.
7. How much of the next Local-to-Local move remains at each accepted signal.
8. Which early signals protect the current position's MFE before the opposite full reversal is certain.

Specifically investigate the physical transfer-of-control chain already observed:

STRUCTURAL EXTREME
-> price stops obeying the old side
-> opposite-side price response becomes efficient
-> aggressor-flow/impact relationship changes
-> liquidation burst of the old move exhausts
-> L50 liquidity recovers/rebalances
-> OI/price-OI stops contradicting reversal
-> control transfers

Do not assume every component must be present. Learn stable combinations and regime-conditional alternatives.

## Hard-negative design

False candidates are essential training data.

Include:
- same-side continuation after a temporary bounce
- candidates that retraced 0.25–0.40% and then made a new extreme
- flow-looking reversals where price did not obey flow
- liquidation spikes without true control transfer
- order-book recovery that disappeared before confirmation
- false LOW and false HIGH separately
- difficult near-miss candidates around true terminal pivots

A first false activation is a HARD FAILURE. Later correctness does not erase it.

## Optimization objective

Do NOT optimize ordinary accuracy alone.

Use lexicographic priority:

1. minimum false-first count
2. maximum precision
3. maximum number/coverage of real terminal Locals captured
4. minimum entry delay and minimum distance from exact extremum
5. maximum captured Local-to-Local MFE
6. robustness across chronological regimes

Report both time delay and price-distance delay. A 60-second signal after a violent 2% move may be worse than a 3-minute signal only 0.35% from the extremum.

Target zone:
- desirable: <=0.40% from exact extremum
- acceptable research fallback: <=0.70–1.00%
- >1% must be explicitly justified by remaining MFE
- the old ~2.47% median is too late for Local-to-Local reversal trading

## Validation — mandatory

No random train/test split.

Use chronological walk-forward:
- fit only on earlier period
- calibrate on later disjoint candidates with purge
- freeze model/thresholds
- replay later period once
- repeat across multiple temporal folds

May/Jul/Aug/Sep/Oct have already been inspected in this project. They are useful transfer tests but are not pristine final OOS anymore.

A genuinely new forward period after the frozen model is required before promotion.

Report for every fold and side:
- strict terminal Locals
- candidate count
- accepted signals
- TP
- false-first FP
- FN
- precision
- recall/coverage
- median/p90 time delay
- median/p90 distance from exact extremum
- median/p10 remaining move to next opposite Local
- captured MFE ratio
- regime breakdown
- feature availability / missingness

## MFE preservation / reversal logic research

Do not wait for a late opposite full-size Local if the current position is giving back MFE.

Research a two-stage exit/reversal state:
- PROTECT: evidence of opposite terminal formation is enough to tighten/exit current position and protect MFE.
- REVERSE: stronger evidence is required to open full-size opposite direction.

Evaluate:
- MFE captured %
- giveback from MFE
- false protective exits
- false opposite reversals
- Local-to-Local net capture before fees/slippage

Do not hide bad exits by looking ahead.

## Anti-overfit rules

Reject a rule/model if:
- its sign flips between months without a causal regime explanation
- it needs future candles
- it relies on one rare data family absent in live operation
- it works only after threshold tuning on the evaluation month
- its false-first rate rises materially on a later period
- it gets 100% on tiny support

Prefer a smaller number of very clean early signals over many false full-size entries, but quantify the economic trade-off.

## Required outputs

Create a new results directory under:
`research/hype_all_in_one/results/`

Produce:
1. `EARLY_REAL_H1_LOCAL_REPORT.md`
2. `EARLY_REAL_H1_LOCAL_METRICS.json`
3. `TRUE_FALSE_RELATIONSHIP_ATLAS.json`
4. `EARLY_LOCAL_MODEL_BUNDLE.pt` or equivalent reproducible model bundle
5. `EARLY_LOCAL_REPLAY_SIGNALS.csv`
6. `MFE_CAPTURE_REPORT.json`
7. `DATA_PROVENANCE.json`
8. tests proving no future leakage and no candidate-id overlap across splits

Also update `research/hype_all_in_one/README.md` with the result and exact commit SHA.

## Stop condition

Do NOT claim "solved" because a training or previously inspected test period is perfect.

You may call the detector a candidate solution only when:
- false-first = 0 on every frozen historical transfer fold with meaningful support,
- the signal is substantially earlier than the late teacher,
- Local-to-Local captured MFE materially improves,
- and a fresh forward period confirms the frozen model.

If zero false-first cannot coexist with sufficiently early entry, report the Pareto frontier honestly: false-first vs entry distance vs coverage vs captured MFE, then continue searching for the best stable architecture rather than inventing a perfect result.

Research only. Do not place real orders.
