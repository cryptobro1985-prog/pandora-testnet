## AUTHORITATIVE STRATEGY OVERRIDE — 2026-11-11

From this checkpoint forward there is ONE primary HYPE strategy only.

**CRITICAL CORRECTION**
The historical ~0.33–0.40% distance from extreme is a DIAGNOSTIC RESULT,
not an entry threshold and not a required retrace. Do NOT wait for a fixed
percentage before deciding Local.

**PRIMARY ENTRY CONCEPT**
- New running extreme candidate.
- Immediately evaluate causal market evidence in real time.
- Confirm Local when the combined causal evidence shows that same-side
  extension has stopped and control is transferring.
- The decision is based on the 12 causal blocks:
  1) structural extreme;
  2) candidate survival / no new same-side extension;
  3) price-response speed/shape;
  4) 30s->60s->180s->300s trajectory;
  5) M1/M3/M5 persistence;
  6) buyer/seller price-impact efficiency;
  7) flow transition / control transfer;
  8) liquidation exhaustion;
  9) L10/L50 book recovery/transfer;
  10) OI + price relationship;
  11) exhaustion/normalization of the pre-extreme impulse;
  12) comparison against prior failed attempts in the same leg.
- L50/OI/liquidations are used only when fresh, valid and causally aligned.
- Confirmed LOW -> LONG.
- Confirmed HIGH -> SHORT.
- Enter as early as the evidence supports, regardless of whether price has
  moved 0.15%, 0.35%, 0.70% or another amount from the extreme.

**ROLE OF RETRACE %**
Distance from extreme is REPORTING/QUALITY METRIC ONLY:
- entry delay/distance;
- remaining move;
- version comparison;
- optional volatility normalization in analysis.
Never use the rule "wait for 0.33–0.40% retrace, then decide Local".

**DO NOT replace this primary strategy** with:
- Ultra Survival V2,
- HARD120/EARLY60,
- Hybrid Zero-FP 249/249,
- Strong/global 256/256 post-factum cascade,
- generic ensemble / unified v2 / 289-feature search.

Those remain auxiliary comparators, confidence/fallback layers, or historical research only.

**ONLY optimization target now**
REAL-TIME CAUSAL LOCAL CONFIRMATION
-> ENTRY AS EARLY AS EVIDENCE ALLOWS
-> suppress wrong-first without delaying true signals
-> emergency STOP sized from true/false MAE
-> HOLD through normal corrections
-> MFE protection
-> early opposite causal Local
-> CLOSE + FLIP.

Do not broaden the research objective unless the user explicitly changes this decision.


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

## Continuation checkpoint — 2026-11-11 (current turn)

Completed and committed:
- candidate-group purged meta calibration and minimum calibration support gate;
- fail-closed contiguous 6h/8h market regime;
- quarantine of cross-generation snapshot merges;
- seven-arm Quantum/JEPA/Cortex diagnostic ablation code in Unified v2;
- paper-only LONG/SHORT/HOLD/CLOSE/FLIP state machine and unit tests;
- causal future path target generator (3/5/10/15/30/60/120m; MFE/MAE/first-hit) and tests;
- reproducible preserved-master price-vs-flow benchmark script and measured report;
- persistent experiment ledger and architecture note;
- July/October crossperiod transfer diagnostic;
- recovery fallback from expired `local116-HYPE` to retained historical master artifact 13650399622;
- GitHub Actions train queue guard, fast smoke workflow.

Verified: fast paper policy tests passed in run 42970456491.
Latest Unified train attempt 42970809302 had completed dependency installation,
artifact inventory, historical master recovery and extra artifact inventory,
then entered the model-training step; no final model report was available at that
observation. Do not claim Unified OOS success without reading its emitted report.

Important rejected or unsupported claims:
- Legacy 5-expert classifier: OOS precision 9.64%, 150 FP / 16 TP, REJECT.
- Simple price+flow 60m research benchmark: Oct 12/18 first-hit positive
  versus price-only 9/19, but Sep only 2 events; SHADOW/INSUFFICIENT_SUPPORT.
- Existing historical OOS windows have been inspected and are no longer untouched.
- No verified live trader, no orders, no statistically established MFE-capture edge.

