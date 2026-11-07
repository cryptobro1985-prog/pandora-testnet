# HYPE H1 LOCAL ENGINE v5 — FINAL RESEARCH HANDOFF

Date: 2026-11-04
Status: RESEARCH / PAPER ONLY. No real order placement.
Primary objective: causally identify true H1 Local High / Local Low on HYPEUSDT as close to the actual structural turning point as possible while rejecting false intrawave corrections.

## 1. Source data

### 30-day HYPE minute archive
GitHub Actions run: 41736806286
Artifact: universal-minute-HYPE
Artifact ID: 13278474318

Expected contents:
- HYPE_minutes.csv.gz
- HYPE_coverage.json

Known minute columns:
- ts
- open
- high
- low
- close
- buy_notional
- sell_notional
- buy_qty
- sell_qty
- buy_count
- sell_count
- max_trade_notional
- trade_count

Window used in prior research:
- 2026-10-04 through 2026-11-02
- approximately 43,198 minute rows
- 720 H1 bars

Final universal artifact from the same workflow:
- PANDORA-UNIVERSAL-30D-FINAL
- Artifact ID: 13279637097

### v5 raw executed-trade refresh + live microstructure
GitHub Actions run: 41826828580
Conclusion: success

Historical raw-trade artifacts:
- 13319113404 — HYPE-H1-LOCAL-V5-TICKS-0
- 13318817968 — HYPE-H1-LOCAL-V5-TICKS-1
- 13319258376 — HYPE-H1-LOCAL-V5-TICKS-2
- 13319686512 — HYPE-H1-LOCAL-V5-TICKS-3
- 13318779319 — HYPE-H1-LOCAL-V5-TICKS-4
- 13319471883 — HYPE-H1-LOCAL-V5-TICKS-5

Forward/live microstructure artifact:
- 13321242644 — HYPE-H1-LOCAL-V5-LIVE-MICROSTRUCTURE

Research branch:
research/hype-h1-local-v5-oi-microstructure-20261104

Current collector / research code:
research/hype_local_v5/research.py

Workflow:
.github/workflows/hype-h1-local-v5.yml

## 2. Core finding

The dominant empirical pattern around true structural H1 reversals is not simply "buyers become sellers" or "imbalance changes sign".

For Local High:
1. mature upward swing;
2. running extreme/high;
3. buyer climax / increased aggressive buy activity;
4. deteriorating price response to additional aggressive buying;
5. seller control transfer within a few minutes;
6. price begins to accept lower levels;
7. no immediate new higher high;
8. retracement becomes meaningful relative to the entire active swing.

For Local Low the sequence is symmetric.

Observed around true HYPE reversals in prior 30-day analysis:
- true transfer often appears about 3–5 minutes after the actual extreme;
- median confirmation price error in good cases was roughly 0.3–0.45% from the actual extreme;
- simple climax + flow-flip rules were too noisy and produced many false H1 locals.

## 3. What was learned about false locals

The principal failure mode is not late detection. It is premature classification of an ordinary correction inside an unfinished H1 swing.

A false HIGH typically behaves like:
HIGH candidate -> short correction -> old direction resumes -> new higher high.

A true HIGH more often behaves like:
HIGH extreme -> opposite flow becomes effective -> price retraces meaningfully -> old high is not renewed.

The same logic is mirrored for LOW.

### Strongest discriminator discovered so far: retracement fraction

Define:

retracement_fraction =
abs(current_price - running_extreme)
/
abs(running_extreme - previous_confirmed_local)

This was more robust than a fixed percentage retracement.

Approximate prior findings:

At ~10 minutes after a candidate:
- true local: about 16–19% of the active swing retraced
- false local: about 9–10%

At ~30 minutes:
- true local: about 22%
- false local: about 10–12%

Do NOT hard-code these values as universal truths. Re-estimate on causal discovery data and validate out of sample.

### Survival without a new extreme

False locals often invalidate themselves when the old trend prints another same-side extreme.

Approximate prior finding for first false structural candidates:
- after 10 minutes, a substantial fraction remain alive;
- by 20–30 minutes many have already been invalidated by a new extreme;
- true structural locals rarely print a same-side new extreme soon after confirmation.

Therefore every candidate must be immediately invalidated when its running extreme is broken.

### Opposite-flow efficiency is more useful than opposite-flow magnitude

Large opposite imbalance alone is not sufficient.

A candidate is stronger when:
- opposite executed flow appears;
- price moves efficiently in the direction of that new flow;
- old-side aggressive flow no longer produces proportional price displacement.

Useful family of metrics:

old_side_efficiency =
old_side_price_displacement / old_side_aggressive_notional

new_side_efficiency =
new_side_price_displacement / new_side_aggressive_notional

