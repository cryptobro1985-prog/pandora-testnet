# HYPE Universal Trading Engine — Overnight Checkpoint

Started as the fifth active automation for the overnight research cycle.

## Objective
Build a local-free HYPEUSDT state machine:
LONG / SHORT / HOLD / CLOSE / FLAT / FLIP.

Primary optimization target:
maximize captured tradeable intraday path after realistic costs while preserving MFE, limiting MAE, and avoiding liquidation in leverage stress tests.

## Hard anti-leakage contract
- 116 canonical points.
- Predictive X may use only causal/quality INPUT points.
- TARGET_EVAL and METADATA_ONLY are forbidden from predictors.
- Local High/Low labels may be used only as research context, never as trading triggers.
- Real orders OFF.

## Known rejected/weak approaches
1. Movement V2:
   - historical edge but frozen absolute threshold went silent on Nov8-10.
2. Adaptive Rank V6:
   - ~17-19 trades/day;
   - edge destroyed on validation/holdout.
3. Direct high-frequency V4:
   - ~35 trades/day;
   - strongly negative.
4. Universal Movement V1:
   - train looked strong;
   - validation and holdout negative;
   - reject.

## Best current local-free proof-of-concept
Frozen Nov8-Nov10 OOS trigger:
- 12 trades / ~2 days;
- ~6.0 trades/day;
- win rate ~75%;
- PF ~1.65;
- underlying return ~+1.16%;
- 25x / 20% margin approximation ~+5.61%;
- approx liquidations 0;
- LONG event lift ~2.24x;
- SHORT event lift ~1.14x.
Interpretation: LONG signature is more mature than SHORT. This is proof-of-concept, not final strategy.

## Tradeable Path correction
Daily net move is NOT the opportunity set.
Evaluate sequential independent tradeable long+short legs at multiple amplitude thresholds:
0.25 / 0.35 / 0.50 / 0.75 / 1.00%+ after realistic costs/noise constraints.

Key KPIs:
- total_tradeable_directional_path
- long_tradeable_path
- short_tradeable_path
- captured_tradeable_movement_fraction
- missed_move_fraction
- false_trade_cost

## Parallel workstreams
### A. LONG Discovery
Search causal ignition / continuation / exhaustion signatures.

### B. SHORT Discovery
Separate model and feature discovery. Do not mirror LONG by assumption.

### C. Microstructure
Test incremental value from:
- L50 imbalance/depth
- replenishment/disappearance
- cancellations/churn
- absorption
- OI transitions
- liquidations
- basis/funding
- price-flow efficiency

### D. Indicator/Data Discovery
Audit missing reproducible public data and test new causal indicators only if historical + live availability are both defensible.

### E. Exit / MFE Protection
Optimize HOLD/CLOSE/FLIP around:
- flow deterioration
- price-flow efficiency decay
- opposite pressure
- book deterioration
- OI regime shift
- liquidation exhaustion
- recoil from MFE

### F. Risk / Execution
Stress:
1x / 5x / 10x / 15x / 20x / 25x
with realistic fees, spread, slippage, latency, depth and approximate liquidation.

### G. Audit
Reject:
- future leakage
- stale/missing-source false zeros
- multiple-testing artifacts
- single-period overfit
- threshold retuning on already-inspected holdout
- leverage-only profitability

### H. Integration
Only combine components that add incremental OOS value.

## Overnight experiment protocol
For every experiment append:
- hypothesis
- feature families
- data period
- train/dev/validation/holdout/forward status
- thresholds/model
- realistic costs
- trades/day
- PF
- win rate
- MFE
- MAE
- MFE capture
- DD
- liquidation stress
- tradeable path capture
- verdict
- reason accepted/rejected

## Priority order for the next runs
1. Build explicit tradeable-path oracle/evaluator.
2. Improve SHORT signature separately from LONG.
3. Add full-micro L50/OI/liquidation confirmation around the surviving price-flow triggers.
4. Run ablations to measure incremental value of each family.
5. Improve MFE protection / flip logic.
6. Preserve untouched future windows for true forward scoring.
