# HYPE Unified Causal Entry + MFE Contract V1 — 2026-11-10

## Goal
Use all preserved HYPE evidence to decide:
- powerful LOW -> LONG
- powerful HIGH -> SHORT

Primary objective:
1. minimize false-first entries;
2. enter as early as the evidence permits;
3. hold the useful leg;
4. protect MFE only when control actually transfers;
5. allow re-entry if the original anchor remains valid and control resumes.

This is research-only. Historical zero false positives are not a future guarantee.

## Data contract
- fixed research contract: 116 points
- legal causal/quality inputs: 86
- teacher/evaluation + metadata excluded from decisions
- historically materialized rich inputs cover most, but not every nominal point independently
- missing OI/L50/liquidation evidence remains missing; never zero-fill

Evidence reviewed:
- strict/strong H1 local history May-Nov
- all-local relationship scan
- false-vs-true causal audit
- full-116 development/coverage work
- untouched May Ultra Survival transfer
- rich Jul-Aug Public Trades/OI/liquidations/L10-L50 state
- strong-global-local cascade
- Caterpillar MFE/exit/re-entry audit
- movement-signature failure analysis on Nov8-10

## Core invariant
The transferable relation is a state transition, not raw BUY/SELL imbalance:

POWERFUL STRUCTURAL EXTREME
-> SAME-SIDE EXTENSION STOPS
-> PRICE DISPLACEMENT AWAY FROM EXTREME
-> NEW-SIDE PRICE-IMPACT EFFICIENCY RISES
-> REVERSAL PERSISTS
-> CURRENT ATTEMPT OUTPERFORMS PREVIOUS FAILED ATTEMPTS IN SAME LEG
-> OLD-SIDE LIQUIDATION/IMPACT EXHAUSTS
-> NEAR BOOK TRANSFERS/RECOVERS
-> CONFIRMED

LOW and HIGH are mirrored.

The 116-point retrospective scan describes the same mechanism as
RELATIVE_TERMINAL_EXHAUSTION / ABSORPTION_DIVERGENCE:
the old side can remain active, but it loses price-impact efficiency while the
new side and defensive near-book liquidity become more effective.

## LOW -> LONG evidence
Universal/core:
- no new lower low after candidate;
- retracement/recovery rises relative to recent 60m range;
- 1m/3m/5m reversal returns remain positive;
- buyer flow must MOVE price, not merely exceed seller notional;
- buyer/new-side impact efficiency improves;
- current reversal is stronger than earlier failed LOW attempts in this leg.

Stable cross-period evidence:
- +5m retrace/range and normalized recovery separate true LOW from false LOW;
- +10m price response to buy flow remains one of the most robust relationships;
- LOW cross-period model is strongest around 5-10m, using 60m/6h recovery,
  retracement, buy-flow response, execution-price/VWAP state and new-side response.

Rich micro boosters:
- long-liquidation flush followed by strong exhaustion;
- L10/L50 recovery toward bids;
- OI/basis only as context unless direction is stable and valid.

Observed rich examples:
- 60s reversal return: true LOW > false LOW in Jul-Aug and Oct-Nov;
- 60s reversal efficiency: true LOW > false LOW;
- Jul-Aug long-liquidation exhaustion ratio by +5m:
  true ~0.00018 vs false ~0.0415;
- L10 imbalance change +180s -> +300s:
  true ~+0.494 vs false ~-0.0075.

## HIGH -> SHORT evidence
Universal/core:
- no new higher high after candidate;
- downward retracement persists for several minutes;
- seller pressure must actually move price down;
- seller/new-side price-impact efficiency improves;
- current reversal is stronger than previous failed HIGH attempts in this leg.

HIGH generally needs more persistence than LOW.

Stable cross-period evidence:
- 10-15m and later recovery/position features are stronger than a one-minute sell burst;
- robust features include 60m/6h recovery, sell-flow response, retracement,
  seller efficiency, execution-price/VWAP state and directional persistence.

Rich micro boosters:
- short-liquidation squeeze decays;
- near-book stops supporting the squeeze / shifts toward ask pressure;
- OI used only as a valid context booster.

Observed rich examples:
- 180s and 300s downward reversal return is materially stronger at true HIGH;
- Jul-Aug short-liquidation exhaustion +30s -> +300s:
  true ~0.00219 vs false ~0.0564;
- +60s L10 imbalance:
  true HIGH ~-0.137 vs false HIGH ~+0.058.

## Frozen high-confidence historical acceptance cascade

### LOW
- L90_REL:
  age 90m; candidate_ord >=20; retrace >=70 bps; rel_eff >=0.5; persistence >=0.60
- L120_EFF_REL:
  age 120m; eff >=12.5594; leg_age_h >=11.9795; rel_eff >=1.0
- L240_EFF_PERSIST:
  age 240m; eff >=18.23735278; persistence >=0.48
- L300_EFF_PERSIST:
  age 300m; eff >=24.13994198; persistence >=0.44333333

### HIGH
- H60_REL:
  age 60m; retrace >=200 bps; rel_eff >=0.9; persistence >=0.60
- H90_RETRACE:
  age 90m; retrace >=350 bps