The desired pattern is:
- old_side_efficiency deteriorates into the extreme;
- new_side_efficiency rises after transfer.

## 4. H1 structural model

Do not classify each M3/M5 flow flip independently.

Use an explicit state machine.

After confirmed LOW:
STATE = SEEK_HIGH

After confirmed HIGH:
STATE = SEEK_LOW

A same-side new extreme before opposite local confirmation is an extension of the existing swing, not a new local.

Suggested causal state sequence:

ACTIVE_SWING
-> STRUCTURAL_MATURITY
-> RUNNING_EXTREME
-> CLIMAX
-> ABSORPTION
-> EARLY_CONTROL_TRANSFER
-> EVIDENCE_ACCUMULATION
-> CONFIRMED_LOCAL

At any stage before confirmation:
NEW_SAME_SIDE_EXTREME -> INVALIDATE CANDIDATE -> UPDATE RUNNING_EXTREME -> CONTINUE ACTIVE_SWING

## 5. H1 structural context

Prior H1 structural work found roughly:
- 720 H1 bars in the 30-day window;
- about 117 raw H1 pivots with a 6-hour lookback style rule;
- after collapsing same-side extensions, roughly 80 alternating structural turns.

Do not treat this count as a target. It is a reference for scale.

The detector should require that the active swing has matured before allowing the opposite local candidate.

Candidate maturity should be normalized, not a fixed absolute percentage only.

Possible normalizers:
- H1 ATR;
- active H1 range;
- distance from previous confirmed local;
- rolling 3h / 6h directional expansion;
- percentile of current swing amplitude versus recent completed swings.

## 6. Evidence hierarchy

Current working priority:

1. no new same-side extreme / candidate survival;
2. retracement fraction of the active swing;
3. price efficiency of the new side;
4. persistent price acceptance in the new direction;
5. executed-flow transfer;
6. old-side efficiency deterioration / absorption;
7. H1 range and ATR expansion;
8. trade velocity / notional climax;
9. OI / liquidation / order-book evidence as additional causal context.

Do not reduce this to one static threshold pack.

## 7. Recommended statistical architecture

Prefer sequential evidence accumulation / change-point logic rather than one-shot classification.

A useful conceptual form:

LLR_t =
LLR_structure
+ LLR_survival
+ LLR_retracement_fraction
+ LLR_old_side_efficiency_decay
+ LLR_new_side_efficiency
+ LLR_flow_persistence
+ LLR_price_acceptance
+ LLR_OI
+ LLR_liquidations
+ LLR_orderbook_absorption

Interpretation:
- REVERSAL hypothesis: current running extreme is a true structural H1 local.
- CONTINUATION hypothesis: this is only an intrawave correction and the old swing remains active.

The score must update with each new minute / microstructure observation.

Avoid fitting dozens of arbitrary thresholds solely to maximize in-sample precision.

## 8. OOS discipline

Required chronological split:
- warmup: approximately 2026-10-04..2026-10-10
- discovery: approximately 2026-10-11..2026-10-26
- untouched OOS: approximately 2026-10-27..2026-11-02

Also use rolling / walk-forward folds inside discovery.

Never use future prices in live features.

Future extrema may be used ONLY to create offline labels and score timing/error.

Reject any model that:
- looks excellent on discovery but collapses on OOS;
- uses future-confirmed pivot information as a live input;
- selects thresholds directly on the final OOS block;
- reports only candidate-level precision while ignoring the first signal that a real state machine would actually take.

The crucial metric is sequential performance:
what is the FIRST candidate the live algorithm would accept inside each active swing?

## 9. Metrics that matter

Primary:
- true-local precision of the first accepted candidate in each swing;
- false-local rate;
- missed true-local rate;
- median and P90 confirmation delay after actual extreme;
- median and P90 entry-price distance from true extreme;
- frequency of immediate invalidation by a new same-side extreme;
- MAE before the next true opposite local.

Secondary:
- recall;
- F1;
- likelihood calibration / Brier score if probabilistic;
- distribution by volatility regime;
- performance stability across chronological folds.

Only after local detection is validated:
- PnL after fees/slippage;
- max drawdown;
- leverage survivability.

Do not optimize local detection directly for a desired dollar PnL target.

## 10. New data now available forward

The live microstructure collector captures:
- L50 order book;
- bid/ask depth;
- book imbalance;
- spread;
- bid/ask additions;
- bid/ask cancellations;
- replenishment / churn proxies;
- executed flow at 5s / 15s / 60s;
- public ticker open interest;
- liquidation stream;
- 1-second feature snapshots.

Prior successful live collector evidence from run 41826828580:
- about 1,200 second-level snapshots for a 20-minute forward sample;
- about 41k order-book messages;
- about 9.6k ticker messages;
- about 5.7k trade messages.

