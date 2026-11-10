# HYPE ALL-DATA ENTRY / EXIT / MFE BLUEPRINT — 2026-11-10

## Objective

Use every preserved HYPE dataset to answer only three questions:

1. When is a LOW sufficiently confirmed to open LONG with maximum confidence?
2. When is a HIGH sufficiently confirmed to open SHORT with maximum confidence?
3. Once in position, when has the current directional move weakened enough to protect MFE and/or flip into the opposite side?

Do not optimize trade count for its own sake.
Do not use Local/teacher/evaluation fields as live predictors.
Do not fabricate missing OI/liquidation/book values.

## Preserved evidence used

- sealed May 2026
- sealed June 2026
- Jul12-Aug07 full-micro block
- Aug08-Sep01 block
- Sep01-Oct01 block
- Oct04-Nov03 block
- Nov05 full-116 live captures as rich forward/rich evidence
- Nov08-Nov10 preserved 48h raw control window
- 116-point canonical contract:
  - 86 legal causal/quality input points
  - TARGET/EVAL + metadata excluded from predictor X

Historical source availability on the full-micro block:
- trades: 631 source hours
- orderbook: 631
- liquidations: 337
- open interest: 378
- mark price: 378
- ticker: 378

## Strong / powerful Local teacher

402 strict H1 L6/K2 pivots over-segmented the trading objective.

Offline 2.5% intrawave collapse:
- 268 powerful/global Locals
- 135 LOW / 133 HIGH
- median local-to-local move ~5.52%
- median duration ~9.68h

After excluding 12 block endpoints whose two-sided strength is censored:
- 256 fully validated powerful/global Locals
- 127 LOW
- 129 HIGH

## Strongest regime-stable causal relation

The repeated relation across periods is NOT raw buyers-vs-sellers imbalance.

POWERFUL STRUCTURAL EXTREME
-> NO SAME-SIDE EXTENSION
-> PRICE DISPLACEMENT AWAY FROM EXTREME
-> NEW-SIDE PRICE-IMPACT EFFICIENCY
-> DIRECTIONAL PERSISTENCE
-> CURRENT ATTEMPT STRONGER THAN PREVIOUS FAILED SAME-LEG ATTEMPTS
-> optional liquidation / L10-L50 / OI reinforcement
-> CONFIRMED DIRECTION

Decision:
- confirmed LOW -> LONG
- confirmed HIGH -> SHORT

Same-side extension invalidates/reset the current candidate.

## Cross-period evidence

### LOW

Stable multi-period relationships include:
- retracement from running LOW
- normalized recovery in the rolling 60m / ~6h structure
- price response to BUY flow
- running-low distance
- directional price persistence

At +10m, retracement medians in the four preserved Jul-Nov blocks were roughly:
- true: ~55-70 bps
- false: ~30-43 bps

Cross-period model at +10m:
- mean AUC ~0.724
- worst-period AUC ~0.685

Earlier +5m recovery/response is useful but less stable than the complete chain.

### HIGH

Stable multi-period relationships include:
- normalized recovery / position inside 60m and ~6h structure
- price response to SELL flow
- retracement from running HIGH
- seller price-impact efficiency
- directional persistence

At +60m, the strongest cross-period model:
- mean AUC ~0.707
- worst-period AUC ~0.669

HIGH generally needs more persistence than LOW.

## Rich full-116 evidence

Exact-extreme full-micro classification by itself is not precise enough to trade:
- one global relation frozen-test ROC AUC ~0.722, but top-decile precision only ~18.2%
- side-specific full-116 composites transferred poorly on the frozen exact-moment test

Therefore exact-extreme prediction is NOT the production objective.

The useful rich relation appears AFTER the extreme:

LOW true vs false:
- 60s reversal return: Jul-Aug 0.1344% vs 0.0396%; Oct-Nov 0.1412% vs 0.0687%
- 60s reversal efficiency: Jul-Aug 0.00855 vs 0.00324; Oct-Nov 0.01275 vs 0.00783
- long-liquidation exhaustion +5m: true 0.00018 vs false 0.0415 in rich Jul-Aug
- L10 imbalance change +180s -> +300s: true +0.494 vs false -0.0075