- H120_REL:
  age 120m; candidate_ord >=5; retrace >=225 bps; rel_eff >=1.1; persistence >=0.50
- H180_EFF_PERSIST:
  age 180m; eff >=16.9135327; persistence >=0.51666667
- H240_EFF_PERSIST:
  age 240m; eff >=16.67592198; persistence >=0.51666667
- H300_EFF_PERSIST:
  age 300m; eff >=17.0954571; persistence >=0.50666667

Historical strong-local result:
- 253 matched strong episodes
- 118 first confirmations
- 118 true / 0 false-first
- observed historical precision 100%
- coverage 46.64%
- median entry distance 3.227% from extreme
- median remaining swing fraction ~42.2%

This is the safest historically observed trade-authorizing layer.

## Full historical coverage layer
A broader fitted post-factum cascade reached:
- 256/256 fully validated powerful locals
- 0 observed false-first
- 100% historical coverage
- median latency ~120.58m
- median entry distance ~2.409%
- median remaining move to next powerful local ~3.206%
- median remaining swing fraction ~60.39%

It used supplemental early branches plus a guarded structural fallback:
K2-confirmed H1 pivot + 2.5% opposite directional change.
A stale-candidate guard invalidates an old candidate if an opposite H1 pivot
becomes K2-confirmed first.

Because supplemental branches were meta-selected on the preserved sample,
this layer is SHADOW/FORWARD-VALIDATION only until frozen prospective scoring.

## Untouched evidence
Frozen HYPE_LOCAL_ULTRA_SURVIVAL_V2 scored unchanged on sealed May:
- 31 accepted first signals
- 31 true / 0 false
- observed precision 100%
- recall 26.27%
- LOW 17/17
- HIGH 14/14

This is the strongest independent evidence for a high-confidence fallback.

## Live decision hierarchy

### 1. Candidate / reset
Start a LOW/HIGH candidate only from a valid structural extreme.
If a more extreme same-side print appears before confirmation:
- invalidate current candidate;
- move candidate to the new extreme;
- reset its causal clock and relative-attempt state.

### 2. Early sensor
Continuously measure:
- price response at 30-60s, 3m, 5m, 10m, 15m;
- normalized retracement/recovery;
- new-side impact efficiency;
- directional persistence;
- execution-price/VWAP state;
- current attempt vs prior failed attempts in the active leg;
- valid rich-micro evidence when present.

The early sensor is NOT itself permission to trade unless it passes a frozen
high-confidence path.

### 3. Rich confidence reinforcement
When valid:
- liquidation exhaustion;
- L10/L50 imbalance/recovery/transfer;
- Public Trades price-impact efficiency;
- OI + price relationship;
- mark/index/basis context.

Rich evidence can increase confidence.
It must not become a mandatory veto merely because older periods lack it.

### 4. Trade authorization
- confirmed powerful LOW -> LONG
- confirmed powerful HIGH -> SHORT

Do not authorize from raw volume imbalance alone.
Do not authorize because a model merely predicts future MFE.
Do not use one absolute expected-value threshold across volatility regimes.

## HOLD / MFE / EXIT
MFE and MAE are updated on every accepted trade/tick.

Do not exit because of:
- one opposite-flow burst;
- one red/green minute;
- raw opposite notional without price response;
- a small pullback while own-side control remains effective.

Continue HOLD while:
- own-side price response remains efficient;
- directional persistence remains intact;
- no opposite transfer is sustained;
- the anchor/local is not invalidated.

Exit when one of the structural hard conditions fires:
- original anchor/local invalidated;
- confirmed opposite local.

Otherwise, flow/MFE exit requires real transfer:
- sustained opposite control;
AND at least one of:
- own-side acceleration/control weakens;
- MFE recoil reaches the current causal price scale while opposite control is present.

This matches the audited Caterpillar principle:
MFE recoil alone is not a trailing stop; it must coincide with opposite evidence
and weakening.

## RE-ENTRY
After an exit:
- original anchor must remain valid;
- an actual correction must have occurred;
- same-direction control/efficiency must return;
- no newer opposite local may invalidate the setup.

Then re-entry is allowed in the original direction.
This is Caterpillar continuation, not blind churn.

## Why the recent V2 movement model is not the entry authority
Frozen V2 on Nov8-10 saw SHORT as the stronger direction for many minutes during
the 78.133 -> 72.391 drop, but opened zero trades because its absolute expected-value
entry threshold was never reached.

Therefore:
- direction information was present;
- absolute regime calibration failed;
- future entry authority must be based on causal state/relative evidence and
  frozen high-confidence paths, not a single absolute score.

## Production-grade claim boundary
Allowed claim:
- preserved historical fitted cascade: zero observed false-firsts on its sample;
- sealed May Ultra Survival: 31/31 observed true signals;
- causal relationships transfer directionally across multiple periods.

Not allowed:
- guaranteed 100% future precision;
- guaranteed profit;
- guaranteed no liquidation.

Forward target:
- freeze the unified contract;
- every first signal is immutable after firing;
- no threshold changes after seeing a forward miss;
- false-first rate is the first metric;
- then recall/coverage;
- then entry distance/latency;
- then MFE capture and remaining swing.
