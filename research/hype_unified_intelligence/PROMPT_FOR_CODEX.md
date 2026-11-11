# CODEX MASTER PROMPT — HYPE TRI-BRAIN AUTONOMOUS INTELLIGENCE

Repository:
`cryptobro1985-prog/pandora-testnet`

Branch:
`research/hype-h1-local-v5-oi-microstructure-20261104`

This is a continuation of an existing HYPE research project. DO NOT restart from zero.

## READ FIRST — MANDATORY

Read these files before writing code or launching experiments:

1. `research/hype_quant/feature_contract.py`
2. `research/hype_local_only/train_local_ensemble_30d.py`
3. `research/hype_local_only/train_unified_local_intelligence_v2.py`
4. `research/hype_local_only/results/HYPE_LOCAL_ENSEMBLE_LATEST.json`
5. `research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md`
6. `research/hype_work_handoff_2026-11-10/HYPE_GLOBAL_LOCAL_MASTER_PROMPT.md`
7. `research/hype_work_handoff_2026-11-09/MASTER_HANDOFF.md`
8. `research/hype_work_handoff_2026-11-09/DATA_ARTIFACT_INDEX.json`
9. `research/hype_local_only/feature_discovery.py`
10. `research/hype_local_only/live_relationship_miner.py`
11. `research/hype_local_only/cortex_daemon.py`
12. `research/hype_quant/learner.py`

Do not repeat rejected experiments unless the hypothesis has materially changed.

---

# PRIMARY OBJECTIVE

Build one unified, research-only HYPE intelligence system that combines:

1. **QUANTUM AGENT** — causal numerical learner / online learner / tabular + nonlinear relationships.
2. **JEPA AGENT** — sequential representation learner that detects temporal state transitions and latent regime changes.
3. **CORTEX AGENT** — relationship-memory / causal interaction analyst / adversarial false-positive filter / explanation layer.

The three agents must operate under one **META-CONTROLLER**.

The final intelligence must solve three linked but separately scored problems:

### A. STRUCTURAL INTELLIGENCE
Estimate whether a meaningful terminal/global LOW or HIGH is actually forming.

### B. ENTRY / PATH INTELLIGENCE
Estimate whether entering LONG/SHORT now has sufficient path quality:
- expected favorable excursion;
- adverse excursion;
- probability of follow-through;
- remaining move;
- false-break probability;
- regime compatibility.

### C. HOLD / EXIT / MFE INTELLIGENCE
Decide whether to:
- HOLD;
- CLOSE;
- FLIP;
- remain FLAT;
while ignoring small corrections inside an intact directional leg and preserving as much MFE as possible.

A Local is an important structural target/context but **must not be the only trading trigger**.
A trade requires agreement between structural confidence, path quality and execution/risk state.

REAL ORDERS = OFF.
Research / paper / shadow only.

---

# EXISTING BASELINE — DO NOT IGNORE

The previous 5-expert ensemble already exists:
- Fin-JEPA sequential;
- Quant-style MLP;
- River LocalOnly logistic;
- ExtraTrees;
- full-minute HIGH/LOW/NONE timeline teacher.

Latest frozen report:
`research/hype_local_only/results/HYPE_LOCAL_ENSEMBLE_LATEST.json`

Important OOS result:
- candidates: 253
- true locals: 19
- accepted: 166
- TP: 16
- FP: 150
- FN: 3
- precision: ~9.64%
- recall: ~84.21%
- F1: ~17.30%
- median delay: 60s

Interpretation:
The system already sees most true locals, but produces far too many false positives.
The next system must focus primarily on **false-positive suppression without destroying recall**.

Do not celebrate high recall if precision collapses.
Do not optimize accuracy on imbalanced data.

---

# NEW EXISTING WORK — CONTINUE, DO NOT REBUILD

A new unified training entry point already exists:

`research/hype_local_only/train_unified_local_intelligence_v2.py`

It introduces:
- deterministic predictive Cortex relationship-memory;
- JEPA + Quantum + Cortex meta-arbitration;
- causal market regime context;
- 5m / 15m / 30m / 60m / 180m / 360m / 480m regime windows;
- train-only Cortex relationship fitting;
- validation-only meta-controller;
- strict OOS;
- guards against mixing incompatible teacher generations.

Workflow:
`.github/workflows/hype-unified-local-intelligence-v2.yml`

Continue from this implementation.

If it has technical errors, fix them minimally.
If its research hypothesis fails, reject it and move to the next hypothesis.
Do not silently retune on OOS.

