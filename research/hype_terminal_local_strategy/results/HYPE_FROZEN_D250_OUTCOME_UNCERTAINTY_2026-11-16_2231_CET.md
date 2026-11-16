# HYPE frozen D250 trade-outcome uncertainty and six-stop risk audit — 2026-11-16 22:31 CET

Research only. No retraining, threshold change, production edit, or orders.

## Source verification
Read original H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md and HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md directly from this branch, plus HYPE_FIXED_VS_STRUCTURAL_STOP_RISK_SENSITIVITY_2026-11-16_2129_CET.md. Source reports 67 sequential completed trades, 49.25% positive after costs, 22 fixed-cut exits, maximum six consecutive losses; 71/71 accepted correct-first historical signals (50/50 OOS). These are *different endpoints*: detector precision does not imply profitable trading.

## New exact reproducible uncertainty calculation
Positive after costs: 33/67 = 49.2537%. Wilson two-sided 95% interval with z=1.96: [37.65%, 60.94%]. Formula: p=k/n; d=1+z²/n; midpoint=(p+z²/(2n))/d; halfwidth=z*sqrt(p(1-p)/n+z²/(4n²))/d. This interval ignores dependence/regime clustering and thus may understate uncertainty.

Zero false-first in 71 accepted historical signals gives a one-sided 95% binomial upper false-signal-rate bound of 1-0.05^(1/71) = 4.13% (OOS 50: 5.82%), **not** guaranteed zero false signals. Selection/multiple-testing bias further limits interpretation.

With a truly enforced 0.5% equity loss per stop, six consecutive full-risk losses compound to 1-(1-0.005)^6 = 2.96275% closed equity DD; with 0.25% risk, 1-(1-0.0025)^6 = 1.49066%. This is a conditional scenario, not historical replay or a hard loss ceiling: fees, slippage, mark-price liquidation precedence, gaps, and overlap can violate it. The original six-loss streak is from the original 5x-account-exposure simulation, not evidence that low-risk fills or streaks remain identical.

## New trade decision implication
The 49.25% net win fraction plus large simulated profit factor 3.14 means hit rate alone cannot validate safety or positive risk-adjusted forward performance. Conversely the 71/71 detector observation is not a 100%-win strategy. A future low-risk strategy must be scored on **per-trade executable net PnL and drawdown**, not candidate truth or oracle opposite extremes.

## Replay acceptance gate
1. Obtain immutable 71-signal ledger and 67 matched entry/exit identifiers, event timestamps, direction, confirmation time, entry price, stop order acknowledgment, structural invalidation, and next opposite K2 availability. Do not manufacture missing entries.
2. Join original recovered 157375 M1 rows, mark five unflagged interior missing minutes as UNKNOWN; preserve separate L50, public trades, mark, OI, funding availability flags. Reject lookahead and stale snapshots.
3. For every trade compare original 1% cut and unchanged causal opposite-local baseline against 0.25/0.5% risk-sized and staged variants on **same trade IDs and same cost/fill model**; use trade-specific structural stop rather than median 3.14% surrogate.
4. Model stop trigger -> exchange acceptance -> fill / gap / mark liquidation precedence; never label an M1 touch as actual fill.
5. Reject overlapping capital reuse; report monthly net equity, MTM and closed DD, exposure, liquidations UNKNOWN if insufficient data, MFE captured/given back, LOW/LONG and HIGH/SHORT separately, chronological walk-forward and sealed forward.
6. Rejected MFE trails and flow overlays remain rejected pending independent evidence.

## Status
This iteration adds a numeric uncertainty/risk-streak audit from verified repository source reports, **not** a matched event replay. No new claim of actual stops, monthly net PnL, MTM DD, zero liquidations, or improved MFE is made.
