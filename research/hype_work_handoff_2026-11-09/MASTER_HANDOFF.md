# HYPE Local-Only — MASTER WORK HANDOFF — 2026-11-09

This folder is the canonical handoff for a new long-running Work/Codex research session.
Do NOT restart the project from zero. Read this file first, then DATA_ARTIFACT_INDEX.json,
AUDIT_INDEX.md and PROMPT_FOR_WORK_GPT61.md.

## 1. Goal
Find the earliest causal distinction between a FALSE H1 Local candidate and a TRUE terminal H1 Local
for HYPE, while preserving honest first-signal evaluation.

Primary target:
- detect terminal LOW/HIGH as close as possible to the real extremum;
- desired early zone: about 0.3%-0.7% from the extremum;
- maximize first-signal precision AND useful coverage;
- LOW and HIGH are separate problems;
- real orders remain OFF during research.

Trading architecture under study:
EARLY SENSOR / TACTICAL BOUNCE -> PROBABLE LOCAL -> HIGH-CONFIDENCE LOCAL -> K2 PROVISIONAL -> TERMINAL FINAL.

## 2. Non-negotiable anti-leakage contract
Canonical feature contract: research/hype_quant/feature_contract.py

116 total inputs/fields:
- 86 causal/model-eligible INPUT_IDS.
- 28 TARGET_IDS (83-110): teacher/evaluation only. NEVER predictors.
- 2 metadata IDs (81-82).

Strict teacher:
- STRICT H1 L6/K2.
- K2 confirms a pivot, NOT terminality.
- same-side stronger K2 replaces the prior provisional pivot.
- prior pending pivot becomes TERMINAL_FINAL only after an opposite K2 confirms.
- ambiguous same-hour HIGH+LOW excluded.
- missing-hour gaps invalidate labels.

First-signal objective:
research/hype_false_local_entry/first_signal_objective.py
An earlier false accepted candidate is a failure even if a later true candidate appears.

## 3. Strict label universe
Across preserved Jul-Nov blocks:
- LOW 132
- HIGH 132
- total 264 strict pivots
- early-evaluable: 131 LOW + 131 HIGH because of archive edges.

Raw K2 != collapsed terminal local. Never mix these denominators.

## 4. What is already known

### Ultra-early localization
True Local can often be seen close to the extremum, but raw false-candidate rate is high.

5m:
- true LOW median distance ~0.4144%; raw first-signal precision 20.31%.
- true HIGH median distance ~0.2895%; raw first-signal precision 18.11%.

10m:
- LOW median distance ~0.5964%; precision 25.00%.
- HIGH median distance ~0.4107%; precision 23.62%.

15m:
- LOW median distance ~0.6523%; precision 28.91%.
- HIGH median distance ~0.4981%; precision 24.41%.

Conclusion: 0.3%-0.7% localization is real. The unsolved problem is false-local suppression.

### Best transferable causal signature
The strongest relationship across all four preserved regimes is not raw buy/sell volume.
It is the causal transition:

STRUCTURAL EXTREME
-> PRICE RESPONSE
-> FLOW EFFICIENCY
-> LIQUIDATION EXHAUSTION
-> BOOK RECOVERY / TRANSFER.

TRUE LOW:
- no new lower low;
- fast retrace relative to recent range;
- persistent positive reversal return;
- buyer flow actually moves price;
- long-liquidation climax decays;
- near-book recovers toward bids.

FALSE LOW:
- buys may exist but price barely reacts;
- sell pressure remains effective;
- liquidation pressure stays alive;
- bid recovery is weak/absent;
- later lower low is likely.

TRUE HIGH:
- no new higher high;
- persistent downside retrace;
- sell pressure actually moves price;
- short-liquidation squeeze decays;
- book shifts toward ask pressure / loses squeeze support.

FALSE HIGH:
- seller burst without sustained downside price response;
- short-liquidation stream remains alive;
- later higher high is likely.

Key rich-data medians:
LOW 60s reversal return:
- Jul-Aug true 0.1344% vs false 0.0396%.
- Oct-Nov true 0.1412% vs false 0.0687%.

LOW 60s reversal efficiency:
- Jul-Aug true 0.00855 vs false 0.00324.
- Oct-Nov true 0.01275 vs false 0.00783.

Jul-Aug LOW long-liquidation 180s exhaustion ratio at +5m:
- true 0.00018 vs false 0.0415.

Jul-Aug LOW L10 imbalance change +180s -> +300s:
- true +0.494 vs false -0.0075.

HIGH 300s reversal return:
- Jul-Aug true 0.1991% vs false 0.0334%.
- Oct-Nov true 0.2212% vs false 0.1389%.

Jul-Aug HIGH short-liquidation exhaustion ratio:
- true 0.00219 vs false 0.0564.

### HARD120 baseline
Frozen structural layer:
research/hype_false_local_entry/hard_survival_gate.py

Four-regime baseline:
- LOW 93 true / 11 false = 89.42%.
- HIGH 89 / 15 = 85.58%.
- combined 182 / 26 = 87.50%.
- episode recall 41.18%.

### Ultra Survival V2 — strongest high-confidence confirmation
Frozen file:
research/hype_local_only/results/HYPE_LOCAL_ULTRA_SURVIVAL_V2.json

Rules:
LOW:
- age 215m
- retrace >= 130 bps
- retrace / prior 180m move >= 0.52