---

# DATA CONTRACT

Canonical contract:
- 116 total points
- 86 causal / quality INPUT points
- 28 TARGET_EVAL points
- 2 METADATA_ONLY points

Only the 86 INPUT / INPUT_QUALITY points and causally derived features may enter predictive X.

TARGET_EVAL and METADATA_ONLY must NEVER enter predictive X.

Core inputs include:
- Last / Mark / Index price;
- M1/M3/M5/H1 causal context;
- rolling 60m / 6h / 24h geometry;
- Public Trades;
- aggressor side;
- trade price / size / notional;
- buy/sell notional;
- trade count;
- flow imbalance;
- CVD-like balance;
- price response;
- buyer/seller efficiency;
- old-side efficiency decay;
- new-side efficiency growth;
- directional persistence;
- retracement;
- candidate survival;
- previous failed attempts;
- L50 book state;
- depth / imbalance;
- replenishment;
- disappearance;
- cancellations;
- bid/ask absorption;
- book validity;
- OI / OI changes;
- price/OI relationship;
- funding;
- volume / turnover;
- public liquidations;
- liquidation clusters / bursts;
- price/flow/OI interactions;
- freshness / gaps / restart state;
- public long-short holder ratio;
- basis;
- OI notional.

Missing historical families must remain missing.
Never fabricate or zero-impute absent microstructure.

Use availability masks where appropriate.

---

# USE ALL RETAINED DATA

Inventory all retained HYPE GitHub Actions artifacts before computation.

Important known artifacts include:
- `local116-HYPE`
- `HYPE-LOCAL-HISTORICAL-GAPS`
- historical master compact / master history
- full-micro artifacts
- recent raw / forward / live captures
- live checkpoint / relationship memory where compatible

The known historical master previously included roughly Jul 12 through Nov 3.
There are also later live/forward captures.

Do not assume every artifact uses the same teacher generation.

Before merging:
- verify schema;
- verify timestamps;
- verify label semantics;
- verify feature availability;
- verify teacher compatibility;
- verify causality.

If an artifact cannot be safely aligned, inventory it but do not fit on it.

---

# THREE-BRAIN ARCHITECTURE

## 1. QUANTUM AGENT

Purpose:
- identify nonlinear causal relationships;
- estimate probabilities / MFE / MAE / continuation;
- learn online from matured labels;
- maintain champion/challenger;
- detect drift.

Compare:
- calibrated logistic;
- River online learners;
- HistGradientBoosting / ExtraTrees;
- XGBoost / LightGBM only if available and justified;
- compact MLP;
- mixture-of-experts by regime.

LOW and HIGH must be allowed separate models.

Do not force symmetry.

## 2. JEPA AGENT

Purpose:
Model sequence/state transition, not isolated snapshots.

Use causal sequences such as:
- 30s -> 60s -> 180s -> 300s;
- M1/M3/M5;
- 15m/60m/3h/6h/8h context;
- flow-efficiency transitions;
- book state transitions;
- OI transition;
- liquidation exhaustion;
- price response.

Test whether JEPA discovers representations that improve OOS precision/recall beyond tabular models.

Do not accept JEPA because it is sophisticated.
Require measurable incremental OOS value.

Ablate JEPA:
- without JEPA;
- JEPA only;
- JEPA + Quantum;
- JEPA + Cortex;
- all three.

## 3. CORTEX AGENT

Cortex has two separate roles.

### Predictive Cortex
Must be deterministic/replayable:
- relationship-memory;
- true-vs-false effects;
- pair/triple interactions;
- repeated causal sequences;
- adversarial false-local patterns;
- regime-specific false-positive filters.

The predictive score must not depend on an unreliable free-form LLM response.

### Explanation Cortex
The local language model may:
- summarize evidence;
- identify contradictions;
- propose new hypotheses;
- explain which relationships fired;
- generate research candidates.

But explanation Cortex is NOT allowed to inject opaque untracked predictive alpha.

If the LLM fails / returns invalid JSON, the predictive system must continue.

---

# META-CONTROLLER

Build a meta-model that learns when to trust each agent.

Inputs to meta-controller may include only:
- agent probabilities/scores;
- agent agreement/disagreement;
- calibration confidence;
- regime;
- feature availability;
- data quality;
- causal market state.

The meta-controller must NOT see future labels at runtime.

Train meta-controller only on development/validation portions.
Threshold selection must occur before OOS.