Source of truth:
- `research/hype_unified_intelligence/ARCHITECTURE.md`
- `research/hype_unified_intelligence/EXPERIMENT_LEDGER.jsonl`
- `research/hype_unified_intelligence/CAUSAL_PATH_BENCHMARK_V1_REPORT.json`
- `research/hype_unified_intelligence/CROSSPERIOD_RELATIONSHIP_DIAGNOSTIC_2026-11-11.md`
- `research/hype_unified_intelligence/entry_path_targets.py`
- `research/hype_unified_intelligence/state_machine.py`
- `research/hype_local_only/train_unified_local_intelligence_v2.py`

Next action: inspect outcome of GitHub Actions run 42970809302 and latest
published report; investigate a concrete failure before changing model hyperparameters.
If it completes, evaluate expert/LOW/HIGH metrics and ablations, then build an
actual entry/exit OOS evaluator using matched executable quotes where available.

## New checkpoint — frozen paper risk and leverage research (2026-11-11)

Verified workflows:
- Unified v2 trained successfully: `42970809302`, result OOS_GATE_REJECT;
  only 2 TP / 7 accepted and 17 misses out of 19 true locals,
  precision 28.57%, recall 10.53%, calibration support only 4 positives.
  Treat as REJECT, no live promotion.
- Risk replay: `42973182059` success, publish
  `research/hype_unified_intelligence/PAPER_RISK_STRESS_LATEST.json`;
  full trade-level artifact attached to that run.
- Equity-sizing smoke tests: `42973370716` success.

New reproducible modules:
- `research/hype_unified_intelligence/paper_risk_replay_v1.py`
- `research/hype_unified_intelligence/exposure_sizing.py`
- `research/hype_unified_intelligence/test_paper_risk_replay_v1.py`
- `research/hype_unified_intelligence/test_exposure_sizing.py`
- `.github/workflows/hype-paper-risk-replay-v1.yml`
- `research/hype_unified_intelligence/RISK_DECISION_2026-11-11.md`

Principal result: October previously-inspected historical paper trend-HOLD
(13 trades, 2 profitable) underlying +0.960%, but excluding the single biggest
winner changes it to -3.032%; 25x/20% margin paper equity +2.697% under basic
cost proxy, -2.516% under only +8bps extra friction, -12.793% under +25bps
extra friction. Rejected for live and cannot be called optimal.

Pure paper risk gate for a hypothetical <=0.5% equity loss under stop+cost+
8bps extra friction+1.0% price gap: 3x/10% margin and 5x/5% margin pass a
bounded scenario, while 25x/20% fails. This is NOT protection against
unbounded market gaps or a validated trading edge.

REAL ORDERS OFF. Do not promote local detector or risk policy without new
untouched forward and executable orderbook/mark-price reality checks.

Next most valuable work: match full-micro July source to compatible labels for
ablation of L50/OI/liquidation contributions, train separate LONG and SHORT
path-quality models on chrono training data, then run fresh independent
forward with trade-level PnL, MFE capture, and risk.

## Continuation checkpoint — FULL-MICRO source quality investigation (2026-11-11)

Question: can feeding all 116 HYPE points and derived L50/OI/liquidation dimensions
into Quantum/JEPA/Cortex produce reliable entry/HOLD/CLOSE/FLIP?

**New verified data-integrity discovery:**
- HYPE July12-Aug07 full-micro 300s candidate snapshots: 1252 total.
- `fullmicro_spread_bps < 0` for **161/1252 (12.8594%)** snapshots.
- All **161** invalid crossed books are marked `fullmicro_book_valid=1`,
  `fullmicro_book_gap_count=0`. Five snapshots also carry `strict_true=1`.
- Those are **NOT executable bid/ask states**. Do not train quote-based
  predictors or backtest executable fills on them.
- Corrected live `research/hype_local_only/feature_discovery.py`: crossed,
  locked, missing and malformed books now fail closed and omit derived
  spread/imbalance/microprice; previous implementation silently clamped
  negative spread to zero (commit `153ee26adc9500487595511b28e57c1e63a77977`).