Use exact artifact contents as ground truth; do not rely on these rounded counts if the artifact says otherwise.

## 11. Important interpretation rules

Executed aggressive BUY does NOT prove a new long was opened.
Executed aggressive SELL does NOT prove a new short was opened.

Without position-level attribution:
- BUY can be long opening or short closing;
- SELL can be short opening or long closing.

Use OI change to improve interpretation:
- price up + OI up + aggressive buys -> more consistent with fresh risk entering;
- price up + OI down -> can be more consistent with short covering;
- price down + OI up + aggressive sells -> more consistent with fresh downside risk;
- price down + OI down -> can be more consistent with long liquidation/closing.

These are probabilistic interpretations, not identities.

## 12. What is still missing

### Historical OI
The GitHub-hosted runner received HTTP 403 from Bybit REST for historical V5 market endpoints due network / regional restrictions.

Do NOT synthesize historical OI.

Find a reproducible legitimate source or a runner/network path that can retrieve historical HYPE OI for the exact 30-day window.

If historical OI cannot be retrieved:
- state that explicitly;
- keep OI forward-only;
- do not backfill with invented data.

### Historical full order book
No trustworthy 30-day historical L2/L50 HYPE order-book archive has yet been incorporated.

Do NOT reconstruct historical book depth from candles.

If a legitimate historical book source is unavailable, use the forward collector to build an expanding OOS sample.

### Historical liquidation stream
No verified complete 30-day HYPE liquidation archive has yet been incorporated.

Do not infer individual liquidation events from minute candles.

### Exact raw within-minute ordering
The minute archive loses within-minute sequence.

The refreshed raw-trade chunks improve executed-flow reconstruction, but make sure candidate features that require sub-minute ordering are computed from true raw trades rather than minute aggregates.

## 13. New features to research

### OI state
- delta OI 30s / 1m / 3m / 5m / 15m
- OI impulse z-score
- price x OI quadrant
- executed-flow x OI interaction
- OI divergence around running extreme

### Liquidation state
- long-liquidation notional 5s / 15s / 60s
- short-liquidation notional
- liquidation velocity
- liquidation climax relative to recent baseline
- post-liquidation price efficiency
- whether reversal follows forced-position exhaustion or continuation

### Order-book absorption
Do not use raw static imbalance as the main signal.

Research:
- ask replenishment after aggressive BUY at candidate HIGH
- bid replenishment after aggressive SELL at candidate LOW
- depth consumed versus depth restored
- cancellation asymmetry
- persistence of passive wall
- price displacement per unit of aggressive notional
- price displacement per unit of removed resting liquidity
- queue/churn proxies
- spread response
- book slope / depth concentration

Desired HIGH pattern:
aggressive BUY continues -> ask liquidity replenishes / absorbs -> price stops advancing -> seller flow becomes effective -> lower prices are accepted.

Desired LOW pattern is symmetric.

## 14. Model design constraints

Do:
- build causal state machine first;
- use simple transparent features;
- use probabilistic/sequential scoring;
- validate every feature incrementally;
- compare against the existing v4/v5 baseline;
- perform ablations: price only, price+flow, +OI, +liquidations, +book;
- measure whether each added data source actually improves OOS first-signal precision and timing.

Do not:
- add indicators just because they are available;
- let ML replace structural state logic;
- optimize on the final OOS period;
- claim 100% accuracy;
- introduce future leakage;
- confuse local-price label with trade-entry price.

ML, if used, should preferably estimate incremental likelihood/confidence, not independently decide market structure.

## 15. Deliverables

Produce a complete research implementation under:
research/hype_local_v5/

Required outputs:
1. causal local detector/state machine;
2. feature builder;
3. historical replay;
4. forward/live collector integration;
5. true/false candidate ledger;
6. exact first-accepted-candidate ledger per swing;
7. discovery / walk-forward / OOS metrics;
8. ablation report;
9. error analysis of every OOS false local and missed local;
10. final recommended Local Engine configuration;
11. machine-readable JSON/CSV results;
12. markdown report with exact provenance.

Do not alter live trading logic or enable real orders.

## 16. Success criterion

The objective is not to create a visually perfect hindsight zigzag.

The objective is:

Detect the end of the active H1 structural swing causally, as near to the true extreme as possible, while minimizing the probability that the FIRST accepted reversal candidate is merely an intrawave correction.

A meaningful improvement must simultaneously improve:
- first-signal OOS precision;
- false-local rate;
- confirmation delay / price error;
- robustness across chronological folds.

If higher precision requires waiting so long that the system gives back most of the swing, report that trade-off explicitly.

No fabricated certainty. No synthetic missing market microstructure. No hidden future information.