Important:
A simple weighted average is only a baseline.
Compare against:
- calibrated logistic stacking;
- regime-gated mixture-of-experts;
- small tree meta-model;
- Bayesian / confidence-weighted arbitration if practical.

Require ablation proof.

---

# REGIME INTELLIGENCE

The model must explicitly know causal market context.

At minimum:
- 5m;
- 15m;
- 30m;
- 60m;
- 180m;
- 360m;
- 480m;
- 24h where available.

Infer:
- rising;
- falling;
- transition;
- range/chop;
- volatility expansion;
- volatility contraction;
- trend acceleration;
- trend exhaustion.

Do NOT use future trend classification.

The system must handle a market that has been falling/rising for 6–8 hours and then abruptly reverses.

Key question:
Which microstructure transition differentiates a true terminal reversal from another minor correction inside the existing trend?

---

# LOCAL INTELLIGENCE TARGET

Primary structural teacher:
STRICT H1 L6/K2 terminal-final LOW/HIGH where preserved and valid.

Teacher is for training/evaluation only.

The system must learn:
- true LOW;
- true HIGH;
- false LOW attempt;
- false HIGH attempt;
- same-side continuation;
- terminal vs non-terminal reversal attempt.

Evaluate FIRST accepted signal.
An earlier false signal is a failure even if the eventual true local is later found.

Key metrics:
- precision;
- recall;
- false-first rate;
- median / p90 delay;
- price distance from true extreme;
- remaining swing captured;
- LOW and HIGH separately;
- by market regime;
- by feature-availability state.

---

# FALSE-POSITIVE RESEARCH — TOP PRIORITY

Old OOS:
16 TP / 150 FP.

Analyze every false positive into repeated failure classes.

Search for repeated differences involving:
- price-flow efficiency;
- old-side impact efficiency decay;
- new-side efficiency growth;
- flow transition;
- candidate survival;
- same-side extension;
- current attempt vs prior failed attempts;
- L50 transfer;
- bid/ask absorption;
- replenishment/cancellation;
- OI + price regime;
- liquidation exhaustion;
- basis / funding;
- volatility regime;
- trend age;
- 6h/8h regime;
- trade intensity;
- microprice;
- realized volatility;
- autocorrelation/persistence;
- entropy/Hurst-style persistence proxies if causal and reproducible.

Do not add a filter based on one attractive historical example.
Require repeated cross-period evidence.

---

# ENTRY / PATH INTELLIGENCE

The goal is not merely “local detected”.

For every candidate entry, predict/evaluate:
- LONG MFE;
- LONG MAE;
- SHORT MFE;
- SHORT MAE;
- time-to-MFE;
- remaining directional movement;
- path smoothness;
- giveback risk;
- probability of +0.25 / +0.35 / +0.5 / +0.75 / +1 / +1.5 / +2% before adverse excursion.

Horizons:
3 / 5 / 10 / 15 / 30 / 60 / 120 minutes.

Runtime should produce:
- LOCAL_LOW_SCORE;
- LOCAL_HIGH_SCORE;
- LONG_SCORE;
- SHORT_SCORE;
- NO_TRADE_SCORE;
- confidence;
- predicted MFE;
- predicted MAE;
- expected net edge;
- MFE/MAE ratio;
- regime state;
- flow state;
- book state;
- OI state;
- liquidation state;
- data-quality state.

---

# HOLD / EXIT / MFE PROTECTION

This is a core objective.

Do NOT close because of:
- one red/green minute;
- one opposite flow burst;
- one small correction;
- raw opposite notional without price response.

HOLD while:
- own-side price-impact efficiency remains strong;
- path remains smooth enough;
- directional persistence survives;
- opposite-side transfer is not sustained.

Research EXIT triggers:
- deterioration of own-side price-flow efficiency;
- acceleration loss;
- opposing flow transition;
- opposing absorption;
- near-book deterioration;
- OI regime shift;
- liquidation exhaustion;
- opposite-agent score growth;
- MFE recoil conditional on real opposing evidence.

MFE recoil alone must NOT become a blind trailing stop.

For each trade save:
- entry;
- exit;
- realized return;
- MFE;
- MAE;
- MFE capture;
- MFE giveback;
- exit reason;
- agent scores at entry/exit;
- feature-family state at entry/exit;
- regime.

---

# IGNORE SMALL CORRECTIONS

Build an explicit distinction between:
- healthy correction inside intact trend;
- true exhaustion;
- terminal reversal;
- temporary flow noise;
- structural FLIP.