**Reproducible quality-corrected July-only ablation:**
- `research/hype_unified_intelligence/fullmicro_quote_audit_v1.py`
- `research/hype_unified_intelligence/FULLMICRO_QUALITY_ABLATION_LATEST.json`
- `research/hype_local_only/test_feature_discovery_book_quality.py`
- `research/hype_unified_intelligence/test_fullmicro_quote_audit_v1.py`
- GitHub Actions runs `42975364892` (historical quality/ablation PASS) and
  `42975517442` (also live book fail-closed tests PASS).
- Valid clean cohort: 1091 snapshots. Within-July last chrono 20%: only
  3 true LOW out of 84 and 4 true HIGH out of 135.
- LOW/HIGH July test PR-AUC on price only: 0.8095 / 0.2320;
  price+flow: 0.1508 / 0.1636;
  price+flow+book: 0.1289 / 0.3885;
  +liquidations: 0.1996 / 0.4492;
  +OI: 0.4028 / 0.3486.
- **Verdict: DIAGNOSTIC ONLY / NO VERIFIED INCREMENTAL MICRO EDGE.**
  High variability and tiny true-local counts preclude confidence.
- This July sample and Oct/Nov historical OOS are ALREADY inspected;
  no tuning on them may claim an untouched validation.

Automation for ongoing work:
`HYPE Universal Tri-Brain Research — Continuous` ID
`6af3961141e48191985b9b3fdd72d1b7` re-enabled and changed from
finite COUNT=8 to hourly without COUNT; continuation follows these checkpoints.
REAL ORDERS remain OFF.

**Next investigation priority:** independently audit timestamp alignment,
bid/ask cross, and snapshot integrity in raw Nov8–10 L50, trades, OI and
liquidation streams (parquet in retained artifacts) BEFORE estimating
incremental FULL-MICRO signal value. Reproducibly align the causal quote
as-of event timestamp; avoid forward-filled gaps and stale source snapshots.
Then compare frozen candidate-level LOW/HIGH and separately LONG/SHORT
entry-path/MFE exit models across disjoint chronological sessions; require
fresh untouched forward for deployment verdict.

## Continuation checkpoint — event-time upper bound (2026-11-11)

Inspected the live feature generator, not merely the July snapshot report.
Found a **causal leakage bug** in `research/hype_local_only/feature_discovery.py`:
book-change and liquidation windows included events with
`event_ts >= decision_ts - window` but did **not** require
`event_ts <= decision_ts`. A buffered out-of-order or future-dated event
could therefore influence a prediction before that event happened.

Fixed both paths in commit `89de073cdfeeaf87cc8e98d5fe476e1fe492a2b4`;
added deterministic past/future boundary regression tests in
`research/hype_local_only/test_feature_discovery_book_quality.py` commit
`21420150362ba023e00b173ed0def64fd88b03d0`.

This is **code-level evidence**, not yet evidence that historical HYPE
predictions were affected. No new PnL, MFE capture, forward alpha or
live-readiness claims. The existing July crossed-book quarantine remains.
Next: verify CI; audit raw Nov8–10 source timestamps (exchange vs local
receipt vs decision) for actual future-event inclusion, stale snapshots,
missing streams, and unmatched source generations. Then freeze causal
features and evaluate on fresh untouched forward. Real orders OFF.

## Full-micro economic strategy search checkpoint — 2026-11-11

User requested actual, maximally profitable and leveraged HYPE strategy from
ALL historically available 116-point contract inputs. **Do not fabricate a
100% accurate or guaranteed profitable strategy**. Research must prioritize
economic net edge, robust MFE capture and real execution; if no robust edge,
choose FLAT and report REJECT.

**Data reality:** full-micro Jul12–Aug07 includes 116-point contract but
only 83/86 causal input IDs observed/derived; other 28 target/evaluation and
2 metadata fields cannot be predictors. 1,252 300s candidates, 161 crossed
L50 books excluded; 1,091 quality-clean. 289 numerically derived causal
features were evaluated, alongside price-only/flow/L50/OI/liquidations
ablations. Training 646, development 216, last July already-inspected
historical test 219, with 121-minute purge.

**Economic entry replay (verified run 42979620987, PASS):**
`research/hype_unified_intelligence/fullmicro_economic_candidate_search_v1.py`
`research/hype_unified_intelligence/FULLMICRO_ECONOMIC_ENTRY_LATEST.json`
- LONG and SHORT heads separately, training target +0.75% before −0.40%
  within 60m, next-minute OPEN entry, 0.12% costs estimated, 30m cooldown.