HIGH:
- age 250m
- retrace >= 65 bps
- retrace / prior 180m move >= 0.50

Development:
- LOW 79/79
- HIGH 88/88
- combined 167/167
- recall 29.25%

Untouched sealed May 2026:
research/hype_local_only/results/MAY_ULTRA_SURVIVAL_V2_SCORE_2026-11-09.json
- 118 completed episodes.
- 31 accepted first signals.
- 31 true / 0 false.
- LOW 17/17.
- HIGH 14/14.
- observed precision 100%.
- recall 26.27%.

This is the strongest untouched-period evidence currently available.
It is NOT a mathematical guarantee of future 100% precision.

### Hybrid development candidate
research/hype_local_only/results/HYPE_LOCAL_HYBRID_ZERO_FP_V1.json
Development union:
- 249 true / 0 false
- coverage 43.61%
BUT May sealed score exists only for Ultra Survival V2 path. Do not claim sealed performance for the full hybrid unless it is actually scored unchanged.

### Balanced strict early rules
research/hype_strict_h1_guard/FINAL_LOCAL_STRATEGY_PORTFOLIO_2026-11-09.json

LOW +90m:
- 25/26 = 96.15% first-signal precision
- recall 19.53%
- median distance 2.355%
- p90 3.668%

HIGH +90m:
- 19/20 = 95.0%
- recall 14.84%
- median distance 1.703%
- p90 2.943%

These are useful historical transfer candidates, not pristine future proof.

## 5. Cost of waiting for maximum confidence
Ultra Survival V2 is too late to be the only entry layer.

Across observed accepted true signals, high-confidence entry typically gives away roughly 2%-3% price movement
before entry. The research direction is therefore:
- use early sensor/tactical layer to capture the first move;
- use Ultra/HARD/high-confidence layers for confirmation, scaling and core-direction authorization.

Do NOT solve this by weakening Ultra thresholds retrospectively.

## 6. Latest live-market control case — 2026-11-09
Live status source:
GitHub issue #24, "HYPE Caterpillar Quant — LIVE".

Last confirmed teacher HIGH:
- 78.133.
- active structural leg: DOWN_TO_NEXT_LOW.

24h public HYPE M1 control replay (Binance cross-check):
- open ~77.124
- high ~78.135
- low ~72.439
- 24h change about -5.54%
- full range about 7.86%.

Important LOW at 72.439:
- subsequent maximum bounce to 74.224 = +2.464%.
- HARD120 +120m requirement: ~+1.322% / price ~73.397.
- actual +120m close ~73.305 / +1.195% -> FAIL.
- Ultra +215m requirement: ~+1.528% / price ~73.546.
- actual +215m close ~73.415 / +1.347% -> FAIL.

This is a key control example:
a large +2.46% tactical bounce can still fail terminal-LOW confirmation.
The architecture must distinguish "profitable bounce" from "terminal Local".

Recent smaller tactical rebounds in the same falling regime included roughly:
+1.64%, +0.89%, +0.81%, +0.88%, followed by renewed downside.

## 7. Current engineering state
Active branch:
research/hype-h1-local-v5-oi-microstructure-20261104

Live Local-only workflow:
.github/workflows/hype-local-only.yml

Stage scoring exists separately for 60s / 180s / 300s.
Strategy scoreboard:
research/hype_local_only/strategy_scoreboard.py

Terminal state machine:
research/hype_strict_h1_guard/terminal_local_state_machine.py

Live real orders:
OFF.

Cortex may be DEGRADED independently; Local learner continues without relying on Cortex output.

## 8. What has already failed
Do not repeat these blindly:
- raw buy/sell flow alone;
- single absolute retrace threshold across regimes;
- broad OR cascades;
- static 235-feature 5m model;
- naive 5->10->15 model consensus;
- simple early ExtraTrees/RF/logit calibrated on one regime;
- HIGH Flow V2 sealed late-August (failed);
- 100% development rules interpreted as future guarantees;
- any experiment using TARGET_IDS or teacher-derived features as predictors.

## 9. Highest-value next research
Priority 1:
trajectory / state-transition features, not static snapshots.

Explicitly model:
- delta of reversal return: 30s -> 60s -> 180s -> 300s;
- delta of flow efficiency;
- decay half-life of same-side liquidation pressure;
- L10/L50 imbalance transition and replenishment/cancellation;
- OI delta + price response state;
- ratio of opposing-side impact efficiency;
- pre-extreme impulse normalized by ATR/range/realized volatility;
- time since last same-side extension;
- candidate survival hazard.

Train LOW and HIGH independently.

Objective should be multi-objective:
1. first-signal precision;
2. recall/coverage;
3. distance from true extremum;
4. latency;
5. false-first severity;
6. regime stability.

Search early checkpoints:
30s, 60s, 90s, 180s, 300s, 5m, 10m, 15m, 30m.

Use sequential/hazard/state-machine approaches, not only static classifiers.

## 10. Required validation discipline
For every promising rule/model:
- development period(s);
- chronological validation;
- sealed untouched period;
- forward/live;
- freeze thresholds before sealed/OOS score;
- report LOW and HIGH separately;
- report sample count;
- report first-signal TP/FP;
- report precision, recall, coverage;
- report median/p90/worst distance;
- report latency;
- report false-positive continuation distance;
- report whether selection was meta-tuned.

Never call historical 100% a guarantee.
