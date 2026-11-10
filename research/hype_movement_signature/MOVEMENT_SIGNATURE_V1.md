# HYPE Universal Movement Signature V1

## Goal
Trade intraday movement strength, not Local prediction.

State machine:
FLAT -> START_LONG/START_SHORT -> HOLD -> WEAKEN -> EXIT -> RESUME or REVERSE.

The engine must use only causal inputs available at the decision timestamp. Strict H1 Local / future extrema / teacher ids are evaluation-only and forbidden from predictors.

## Inputs
Reuse the canonical HYPE-QUANT-116 contract and FeatureState.
- 86 legal causal/quality inputs
- Public Trades and aggressor flow
- price response / buyer-seller efficiency
- 5s/15s/30s/60s/180s/300s/900s windows
- M1/M3/M5/H1
- L10/L50 order book state/change/replenishment/withdrawal/absorption
- OI and price/OI state
- liquidation stream and clusters
- mark/index/basis
- funding, holder ratio, volatility/range/structure
- live data-quality masks

Missing rich microstructure is missing, never zero.

## Training target
Do not label by Local.

For every causal snapshot t and horizon h:
- future_up_mfe = max(P[t:t+h]/P[t]-1)
- future_down_mfe = max(1-P[t:t+h]/P[t])
- long_adverse = future_down_mfe
- short_adverse = future_up_mfe
- long_value = future_up_mfe - adverse_penalty*long_adverse - round_trip_cost
- short_value = future_down_mfe - adverse_penalty*short_adverse - round_trip_cost

Train LONG and SHORT value heads at multiple horizons.

For an open position also train continuation value from the current state:
- current_return
- MFE
- MAE
- MFE recoil = MFE-current_return
- position age
- future continuation MFE
- future adverse excursion
- recovery after recoil

This is the MFE-protection head.

## Decision objective
At every live snapshot estimate:
- value_start_long
- value_start_short
- value_hold_current
- value_exit_flat
- value_reverse

Choose the highest expected net value only in SHADOW/PAPER research.

A reversal is not forced. EXIT and later RESUME are separate actions.

## Evaluation
Primary metrics:
1. net captured underlying move after fees/slippage
2. MFE capture ratio
3. MFE giveback at exit
4. MAE
5. false starts / churn
6. trade count/day
7. profit factor
8. max drawdown
9. time in market
10. LONG/SHORT symmetry
11. chronological transfer by period
12. performance by feature-availability cohort

Leverage is applied only after the unlevered policy is scored. Report 1x first, then 5x/10x/25x paper simulations.

## Validation split
Chronological only.
- development: May-June + Jul12-Aug07
- validation: Aug08-Sep01
- test: Sep01-Oct01
- final historical holdout: Oct04-Nov03
- forward: new Nov data, frozen parameters

Never select a rule after looking at its holdout failure.

## Existing Caterpillar reuse
Reuse FeatureState and stream ingestion. Reuse the old Caterpillar concepts of entry/exit/re-entry and MFE/MAE, but remove the requirement for an active/confirmed Local before the direct movement policy can act.

## Research-only safety
No Bybit private endpoints. No real orders. No production strategy changes.
