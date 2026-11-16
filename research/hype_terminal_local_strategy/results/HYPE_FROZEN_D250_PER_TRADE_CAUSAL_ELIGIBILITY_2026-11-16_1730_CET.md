# Frozen D250 per-trade causal eligibility — 2026-11-16 17:30 CET

Research only. No orders or production changes. Same branch. No detector training.

## New concrete audit
Read the original frozen D250 walk-forward report and asymmetric-risk report, and inspected the existing event-coverage gate. A coverage PASS does **not** verify the frozen entry features or their observation timestamps. Added `frozen_d250_trade_eligibility_audit_20261116.py` to enforce a separate per-trade eligibility gate before any execution replay.

Gate checks LOW->LONG / HIGH->SHORT, extreme <= confirmation <= signal <= entry, signal at least 250 minutes after extreme, explicit no same-side invalidation and no opposite local before signal, and individually timestamped finite rev_atr > 2.0840049433824706, trade_ratio5 > 0.2727842248141979, flow15 < 0.4504731635235635. Any feature observed after signal fails. UNKNOWN remains UNKNOWN; no zero imputation. Gate output is D250_ELIGIBLE_ONLY, never a verified fill or profit.

Seven synthetic regression cases are embedded in the module (valid, side mismatch, failed flow, future feature, premature signal, unknown invalidation, NaN). CI execution is not yet verified.

## Historical findings preserved, not new results
Frozen D250: 71/71 accepted historical first signals, 50/50 OOS, ~22.4% coverage, median causal-exit MFE giveback 61.2%. Asymmetric risk: 67 simulated sequential trades, 1% adverse cut, 3x account exposure $100->$531.16, closed DD 18.56%. Neither establishes event-level fills, mark-to-market DD or zero liquidation.

## Replay integration contract
1. Generate one row per original 67 sequential trades with local_type, side, extreme/confirmed/signal/entry timestamps, per-feature values and observed timestamps.
2. Run this gate and the existing trade_event_coverage_gate_20261116.py separately. Reject or mark UNKNOWN on either failure; do not turn unknown rich streams into zero.
3. For eligible covered trades, match trade-level Bybit public trades, mark, validated L50 and order execution assumptions, then test entry fill, stop-first vs liquidation-first, fee/funding, MAE/MFE and causal opposite-local exits.
4. Compare untouched original 3x baseline against 0.25%-0.5% equity stop-risk, total stop-risk <=1%, staged entry and profit protection on exactly the same chronological eligible sample. Rejected overlays remain rejected without unseen forward evidence.
5. Report per-month closed and MTM equity/DD, stops, gaps, liquidations (UNKNOWN if mark/maintenance unavailable), MFE captured/given back, and independent forward.

## Current blocker
No 67-trade event payload was obtained or processed in this iteration. The new module is a necessary causal audit, not the requested completed execution replay. No new historical net-return figures are claimed.
