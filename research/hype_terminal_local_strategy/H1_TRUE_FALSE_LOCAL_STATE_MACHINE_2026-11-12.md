# HYPE H1 TRUE/FALSE Local State Machine — 2026-11-12

Research only. Real orders OFF.

## Correct objective

The market structure object is H1.

Within the active H1 candle the running HIGH/LOW may update multiple times. Those
updates are not independent Locals. They are updates to one active H1 Local
hypothesis.

The live task is therefore:

1. maintain an H1 Local HIGH/LOW hypothesis from causal data only;
2. update its extreme whenever the active H1 candle extends;
3. observe the full causal market state around the active extreme;
4. decide TRUE / FALSE / WAIT without future candles;
5. activate LONG only from a TRUE LOW and SHORT only from a TRUE HIGH;
6. use strict H1 L6/K2 terminal labels only after the fact for training/scoring.

No TARGET_EVAL fields from the canonical 116-point contract are permitted in X.

## Canonical causal inputs

Use the 86 causal/quality INPUT fields from research/hype_quant/feature_contract.py.
The important physical families are:

- H1/M1/M3/M5 price structure and range position
- aggressor trade flow / CVD
- buyer/seller price-response efficiency
- candidate survival / same-side extension
- L50 book state, replenishment, cancellation, absorption and imbalance
- OI and price/OI relationship
- funding / basis / holder ratio
- liquidation burst, side, clustering and exhaustion
- continuity/freshness masks

Missing rich fields are masked; never zero-imputed as market evidence.

## H1 state machine

For each side independently:

WATCH
- active H1 hour approaches/breaks the relevant rolling structural extreme.

FORMING
- current H1 hour creates a new candidate extreme.
- a more extreme print in the same direction updates the same hypothesis and
  resets post-extreme measurements.

FALSE
- a more-extreme same-side extension invalidates a prior attempted reversal;
- or a frozen high-confidence FALSE gate fires from causal features.

TRUE
- full causal control-transfer signature is present before the configured
  maximum entry-distance budget.

WAIT
- evidence is incomplete or contradictory. Do not pretend this is TRUE.

## Causal transition hypothesis

TRUE LOW:
STRUCTURAL LOW
-> downside stops extending
-> positive price response persists
-> buyer flow becomes price-efficient
-> long-liquidation flush exhausts
-> L50 bids recover / selling is absorbed
-> OI/positioning does not contradict transfer

TRUE HIGH:
STRUCTURAL HIGH
-> upside stops extending
-> negative price response persists
-> seller flow becomes price-efficient
-> short-liquidation squeeze exhausts
-> L50 stops supporting squeeze / ask pressure appears
-> OI/positioning does not contradict transfer

LOW and HIGH MUST be modeled separately.

## Current transfer evidence

Historical strict teacher:
- H1 completed-hour pivots, lookback L6 / lookahead K2, collapsed alternating.
- teacher/future values are scoring only.

Exact-moment July rich audit:
- LOW strongest single discriminator: L50 bid depth feature AUC ~0.697.
- LOW flow-price response features ~0.65 AUC.
- HIGH structure/L50/flow features were weaker, mostly ~0.61-0.64 AUC.
Therefore exact-extreme state alone is not enough for an ideal classifier.

Fresh common-feature transfer test, July development -> untouched Oct-Nov:
- LOW +60s: OOS AUC ~0.643.
  Stable July discriminators included reversal return, reversal efficiency and
  reversal flow.
- HIGH +60s: OOS AUC ~0.575.
- LOW +180s: OOS AUC ~0.598.
- HIGH +180s: OOS AUC ~0.401 (regime/sign instability).
- LOW +300s: OOS AUC ~0.571.
- HIGH +300s: OOS AUC ~0.416.

Interpretation:
- TRUE LOW has a more transferable early post-extreme response.
- HIGH is more regime-sensitive and cannot reuse the LOW rule.
- a generic symmetric TRUE/FALSE model is rejected.
- a July-tuned high-precision threshold did not yield a robust high-precision
  accepted region on untouched Oct-Nov in this common-feature test.

## Previous early-rule evidence

The old EARLY60 fixed rule is rejected:
- untouched September HARD120 precision: 86.15%
- HARD120 + EARLY60 precision: 82.35%
- HIGH stack precision: 77.78%

Ultra Survival / Hybrid remains a late high-confidence fallback, not the desired
early <=~0.4% solution:
- development Hybrid A|B: 249 true / 0 false, coverage 43.61%
- frozen Survival V2 on sealed May: 31 true / 0 false.

## Required research protocol

Phase A — rebuild H1 hypotheses
- do not count every intrahour update as an independent Local;
- preserve the active-hour lineage and reset measurements on same-side extension.

Phase B — generate snapshots
For each H1 hypothesis capture causal state:
- immediately at each updated extreme;
- +30s / +60s / +180s / +300s;
- first 0.25 / 0.30 / 0.34 / 0.35 / 0.38 / 0.40% reversal,
  provided no newer same-side extreme superseded it first.

Phase C — true/false labeling
Only after snapshot generation:
- TRUE = hypothesis ultimately maps to the strict terminal H1 pivot.
- FALSE = attempted reversal/signal does not map to terminal H1 pivot.
- same-hour extensions remain one H1 lineage, not independent semantic Locals.

Phase D — model search
Separate LOW and HIGH.
Use:
- sparse monotonic rules;
- calibrated ensembles;
- sequential/hazard classifier;
- control-transfer score using price-response + flow efficiency + liquidations +
  L50 + OI.

Do not optimize raw classification accuracy. Optimize:
1. false-first rate;
2. true-local coverage before 0.40% move;
3. median/p90 entry distance from H1 extreme;
4. chronological transfer.

Phase E — chronological validation
Thresholds/models freeze before the next period.
Minimum protocol:
- discovery: earliest rich periods;
- validation: later period;
- untouched test: later unseen period;
- additional sealed period after freeze.

Any regime in which the rule flips sign or generates unacceptable false-first
signals rejects promotion.

## Promotion standard

A rule is allowed to become the full-size trading trigger only if:
- all features are causal at decision time;
- no teacher/future fields enter X;
- LOW/HIGH are independently calibrated;
- same-hour extensions are handled as one H1 hypothesis;
- it remains stable on untouched chronological periods;
- false-first rate is within the frozen gate;
- entry occurs within the desired move budget (target <=~0.40% when possible).

"Perfect" means perfect/near-perfect on multiple untouched historical regimes
under these rules. It is not a guarantee of future market performance.
