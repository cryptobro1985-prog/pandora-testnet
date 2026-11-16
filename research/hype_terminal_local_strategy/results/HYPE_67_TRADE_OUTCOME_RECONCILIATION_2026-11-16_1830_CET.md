# HYPE terminal H1 safe-entry — aggregate trade outcome reconciliation
Date: 2026-11-16 18:30 CET. Research only; no production, orders, or detector retraining.

## Sources checked on this branch
- results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md
- results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md
- frozen_d250_trade_eligibility_audit_20261116.py
- trade_manifest_gate_research.py
- results/HYPE_FROZEN_D250_PER_TRADE_CAUSAL_ELIGIBILITY_2026-11-16_1730_CET.md

## New arithmetic reconciliation (aggregate only, not event replay)
The asymmetric-risk report states 67 completed sequential trades, 22 fixed adverse-price cut exits, and 49.25% positive after costs. 33/67 = 49.253731%, therefore **33 positive and 34 non-positive** (assuming percentage is rounded to two decimals and no uncounted trades). Since the adverse 1% price cut exits are losses under the stated 0.15% round-trip fee assumption, **at least 12 of the 34 non-positive trades were not fixed-cut exits** (34 - 22 = 12). This is a lower bound on negative opposite-local exits, not a per-trade identification; any unreported exit reasons/flat outcomes must be resolved from the ledger. 22/67 = 32.84% fixed-cut exits; 12/67 = 17.91% minimum non-cut non-positive trades. Thus improving stop gap alone cannot fix all realized loss-side exits. Exact per-trade attribution remains UNKNOWN.

The frozen D250 report states 71 accepted first signals but only 67 entries with finalized next opposite local; **4/71 = 5.63%** of accepted signals do not belong to the completed next-local sample. No claim that the two reports contain identical 67 trades is justified until joined by stable trade ID, timestamps and side. Denominator consistency must be established before any baseline vs overlay comparison.

At 3x account notional, the historical baseline terminal multiple is 5.3116, at 5x it is 13.0886. These are *closed-equity modeled* results, not validated execution. No new monthly net equity, mark-to-market DD, liquidations, or MFE capture can be calculated from these aggregates.

## Immediate data gate (do not manufacture rows)
Require the 67-row original sequential ledger (trade_id, local extreme and confirmation UTC, signal timestamp, side, entry/exit, exit reason, stop trigger/fill, fees/funding, and source artifact SHA). First reconcile exactly 22 fixed-cut exits and 33 positive net trades. Then match each to real event tape with provenance and mark/L50 coverage. Run the frozen D250 gate separately; do not count a generic trade-manifest PASS as a D250 PASS. If historical paper simulation has no private fills, record modeled fill with explicit assumptions, not 'private-fill'. Distinguish 67 finalized trades from 71 accepted first signals and maintain chronological capital accounting.

## Decision
No strategy promotion. Original 1% cut + causal opposite-local remains the frozen baseline; rejected MFE overlays remain rejected. The aggregate reconciliation identifies an exit-loss cohort worth inspecting, but it does not demonstrate that a new exit rule will improve independent forward results.
