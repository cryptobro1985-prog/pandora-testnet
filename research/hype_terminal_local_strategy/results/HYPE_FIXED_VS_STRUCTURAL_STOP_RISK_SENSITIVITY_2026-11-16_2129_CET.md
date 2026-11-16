# HYPE stop-risk feasibility sensitivity — 2026-11-16 21:29 CET

Research-only checkpoint. Frozen D250 unchanged. No new detector, production edits, or orders.

## New cross-source finding: 1% cut versus structural-stop geometry

The frozen entry report records a **median structural stop distance of 3.140%**, while the asymmetric-risk report selects a **1.000% adverse-price cut**. These are distinct stop hypotheses, not interchangeable implementations. The structural stop is a diagnostic level beyond the original local, whereas the fixed cut can be reached well before structural invalidation. The 67-trade result explicitly reports 22 cut exits and cannot be represented as 67 structurally held trades.

Using a conservative illustrative round-trip cost reserve of 0.15% notional (the source baseline) plus an additional adverse execution gap of 0%, 0.5%, 1% or 2%, risk-based account exposure is **risk_budget / (stop_distance + 0.15% + gap)**. This assumes costs scale with notional and does not establish actual fills or Bybit liquidation safety.

| Stop | Gap | 0.25% equity-risk exposure | 0.50% equity-risk exposure |
|---|---:|---:|---:|
| fixed 1.00% | 0.00% | 0.2174x | 0.4348x |
| fixed 1.00% | 0.50% | 0.1515x | 0.3030x |
| fixed 1.00% | 1.00% | 0.1163x | 0.2326x |
| fixed 1.00% | 2.00% | 0.0794x | 0.1587x |
| median structural 3.14% | 0.00% | 0.0760x | 0.1520x |
| median structural 3.14% | 0.50% | 0.0660x | 0.1319x |
| median structural 3.14% | 1.00% | 0.0583x | 0.1166x |
| median structural 3.14% | 2.00% | 0.0473x | 0.0945x |

Reproducible: for stop_pct in [1,3.14], gap_pct in [0,.5,1,2], budget_pct in [.25,.5], compute budget_pct/(stop_pct+.15+gap_pct), rounding to 4 decimals.

## Consequence

At the same 0.5% equity risk budget with a 1% modeled gap, the structural-stop geometry supports **0.1166x** account exposure, versus **0.2326x** for the fixed cut. The 1% cut is therefore not just a loss-rule change: it changes the attainable position size and the probability of stop activation. No expected-return comparison is valid without re-running identical entries under each exit and fill rule. Actual stop location is trade-specific; the 3.14% figure is a **median**, not a per-trade substitute.

## Data integrity blockers carried forward

The recovered Actions artifact 13650399622 contains 157,375 compact M1 rows and five unflagged interior missing minutes (Jul 28 22:24 UTC; Aug 15 08:14; Sep 26 23:14; Oct 04 01:44 and 04:19). These must be masked for any overlapping trade or pre-entry feature window. Archive coverage also has inter-period holes. The archive is not proof of mark-price continuity, full L50 tape or private fills.

The original immutable 71 accepted signal ledger and corresponding 67 trade IDs are still needed to compute matched trade-specific stops and fill paths. Until then monthly net equity, MTM drawdown, fills, liquidation count, and MFE capture remain UNKNOWN. No overlays are promoted; previously rejected profit protection remains rejected. Next concrete step: retrieve the original trade-level ledger, join to recovered compact M1, and produce a coverage-qualified chronological replay. Do not substitute oracle opposite extremes.

Sources: H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md; HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md; HYPE_RECOVERED_ACTIONS_M1_GAP_AUDIT_2026-11-16_2029_CET.md.
