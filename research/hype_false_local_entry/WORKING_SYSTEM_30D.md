# HYPE False-Local Entry Engine — working paper system

Date: 2026-11-08
Mode: PAPER / RESEARCH ONLY. Real orders are disabled.

## System architecture

The detector does not predict the exact H1 extreme. It waits for causal evidence that the candidate extreme survived and the market accepted price in the reversal direction.

State sequence:

WATCH -> FORMING -> EARLY_PROBE -> CONFIRMED -> HARD_CONFIRMED -> ULTRA_CONFIRMED

Any new same-side extreme invalidates the active candidate immediately.

Risk staging:
- EARLY_PROBE: 10% of intended paper position; stop at the candidate extreme.
- CONFIRMED: 35% of intended paper position.
- HARD_CONFIRMED: 70% of intended paper position.
- ULTRA_CONFIRMED: 100% paper position, research-only because this gate was selected on the same 30D sample.
- EARLY/CONFIRMED in the opposite direction is not allowed to flip an established core position. Full direction change is reserved for HARD/ULTRA.

## Replayed 30D data

Artifacts:
- local116-HYPE / 13435356156
- HYPE-LOCAL-HISTORICAL-GAPS / 13533587104

Ground truth:
- 76 finalized strict H1 locals
- 75 complete alternating swings

### 10-minute probe trade-off
- all 75 true local candidates survived to the checkpoint
- 307 false candidates also survived
- median true-local entry distance from exact extreme: 0.365%
- median remaining swing after entry: 85.16%
- median full swing: 3.064%
- false-candidate probe distance to invalidation extreme: median 25.83 bps; P90 67.73 bps

### 30-minute CONFIRMED gate
- accepted first signals: 21
- true first signals: 14
- false first signals: 7
- precision: 66.67%
- correct-first recall over 75 swings: 18.67%
- median remaining swing at checkpoint: 79.76%
- quarter precision: 60.0% / 62.5% / 66.7% / 100% (last quarter 2/2)

### 60-minute HARD gate
- accepted first signals: 18
- true first signals: 14
- false first signals: 4
- precision: 77.78%
- correct-first recall over 75 swings: 18.67%
- median remaining swing at checkpoint: 72.32%
- quarter precision: 80.0% / 83.3% / 60.0% / 100% (last quarter 2/2)

### 60-minute ULTRA gate
The most conservative gate produced 9 accepted first signals and all 9 were true in this 30D sample, across all four chronological quarters.

This is NOT an untouched OOS result. The gate was selected after examining this same 30D history, so 9/9 is evidence for a useful high-confidence research state, not proof of future 100% precision.

## Operational conclusion

The system is ready for paper/live-forward signal generation, logging and continuing validation. It is not ready for leveraged real-money execution.

The core risk-control decision is that early reversal evidence cannot flip the whole position. False locals are handled as small probes with immediate invalidation, while large exposure is reserved for later structural confirmation.

Historical full L50 and liquidation coverage is incomplete; missing data are not synthesized. Forward L50/liquidation/OI should be used to test whether they improve HARD/ULTRA precision before any live promotion.