Possible causal features:
- correction depth normalized by volatility;
- correction depth vs prior impulse;
- recovery speed;
- efficiency retention;
- opposing-side price impact;
- same-side replenishment;
- persistence after correction;
- regime age;
- trend impulse decay.

The goal is to keep HOLD through harmless pullbacks while exiting before large MFE giveback.

---

# TRADEABLE PATH

Do not confuse daily net move with available intraday movement.

Use an EVALUATION-ONLY oracle for sequential independent legs:
- 0.25%;
- 0.35%;
- 0.5%;
- 0.75%;
- 1.0%+.

Never use the oracle in predictive X.

Report:
- total_tradeable_directional_path;
- long_tradeable_path;
- short_tradeable_path;
- captured_tradeable_movement_fraction;
- missed_move_fraction;
- false_trade_cost.

Analyze high-path days where the strategy captured little.

---

# WALK-FORWARD / ANTI-OVERFIT

Use chronological splits.

Known research chronology:
- Jul12–Aug07 train / discovery where available
- Aug08–Sep01 development
- Sep01–Oct01 validation
- Oct04–Nov03 holdout
- Nov08–Nov10 and later forward where available

Some older Local-only modules use:
- train before Oct23;
- validation Oct23–Oct27;
- OOS Oct27–Nov03.

Do not silently mix these protocols.
Document which one is used and why.

Once a period is inspected for selection, it is no longer untouched.

Never:
- retune after seeing OOS and call it OOS again;
- use TARGET_EVAL as predictor;
- use future opposite local;
- use future high/low;
- use terminal timestamp;
- select thresholds on sealed forward.

Every new model must receive a unique version tag and a new valid forward window where possible.

---

# MODEL SEARCH

Do not brute-force blindly.

Use staged search:

### Stage 1 — reproduce baselines
Reproduce old 5-expert OOS result exactly.

### Stage 2 — unified tri-brain
Run Quantum + JEPA + Cortex v2.

### Stage 3 — false-positive suppression
Learn adversarial false-local classifier / veto.

### Stage 4 — regime mixture
Separate behavior in:
- bear;
- bull;
- transition;
- chop;
- high vol;
- low vol.

### Stage 5 — entry/path model
Predict path quality and MFE/MAE.

### Stage 6 — hold/exit model
Optimize MFE capture without overreacting to minor corrections.

### Stage 7 — integrated hierarchical state machine
Output:
FLAT / LONG / SHORT / HOLD / CLOSE / FLIP.

Each stage needs ablation.

Stop branches that:
- improve train only;
- improve one period but fail transfer;
- add complexity without OOS gain;
- increase trade frequency while destroying edge.

---

# EXPERIMENT LEDGER

Maintain:
`research/hype_unified_intelligence/EXPERIMENT_LEDGER.jsonl`

Each experiment must record:
- version;
- hypothesis;
- dataset hashes;
- feature families;
- model;
- parameters;
- split;
- costs;
- train metrics;
- validation metrics;
- holdout/OOS metrics;
- forward metrics;
- LOW precision/recall;
- HIGH precision/recall;
- false-first count;
- median delay;
- MFE;
- MAE;
- MFE capture;
- drawdown;
- tradeable path capture;
- result: ACCEPT / REJECT / SHADOW;
- reason.

Never rerun an already rejected configuration without recording the material hypothesis change.

---

# REALISTIC EXECUTION / RISK

First prove underlying edge without leverage.

Then stress:
1x / 5x / 10x / 15x / 20x / 25x.

Main scenario:
25x leverage with ~20% equity used as margin = ~5x nominal equity exposure.

Include:
- fees;
- spread;
- slippage;
- latency;
- depth/capacity;
- stale-data protection.

Report:
- equity;
- max drawdown;
- losing streak;
- worst intratrade MAE;
- daily returns;
- approximate liquidation events;
- risk of ruin.

High leveraged PnL with weak underlying edge is REJECTED.

No real order placement.

---

# DISCOVER NEW PUBLIC CAUSAL FEATURES

You may add new features only if they are reproducible historically and live.

Candidates:
- VWAP / rolling VWAP;
- ATR;
- RSI;
- Stochastic;
- ADX;
- Bollinger z/bandwidth;
- ROC;
- OBV-like flow;
- volume profile;
- volume delta;
- microprice;
- trade intensity;
- realized volatility;
- autocorrelation;
- volatility clustering;
- entropy/Hurst/persistence proxies;
- Kyle-like impact;
- Amihud-like illiquidity;
- spread/depth regimes;
- cross-exchange context;
- BTC/ETH/SOL regime;
- perp/spot/basis;
- public long-short ratios.

