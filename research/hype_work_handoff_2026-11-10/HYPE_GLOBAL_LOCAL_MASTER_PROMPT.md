# MASTER PROMPT — HYPE GLOBAL LOCAL SYSTEM AUDIT

Use GPT-6.1 Sol High for the main audit. Optionally use GPT-6 Astra Medium/High only as an independent final reviewer.

You are continuing an existing HYPE research project. DO NOT restart from zero.

## DATA LOCATION
Persistent Library vault:
/HYPE Research Vault/HYPE_DATA_VAULT_2026-11-10.zip

Repository:
cryptobro1985-prog/pandora-testnet
Branch:
research/hype-h1-local-v5-oi-microstructure-20261104

Read first:
1. research/hype_work_handoff_2026-11-09/MASTER_HANDOFF.md
2. research/hype_work_handoff_2026-11-09/DATA_ARTIFACT_INDEX.json
3. research/hype_quant/feature_contract.py
4. research/hype_local_v5/labels.py
5. research/hype_false_local_entry/first_signal_objective.py
6. research/hype_false_local_entry/FALSE_VS_TRUE_FINAL_CAUSAL_RESULT_2026-11-09.md
7. research/hype_work_handoff_2026-11-10/HYPE_GLOBAL_LOCAL_12_POINT_SYSTEM.md

## PRIMARY GOAL
Audit and improve the existing causal system for detecting GLOBAL / TERMINAL H1 Local Low and Local High.

Do NOT optimize for tactical bounces inside a larger move.
We care about the terminal global local ending the active structural leg:
LOW -> next HIGH
HIGH -> next LOW.

Detect it as early as causally possible after the true extreme, ideally about 0.3%-0.7% away, while minimizing false-first confirmations.

## EXISTING BASELINE
Test the existing 12-point causal system unchanged before inventing anything new:
1. structural extreme
2. candidate survival / no new extension
3. retracement speed / price response
4. 30s->60s->180s->300s trajectory
5. M1/M3/M5 persistence
6. buyer/seller price-impact efficiency
7. flow transition
8. liquidation exhaustion
9. L10/L50 book recovery / transfer
10. OI + price relationship
11. pre-extreme impulse normalization
12. comparison with previous false attempts in the same leg

Strongest historical chain:
STRUCTURAL EXTREME
-> PRICE RESPONSE
-> FLOW EFFICIENCY
-> LIQUIDATION EXHAUSTION
-> BOOK RECOVERY / TRANSFER.

Use all available causal inputs from the canonical 116-field contract, but NEVER use TARGET_IDS or teacher/future-derived fields as predictors.

## GROUND TRUTH
Use STRICT H1 L6/K2 terminal-final labels as the primary teacher for GLOBAL locals.

Semantics:
- K2 confirms a pivot, not terminality.
- a stronger same-side provisional replaces the prior candidate.
- terminal final is for scoring only.
- teacher labels must never leak into live features.

Historical strict terminal set across preserved May-Nov data:
402 locals = 202 LOW + 200 HIGH.
Do not confuse this with 249 accepted zero-FP Hybrid confirmations.

## EXACT AUDIT PROCEDURE
Work chronologically.

For every structural leg:
1. generate candidates causally;
2. if a stronger same-side extreme appears, replace the prior candidate immediately and reset candidate clocks;
3. evaluate each candidate only with information available by that timestamp;
4. record the FIRST moment the frozen system would confirm LOW/HIGH;
5. compare first confirmation against the eventual terminal teacher label;
6. an earlier false accepted candidate is a failure even if the eventual true local is later detected.

Evaluate checkpoints where supported:
30s, 60s, 90s, 180s, 300s, 5m, 10m, 15m, 30m, 60m.
Do not add waiting time merely to improve historical precision.

## REQUIRED METRICS
Report LOW and HIGH separately and combined:
- total true global locals;
- detected;
- missed;
- false-first confirmations;
- precision;
- recall;
- coverage;
- median/p90/worst confirmation latency;
- median/p90/worst price distance from true extreme;
- remaining swing captured after confirmation;
- false-first continuation distance;
- performance by historical period/regime;
- performance by data-quality state.

