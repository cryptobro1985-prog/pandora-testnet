# HYPE H1 causal full audit — 12 strong days
2026-11-11. HYPEUSDT. Research-only; the trading engine has not been changed.

## Data
12 days: SEP03, SEP10, SEP17, SEP18, SEP30, OCT05, OCT08, OCT12, OCT22, OCT26, OCT27, OCT30.
Existing master artifact ID 13650399622 + 12 compact seven-layer overlays from run 43031802445.
Only H1 L6/K2 structure; L6 is six prior completed H1 bars, NOT an additional 6h trading timeframe.
Existing 12 strategy groups + seven available rich data layers. No new indicators, scores, tiers, or fixed retracement thresholds.
Only available-to-decision-time M1/market fields are inputs; future K2 and finality are evaluation labels only.

## Core correction
The old count of 26 "true terminal" included one censored H1 pivot:
- 43 historical raw L6/K2 pivots on the 12 days
- 25 finalized terminal (13 LOW, 12 HIGH)
- 17 later superseded same-side/nonterminal
- 1 censored and excluded from confirmed success claims

The 43 raw K2 candidates are selected using future two-hour pivot confirmation, so they **cannot** be mistaken for all first opportunities visible online.

## Actual first causal H1 structure opportunities
At the first completed M1 bar that breaks the preceding six completed H1-bar high/low, 140 distinct H1-hour/side opportunities exist:
- 25 correspond to future finalized terminals
- 114 to other opportunities
- 1 censored.

For the 25 finalized terminals the median elapsed time from first observable H1 breakout to last in-hour extreme is **11.23 minutes**; 16/25 continue building the extreme beyond 3 minutes; 14/25 beyond 5 minutes.

If the detector accepts its FIRST alert solely after 60/180/300 seconds without a newer same-side extreme:

| Wait | Correct terminal first | Premature alert before actual terminal extreme | Other false first | Censored | No alert |
|---|---:|---:|---:|---:|---:|
| 60 sec | 8 | 17 | 114 | 1 | 0 |
| 180 sec | 13 | 12 | 112 | 1 | 2 |
| 300 sec | 14 | 11 | 110 | 1 | 4 |

This is a structural-survival baseline, NOT the full executed trading strategy or its PnL. First accepted false signal counts as a failure.

## Findings within the 43 retrospectively K2-confirmed H1 pivots
At 180s after the extrema, terminal vs 17 superseded medians:
- OI change in last 1 minute: +88.46 vs -1180.46 HYPE contracts; AUC .805, n42; LOW side AUC .637, HIGH .908. Multiple-testing BH q=.0815: exploratory, not a proven universal factor.
- New-side vs old-side book replenishment 5s: +14503 vs -157750 proxy notional; n33; AUC .710.
- Old-side vs new-side book cancellation 15s: -99867 vs +516590 proxy notional; n33; inverted AUC .742.
- Old-side liquidation 180s: median 92.76 vs 490.14; n40, weak discrimination.
Counterexamples to any mandatory OI sign: genuine LOW SEP10 23:55 has OI -4538; false HIGH SEP18 15:00 has OI +7969.

## Findings at the ACTUAL first 180s alert
13 timely vs 124 false/premature first alerts, 1 censored excluded, 2 episodes did not alert:
- New-side price-impact efficiency per unit aggressor notional (x1e6): median .00625 vs .000945, AUC .723 (n137).
- Old-side flow failing to continue price: -0.02023 vs -0.00231 in the same directional per-notional convention; reverse AUC .730.
- New-side relative book replenishment 5s: +43729 vs -71276 (n104), AUC .657.
- OI last 1 minute: -257 vs -34, AUC .339 — the apparent OI sign benefit disappears/reverses in the broader online-first cohort.
- Old-side liquidation 180s: median 0 vs 0 (n131), not a universal discriminator.
The efficiency measures share the same price response and are NOT independent evidence.
None of these multiple tested features was statistically compelling as an error-free universal gate after correction (new-side efficiency BH q about .146).

## Day-held-out diagnostic, NOT a new trading model
Exploratory logistic probe with only pre-existing feature families (structure/flow/efficiency/OI/L50/liq/funding and basis):
- 42 raw K2 pivot events: TP21 FP6 FN4 TN11.
- 137 actual first 180s alerts: TP4 FP37 FN9 TN87.
Features were selected during the study, hence this is diagnostic leave-day-out, not untouched final OOS. It fails the user's requirement for near-zero false first signals.

## Why false H1 candidates happen
The old side can produce a short reversal and apparent absorption, then resumes and extends its H1 extreme. Some raw K2 pivots are later superseded by stronger same-side K2 pivots; many live H1 breakouts never become K2 pivots at all.
The recurring physical distinction is a genuine price/flow **transfer of control**, supported in some cases by L50 replenishment/cancellations, OI positioning, and liquidation exhaustion. No single sign of OI, liquidation, or orderbook reliably identifies finality in this sample.

## Data caveats
- Seven-layer overlays: 17,280 timestamps at 1-minute cadence across 12 days; trade/structure history taken from existing master.
- L50 valid on 33/42 K2, available at ~104/137 first 180s; liquidation valid ~131/137 first alerts.
- Missing historical long/short holder-ratio data; absent values are masked, not zero-filled.
- Precomputed fullmicro_basis_bps_derived is erroneous and excluded; basis recalculated from mark and index.
- OI alone cannot identify exact opening/closing long or short positions.
- The selected strong days and M1 sampling cannot establish universal tick-level behavior; no trading PnL has been simulated as part of this audit.

## Final outcome
**No perfect deterministic H1 terminal-local classifier was discovered on the causal first-signal replay.** Do not add a new fixed retracement percentage, OI sign, layer gate, score, or confidence tier from this analysis. Keep the existing strategy unchanged until a strict first-signal replay can verify any further hypothesis.