Every feature family needs an incremental-value ablation.

Popularity of an indicator is not evidence.

---

# REQUIRED MULTI-AGENT RESEARCH ROLES

Run these as separate workstreams, even if implemented in one process:

1. Quantum Discovery
2. JEPA Sequence Discovery
3. Cortex False-Positive / Relationship Discovery
4. Regime Intelligence
5. Microstructure L50/OI/Liquidation
6. Entry / Path Quality
7. Exit / MFE Protection
8. Risk / Execution
9. Leakage / Overfit Audit
10. Integration

The Audit workstream has authority to reject attractive results.

Do not let selection and evaluation contaminate each other.

---

# SUCCESS CRITERIA

Do NOT optimize for a fantasy numeric target.

The aspirational goal is an extremely strong autonomous HYPE system, but success is defined by robust OOS/forward evidence.

For Local Intelligence:
- materially reduce false-firsts from the old 150 FP;
- retain useful recall;
- improve precision substantially;
- reduce median distance/delay where possible.

A strong milestone would be >=70% precision with useful recall on honest OOS, but do not tune directly to this number and do not claim success unless achieved honestly.

For Trading Intelligence:
- positive underlying expectancy after costs;
- strong MFE capture;
- controlled MAE;
- stable path capture;
- low drawdown;
- practically zero liquidation in stress tests;
- stable chronological transfer.

No guarantee of 100% precision, profit or no liquidation.

---

# REQUIRED DELIVERABLES

Create directory:
`research/hype_unified_intelligence/`

Mandatory outputs:

1. `ARCHITECTURE.md`
2. `DATA_INVENTORY.json`
3. `EXPERIMENT_LEDGER.jsonl`
4. `TRI_BRAIN_ABLATION.json`
5. `FALSE_POSITIVE_TAXONOMY.md`
6. `LOCAL_OOS_METRICS.json`
7. `ENTRY_PATH_METRICS.json`
8. `MFE_EXIT_METRICS.json`
9. `REGIME_BREAKDOWN.json`
10. `TRADEABLE_PATH_CAPTURE.json`
11. `RISK_STRESS.json`
12. `FINAL_UNIFIED_MODEL_REPORT.md`
13. `FINAL_UNIFIED_MODEL.pt` or equivalent reproducible bundle
14. inference/runtime module
15. tests for:
   - target leakage;
   - metadata leakage;
   - temporal split;
   - missing-data masks;
   - deterministic replay;
   - Cortex LLM failure isolation;
   - same-side candidate replacement;
   - first-signal scoring;
   - no live orders.

Save checkpoints and intermediate reports to GitHub artifacts when too large for git.

Commit useful code/reports to the current research branch.

---

# FINAL SYSTEM INTERFACE

The final runtime should expose one machine-readable state:

```json
{
  "state": "FLAT|LONG|SHORT|HOLD|CLOSE|FLIP",
  "local_low_score": 0.0,
  "local_high_score": 0.0,
  "long_score": 0.0,
  "short_score": 0.0,
  "no_trade_score": 0.0,
  "confidence": 0.0,
  "predicted_mfe": 0.0,
  "predicted_mae": 0.0,
  "mfe_mae_ratio": 0.0,
  "horizon_minutes": 0,
  "regime": "BULL|BEAR|TRANSITION|RANGE",
  "quantum_score": 0.0,
  "jepa_score": 0.0,
  "cortex_score": 0.0,
  "agent_disagreement": 0.0,
  "flow_state": {},
  "book_state": {},
  "oi_state": {},
  "liquidation_state": {},
  "data_quality": {},
  "reason_codes": []
}
```

Every decision must be explainable from stored causal evidence.

---

# EXECUTION ORDER

1. Inspect current branch and latest reports/artifacts.
2. Verify whether `HYPE-UNIFIED-LOCAL-INTELLIGENCE-v2` workflow completed.
3. Reproduce old baseline.
4. Run/fix Unified v2.
5. Build exact FP taxonomy.
6. Improve Cortex false-positive discriminator.
7. Test regime-aware gating.
8. Add full-micro incremental layer where available.
9. Add entry/path targets.
10. Add MFE/HOLD/CLOSE/FLIP model.
11. Run ablations.
12. Freeze model.
13. Evaluate untouched OOS/forward.
14. Run realistic execution/leverage stress.
15. Save final report/checkpoint.

Do not stop at a pretty train result.
Do not invent metrics.
If a hypothesis fails, mark it REJECTED and continue.