- Historical test net underlying: ridge price+flow −2.651% (7 trades);
  ridge all289 −7.354% (23); ExtraTrees price+flow −0.720% (8);
  ExtraTrees all289 −2.663% (12); HGB price+flow −0.424% (10);
  HGB all289 **+0.617%** (9).
- **HGB all289 development = −2.006% on 5 trades**. Do not select it
  because its already-inspected historical test happened to be positive.
- The baseline selecting all 300s candidates had about −8.249%
  underlying / 38 test trades (local independent diagnostic).
- Verdict: NO reproducibly profitable underlying strategy across these
  development and historical test splits.

**MFE HOLD / corrective exit replay (verified run 42979958634, PASS):**
`research/hype_unified_intelligence/fullmicro_mfe_hold_replay_v1.py`
`research/hype_unified_intelligence/FULLMICRO_MFE_HOLD_LATEST.json`
- 180m HOLD, 0.60% adverse underlying emergency stop,
  0.12% cost, next-bar execution, dev-selected entry thresholds.
- Price+flow opposing-flow-confirmed EXIT: dev −2.552%, test −1.319%;
  price+flow pure MFE recoil: dev −1.904%, test −0.187%;
  full289 flow-confirmed EXIT: dev −2.175%, test −2.746%;
  full289 bare MFE recoil: dev −1.733%, test −2.073%.
- None is positive in both development and historical test. They all FAIL
  robust positive expectancy criterion. MFE capture remains inadequate;
  price+flow trail test median ~0.308 net/MFE on 9 trades (not stable).

**Anti-overfit/verdict:** these are previously inspected July segments, NOT
new untouched OOS, with insufficient independent events. No verified
execution, bid/ask, market-impact, or liquidation engine. Do not apply
leverage to a statistically unsupported underlying edge. Paper/shadow only,
real orders OFF.

**Reproducible permanent assets:**
- `research/hype_unified_intelligence/FULLMICRO_ECONOMIC_SEARCH_2026-11-11.md`
- `research/hype_unified_intelligence/EXPERIMENT_LEDGER.jsonl`
- `.github/workflows/hype-fullmicro-economic-search-v1.yml`
- `.github/workflows/hype-fullmicro-mfe-hold-v1.yml`

Next workstream (not repeating rejected models):
1. Audit November raw L50/orderbook/mark/OI/trades/liq timestamp sync,
   crossed-book and stale quote/lag. Decide which 86 input families are truly
   reproducible live AND historically. Do not zero-fill missing.
2. Define **intraday continuous-scan** LONG/SHORT ignition/continuation models,
   not only sparse 300s Local proposals; candidate-only entries miss too much
   daily path. Use the highest-coverage, synchronized and quality-valid
   forward snapshots.
3. Train economic outcomes (MFE/MAE/time-to-MFE/first-hit on several horizons)
   separately for LONG and SHORT. Fit model/thresholds solely on development.
4. Compare MFE-protecting HOLD/CLOSE/FLIP and strict first-trade sequential
   execution with executable mark/bid/ask if synchronized.
5. Require a genuinely NEW forward session, sufficient trades on independent
   market regimes, risk-of-ruin and leverage robustness before any
   strategy acceptance. Never tune on already inspected July/Oct/Nov8-10.

## Continuation checkpoint — timestamped L50 freshness gate (2026-11-11)

**One engineering hypothesis only:** a non-crossed book may still be stale or
future-dated at the decision timestamp. In
`research/hype_local_only/feature_discovery.py`, when `book_ts_ms` exists:
- book timestamp > decision `last_ts_ms` -> fail closed;
- age > 5000ms -> fail closed;
- malformed/nonfinite timestamp -> fail closed;
- age exactly 5000ms remains valid.
The resulting invalid book omits spread/depth/microprice and change-derived
book predictors. Four synthetic boundary regression tests added to
`research/hype_local_only/test_feature_discovery_book_quality.py`.
CI workflow: `.github/workflows/hype-book-freshness-smoke.yml`.
Commits: c261d46e, 79296b95, 6bc9cf2d.