HIGH true vs false:
- 300s reversal return: Jul-Aug 0.1991% vs 0.0334%; Oct-Nov 0.2212% vs 0.1389%
- 180s reversal return: Jul-Aug 0.1506% vs 0.0295%; Oct-Nov 0.1681% vs 0.1009%
- short-liquidation exhaustion +30s -> +300s: true 0.00219 vs false 0.0564
- +60s L10 imbalance: true HIGH ~-0.137 vs false HIGH ~+0.058

Interpretation:
- liquidation exhaustion and book transfer are confidence boosters
- price response / efficiency / persistence remain the most regime-stable core

## Historical high-confidence evidence

Frozen Ultra Survival V2 on untouched sealed May:
- 118 completed episodes
- 31 accepted
- 31 true-first
- 0 false-first
- observed precision 100%
- recall 26.27%

This is the strongest genuine sealed-period evidence for a high-confidence subset.

A later full historical post-factum cascade fitted across May-Nov:
- fully validated powerful Locals: 256
- confirmed before next powerful opposite Local: 256
- observed historical false-first: 0
- historical coverage: 100%

This 256/256 result is a historical fit, NOT a future guarantee, because supplemental branches were meta-selected on preserved history.

## Entry hierarchy

Use confidence hierarchy rather than one magic threshold:

1. Structural extreme candidate exists.
2. Reject/reset immediately if same-side extension occurs.
3. Require actual displacement away from the extreme.
4. Require new-side price-impact efficiency: flow must MOVE price, not merely show notional dominance.
5. Require directional persistence across short windows.
6. Compare current attempt with earlier failed attempts in the same active leg.
7. If rich microstructure exists, increase confidence when:
   - old-side liquidations exhaust,
   - L10/L50 transfers toward the reversal side,
   - OI/basis state does not contradict the reversal.
8. Only then authorize direction:
   - LOW -> LONG
   - HIGH -> SHORT

## MFE / exit / flip logic

Do not use a fixed TP as the primary exit.

The exit is the mirrored entry relation.

While LONG:
- HOLD while buyer/new-side price-impact efficiency and persistence remain intact.
- If MFE has formed and buyer efficiency deteriorates while seller price response becomes more efficient/persistent, protect MFE.
- A confirmed powerful HIGH is the hard reason to close LONG and authorize SHORT.

While SHORT:
- HOLD while seller/new-side price-impact efficiency and persistence remain intact.
- If MFE has formed and seller efficiency deteriorates while buyer price response becomes more efficient/persistent, protect MFE.
- A confirmed powerful LOW is the hard reason to close SHORT and authorize LONG.

The key exit variable is the transition:
CURRENT-SIDE EFFICIENCY DECAY
+ PERSISTENCE BREAK
+ OPPOSITE-SIDE PRICE RESPONSE / EFFICIENCY RISE
+ OPPOSITE ATTEMPT STRONGER THAN PRIOR FAILED OPPOSITE ATTEMPTS

That transition should be measured against MFE so the engine exits when the probability of giving back the already-created move rises materially.

## Geometry of historical post-factum confirmation

Full historical fitted cascade:
- median confirmation latency ~120.6 min
- median entry distance from true extreme ~2.409%
- median remaining move to next powerful opposite Local ~3.206%
- median remaining fraction of the next powerful swing ~60.39%

Therefore the next optimization target is NOT “detect exact extreme”.
It is:

MAXIMIZE CAPTURED FRACTION BETWEEN TWO HIGH-CONFIDENCE OPPOSITE CONFIRMATIONS
subject to:
- false-first rate minimized first
- no lookahead
- no threshold retuning on forward data
- MFE giveback minimized

## Rejected directions

- raw buyers/sellers imbalance alone
- exact-extreme full-116 classifier as the primary live gate
- old movement V2 as universal movement engine: frozen Nov08-Nov10 replay produced 0 trades and missed the large decline
- standalone continuation-risk veto as the primary exit gate: LOW OOS transfer was weak

## Required scorecard from now on

Every candidate system must report:
- LONG / SHORT separately
- false-first count
- precision
- recall / coverage
- entry latency
- distance from true extreme
- remaining movement after entry
- MFE
- realized movement
- MFE capture ratio
- MFE giveback
- max adverse excursion
- result when exited/flipped by the opposite confirmed relation
- chronological / sealed-forward result with NO retuning

No production or “100% future” claim until frozen forward data preserves the zero/near-zero false-first behavior.