For every miss, identify which causal links failed.
For every false-first, explain what mimicked a true local and what repeated causal distinction could suppress it.

## ERROR TAXONOMY
Before adding any new filter, determine whether the error is:
A. candidate-generation bug
B. same-side replacement bug
C. missing/stale data
D. bad normalization
E. weak trajectory representation
F. weak flow-efficiency representation
G. liquidation missingness/silence mishandled
H. book-transition representation
I. OI/price-state representation
J. genuine market ambiguity

Only propose changes that solve repeated failure patterns across multiple periods.

Prefer transition features over static thresholds:
- delta reversal return 30->60->180->300
- delta flow efficiency
- liquidation decay half-life
- L10/L50 replenishment/cancellation transition
- OI delta + price response state
- opposing-side impact efficiency ratio
- normalized pre-extreme impulse
- time since same-side extension
- candidate survival hazard

LOW and HIGH may use separate models/rules.

## MODEL SEARCH — KEEP IT SMALL
Start with frozen baseline.
Then compare only:
1. compact rule/state machine
2. calibrated logistic / linear model
3. small tree ensemble if genuinely needed
4. sequential/hazard model only if clearly justified

Do NOT brute-force thousands of variants.
Do NOT repeat experiments already documented as failures.
Do NOT tune thresholds on sealed/OOS periods.

## TOKEN / COMPUTE BUDGET
Be extremely efficient.

Before new computation:
- inspect existing reports/results/checkpoints;
- reuse existing artifacts and cached features;
- do not redownload history unless required data is missing/corrupt;
- do not regenerate features that already exist;
- batch independent evaluations;
- save large tables/results to files instead of dumping them into chat;
- stop any branch that cannot beat the baseline on first-signal precision + recall + entry distance;
- stop any branch that helps one period but hurts transfer;
- stop any branch that adds complexity without repeated causal benefit.

Use high reasoning for methodology, leakage review, repeated-failure interpretation and final model selection.
Use scripts/computation for repetitive scoring.

## ANTI-LEAKAGE
Never use:
- future highs/lows
- future terminal-final timestamp
- future opposite pivot
- TARGET_IDS / teacher-derived predictors
- future state to choose the current signal
- post-hoc threshold changes after seeing sealed/OOS result

If any such leakage occurs, invalidate that experiment.

## SUCCESS CRITERIA
Produce one compact, causal, reproducible GLOBAL LOCAL detector that:
- catches as many true terminal LOW/HIGH as possible;
- has near-zero false-first confirmations;
- confirms early enough to retain most of the next swing;
- transfers across May-Nov regimes;
- can run live on the 116-field stream.

Prefer a final system simple enough to explain in one page.

## REQUIRED DELIVERABLES
Create:
1. FINAL_GLOBAL_LOCAL_AUDIT.md
2. FINAL_GLOBAL_LOCAL_METRICS.json
3. FINAL_GLOBAL_LOCAL_FALSE_FIRSTS.csv
4. FINAL_GLOBAL_LOCAL_MISSES.csv
5. FINAL_GLOBAL_LOCAL_RULESET.md
6. minimal patch + tests if code changes are justified
7. concise final verdict with:
   - current baseline quality
   - best improved system
   - LOW/HIGH precision and recall
   - median entry distance
   - false-first count
   - readiness for forward paper/live-shadow mode

Do not claim 100% future accuracy from historical performance.

## SPECIAL CONTROL CASE
Use Nov 9 LOW 72.391 only after freezing the system from earlier periods.
Do not tune on 72.391.

Report:
- whether the frozen detector recognizes it;
- first confirmation timestamp;
- confirmation price;
- distance from 72.391;
- which causal links were active;
- whether any earlier false LOW in that same down leg would have fired first.

Begin by auditing the existing 12-point system unchanged. Improve only after you have its exact baseline metrics.