**Important limitation:** if source state has no `book_ts_ms`, timestamp
freshness is UNKNOWN, not certified. The guard cannot infer exchange quote age
from a decision clock. Next cycle should inspect Nov raw source field mappings
and enforce availability/freshness in the source adapter, then audit measured
stale/future/crossed rates. No new PnL or OOS improvement claimed.
Previous 161/1252 crossed July books remain quarantined. Real orders OFF.

## Continuation checkpoint — missing L50 timestamp gate (2026-11-11)

Single issue: previously `_book_features` accepted untimestamped books as
valid even though quote age and causal as-of alignment were unknown. Now
`book_ts_ms is None` returns `book_quality_valid=0` plus
`book_quality_timestamp_missing=1`; derived spread, depth, and microprice
are withheld. Stale, future, crossed, and valid timestamped cases retain
prior semantics. Regression test added. Commits: dde17502, 791fc621.

**CI: VERIFIED** run 42992316987 SUCCESS on commit 791fc621; earlier
42992314094 failed at test-first commit before code fix (expected red phase). November raw missing-timestamp incidence
has not been measured. The source adapter may not populate book_ts_ms and
therefore suppress all live L50 predictors; inspect source mappings and
freshness coverage before any model claims. Historical July 161/1252 crossed
books remain excluded. No new edge, MFE or PnL measured; real orders OFF.

## Frozen Ultra Survival trading-layer checkpoint — 2026-11-11

**Critical course correction:** stop replacing the strong local detector with
later generic ensembles. The current primary Local detector is the exact
frozen `HYPE_LOCAL_ULTRA_SURVIVAL_V2`.

Reproduced detector evidence:
- development originally 167/167 true-first, 0 false-first;
- sealed May 31/31 true-first, 0 false-first;
- new replay over May + Jul-Aug + Aug-Sep + Sep-Oct + Oct-Nov:
  **152 accepted / 152 true-first / 0 false-first**.
Coverage remains only ~26–28% by block; this is a high-confidence subset, NOT
all locals and not a future 100% guarantee.

### Verified geometry
Run `42996512191`, report
`research/hype_strong_global_local/ULTRA_SURVIVAL_TRADE_GEOMETRY_LATEST.json`.
- median Ultra entry distance from true Local: 1.992%;
- median MFE after entry: 1.297%;
- median MAE: 0.356%;
- true-signal MAE before first +0.5% MFE: p95 1.160%, p99 1.933%;
- 1.5% emergency stop survives 96.71% of true signals until +0.5% MFE;
- 2.0% emergency stop survives 99.34%;
- wait-for-next-opposite-Ultra alone is NOT a good exit (median matched return
  ~-0.049%, positive fraction ~48.98%).

### Strongest current historical trading layer
Code:
`research/hype_strong_global_local/ultra_survival_dynamic_mfe_exit_v1.py`
Workflow:
`.github/workflows/hype-ultra-survival-dynamic-mfe-exit.yml`
Latest verified run: `42997543119` SUCCESS.
Report:
`research/hype_strong_global_local/ULTRA_SURVIVAL_DYNAMIC_MFE_EXIT_LATEST.json`.

**MFE-capture-first variant** (parameters selected ONLY on Jul-Aug/Aug-Sep/Sep-Oct):
- entry = frozen Ultra signal, LOW LONG / HIGH SHORT;
- emergency stop = 1.50% underlying;
- HOLD normally until MFE >= +0.75%;
- after activation, close at next minute open when drawdown from current MFE
  reaches `max(0.25%, 35% * MFE)`;
- one completed bar confirmation;
- opposite frozen Ultra confirmation => immediate CLOSE + FLIP;
- modeled 12bps round-trip cost already included.

Development:
- Jul-Aug 22/26 wins, +4.272%, DD 3.214%, median MFE capture 58.79%;
- Aug-Sep 20/27 wins, +0.375%, DD 6.628%, capture 55.95%;
- Sep-Oct 28/34 wins, +6.152%, DD 3.617%, capture 57.41%.

