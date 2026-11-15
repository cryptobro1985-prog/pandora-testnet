# HYPE frozen 1% stop: non-stop loss reconciliation and executable evidence gate — 2026-11-15 12:34 CET

Research-only continuation. No retraining, no new branch, no live orders, no production modifications.

## Sources re-read directly from target branch
- results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md
- results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md
- results/HYPE_EXIT_COHORT_ACCOUNTING_2026-11-15_1126_CET.md

## New audit: exact accounting under an explicit stop-fill assumption
The 67 completed simulated trades have a published 49.25% positive-after-cost rate, which corresponds to 33/67 positive and 34/67 non-positive. There are 22 fixed-cut exits. If **each fixed-cut exit was actually filled at or beyond the adverse stop** (and costs are nonnegative), each is net-negative. Under that *specific execution assumption*, the 45 non-fixed-cut exits consist of exactly 33 positive and 12 non-positive, not merely "potentially" 12. This is an algebraic conclusion, not a claim to have seen the individual ledger. If the fixed-cut count includes cancellations, non-executions or alternative stop fills, that assumption fails and the partition is unverified.

This produces two disjoint failure channels to investigate:
- 22/67 (32.84%) nominal fixed-cut exits: need gap/slippage and liquidation-first verification.
- 12/45 (26.67%) non-stop exits that are non-positive after costs: need MFE-before-exit and causal control-transfer timing verification.

33/45 (73.33%) surviving non-stop exits are positive, **conditional on the same stop-fill assumption**. This survivor win rate is selection-conditioned and cannot be used to justify an exit overlay.

## Independent, new bounded-risk calculation
The frozen baseline's modeled worst equity loss at 5x is 5.75%. At 5x notional/equity this is 1.15% of notional, consistent with a 1% price cut plus the 0.15% round-trip cost assumption. At fixed nominal, 0.25% equity risk on a 1.15% adverse notional loss requires notional/equity <= 0.25/1.15 = 0.2173913x; 0.5% requires <= 0.4347826x. These are **no-gap** illustrative caps only. With an additional adverse 1% price gap, loss budget becomes 2.15% notional and caps become 0.1162791x / 0.2325581x respectively. These calculations do not guarantee a hard loss cap, because unbounded gaps and liquidation-first execution remain possible.

At $100 equity and a 0.5% risk budget, nominal is $43.48 with no gap, or $23.26 with a modeled additional 1% adverse gap, before funding and additional market-impact reserves. 25x isolated margin on $23.26 nominal would be about $0.93, but actual liquidation depends on mark price, margin mode, maintenance margin and fees; this cannot be inferred from the modeled loss budget.

## Exact per-trade replay contract
For each original signal, preserve original extreme time, frozen D250 availability time, order placement time, first permissible fill time, position state, direction and source quality. Join by exchange event time (not arrival time); discard pre-entry trades even if received late. Reconstruct the stop and causal exit using only events available by that instant. If an M1 bar spans both stop and exit, branch into pessimistic and optimistic outcomes, never silently choose the favorable path. Mark missing M1 intervals as unknown. Do not infer tick fills, L50 queue or mark-price liquidation from M1 OHLC.

Maintain **same chronological trade sample and identical cost assumptions** for baseline and 0.25%/0.5% risk-sized alternatives; enforce max 1% total open stop-risk and no overlapping reuse of equity. Separate LOW->LONG and HIGH->SHORT. For non-stop losing cohort, measure whether MFE exceeded all-in breakeven before opposite-local K2 and whether sustained opposite price-impact efficiency/control transfer was causally available. Do not promote previously rejected flow+MFE, K0/K1 or ATR-trail overlays without new unseen-forward evidence.

## Evidence boundary / blockers
No matched 67-trade ledger or complete tick/L50 execution tape was read in this iteration. No new fills, monthly net equity, MTM DD, liquidation count, realized MFE capture or truly unseen-forward performance can be asserted. Historical 71/71 first-signal scoring is not 71 executed trades; 67 completed versus four censored must be reconciled. May sealed OOS predates July model selection and is not chronological forward. The arithmetic above is an independently reproducible checkpoint on **existing reported aggregates**, not an event replay.

## Reproduction
```python
n, wins, stops = 67, 33, 22
assert n-wins == 34
assert n-stops == 45
assert (n-wins)-stops == 12
for risk_pct in (0.25, 0.5):
    for gap_pct in (0.0, 1.0):
        all_in_loss_pct = 1.0 + 0.15 + gap_pct
        print(risk_pct, gap_pct, round(risk_pct/all_in_loss_pct, 8))
```