Later historical Oct-Nov (not used to select exit):
- 34 trades, 30 winners = **88.24%**;
- **+15.017% underlying compound**;
- max DD 2.846%;
- median MFE 0.913%, median MAE 0.397%;
- median MFE capture **60.15%**;
- 3 emergency stops, 30 MFE exits, 1 opposite-Ultra flip.

May diagnostic (detector was sealed May; EXIT was not):
- 27/31 winners;
- +11.046% underlying;
- DD 3.223%;
- median capture 58.30%.

Statistical caveat: hundreds of exit combinations were evaluated on development,
so full entry+exit system is only **PROMISING_HISTORICAL**. Freeze it now;
new forward must be scored with NO retuning.

### Bounded paper risk reference for capture-first variant
Stress assumptions: 12bps base modeled costs +8bps extra friction,
+0.25% adverse gap only on emergency-stop trades, approximate maintenance
0.5%, require >=2.5x liquidation-distance cushion and <=2% equity loss for a
stressed emergency stop.

Best bounded scenario by maximum effective exposure under those gates:
- 5x leverage;
- 20% equity margin;
- 1.0x total-equity notional exposure;
- stressed Oct-Nov compound +11.090%;
- stressed max DD 3.650%;
- stressed one-stop equity loss 1.95%;
- approximate liquidation distance 19.5%;
- cushion 10x.

Equivalent 10x/10% has same 1.0x exposure/PnL but much less liquidation
cushion (~4.87x), so 5x/20% is structurally safer in this approximation.

**25x/20% is rejected**:
- 5.0x equity exposure;
- attractive historical stress compound (~+61.68%) is NOT a safety argument;
- stressed one-stop account loss ~9.75%;
- approximate liquidation cushion only ~1.79x;
- fails both selected safety gates.

No stop/leverage setting guarantees no liquidation under arbitrary price gaps,
outage, mark-price dislocation or failed stop execution.

### Earlier entry
HARD120 enters closer historically (median ~1.293% from local) than Ultra
(~1.992%), but it has false-first signals (Oct-Nov 53 true / 4 false, ~92.98%
precision, and weaker Jul transfer). EARLY60 failed its untouched September
promotion check.

Therefore full-size entry remains Ultra. HARD120/EARLY60 may only be studied
as a **small early probe**, scaling to full exposure only when Ultra confirms.
Do NOT authorize probe sizing until its two-stage economic replay is completed.

Permanent summary:
`research/hype_strong_global_local/ULTRA_SURVIVAL_TRADING_LAYER_2026-11-11.md`

REAL ORDERS OFF. Next priority: freeze the exact capture-first strategy and
score genuinely NEW forward data; separately run the HARD120-probe -> Ultra
scale-in economic replay without changing the frozen full-size detector.

## Early-core cohort integrity checkpoint — 2026-11-11

Focused one issue: original early causal replay workflow 43001455158 SUCCESS, but July internal cohort had 0 labels while July strict had 47. Earlier aggregate internal metrics were therefore partial (Aug-Nov only) despite appearing to cover Jul-Nov. Corrected early_causal_core_entry_mfe_v1.py to explicitly flag missing/insufficient labels and mark aggregate completeness PARTIAL_MISSING_LABELS; added three regression tests. No attempt to synthesize missing internal teacher labels, and no OOS tuning. Oct-Nov original early core: 111/121 correct first, 10 wrong-first, 2,507 core flips; first-swing side accuracy is NOT event-level precision or profitable execution. Correct-first median 6m; wrong-first MAE median about 2.03% across available internal cohorts. Full-size live trading remains OFF. Next: inspect source label schema and restore compatible July internal cohort only if canonical, otherwise keep it excluded; dedupe/veto must be tested on fresh chronological forward.

## Confirmed bounce CV import repair — 2026-11-11

- Run 43012122455 failed in regression tests, before CV: nonexistent `full116_data_sources` import in `confirmed_local_bounce_cv.py`.
- Existing `full116_sources.py` is already used by `full116_terminal_replay.py` and provides `read_clean_cache`.
- One-line import corrected in commit `7ffa64b51cec2226c7c8bd745aee0ea35b878e51`.
- Do not claim training or OOS improvement from this infrastructure fix; check next CI and address any new failure without changing strategy thresholds.
- Primary strategy remains early 0.33–0.40% causal Local confirmation; real orders OFF.
