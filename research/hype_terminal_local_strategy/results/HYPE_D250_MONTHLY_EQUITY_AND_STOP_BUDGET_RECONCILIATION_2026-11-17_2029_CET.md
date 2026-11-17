# D250 monthly closed-equity reconciliation and conservative stop budget — 2026-11-17 20:29 CET

Research only. This is a **new arithmetic audit of published historical aggregates**, not an event-level replay or a new performance estimate. Frozen D250 and rejected exits unchanged.

## Inputs and provenance
Read directly from `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md` and `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md` on the specified research branch. Original baseline uses 5x account notional exposure (25x instrument leverage with 20% margin), 1% adverse-price cut, 0.15% assumed round-trip cost. Historical period sequence is **sealed May, Jul12–Aug07, Aug08–Sep01, Sep01–Oct01, Oct04–Nov03**. These are **noncontiguous research windows, not calendar months**, and the sealed May window appears first in the published sequential compound; do not call the sequence a chronological forward equity curve without UTC trade records.

## Reconciled published 5x closed-equity snapshots
| Published window end | Equity ($) | Return from preceding published snapshot |
|---|---:|---:|
| Starting balance | 100.00 | — |
| Sealed May | 471.51 | +371.510% |
| Jul12–Aug07 | 755.20 | +60.166% |
| Aug08–Sep01 | 583.32 | -22.760% |
| Sep01–Oct01 | 1037.06 | +77.786% |
| Oct04–Nov03 | 1308.86 | +26.209% |

Returns calculated as `100*(E_i/E_(i-1)-1)`, rounded to 3 decimals. The -22.760% decline between snapshots is **not** the maximum closed DD and cannot substitute for intraperiod or MTM DD. The published maximum closed DD remains 29.36% on its original ordering. No interpolated daily/monthly equity, trade timestamps, funding, or liquidation counts are asserted.

## Stop-risk accounting, unchanged 1% adverse cut
With an assumed threshold fill and 0.15% round-trip notional costs, modeled stopped-loss magnitude is `(1.00% + 0.15%)*notional` before gap, additional slippage, funding and other fees. At 3x account exposure this is **3.45% of equity**; at 5x it is **5.75%**, matching the published worst modeled trade. Neither qualifies for the proposed 0.25–0.50% equity stop-risk budget.

A conservative *pre-gap* cap using only this published cost assumption yields:
| Stop-risk allocation | Max notional / equity | Required initial margin / equity at 25x |
|---|---:|---:|
| 0.25% | 0.217391x | 0.869565% |
| 0.50% | 0.434783x | 1.739130% |
| 1.00% total | 0.869565x | 3.478261% |

Formula `N/E <= r / 0.0115`. These are **optimistic upper bounds**, not approved live sizing: with an extra 0.10% notional slippage + 0.50% gap reserve, denominator becomes 1.75%, and 0.25% / 0.50% budgets cap notional at **0.142857x / 0.285714x**, respectively. At 25x instrument leverage, corresponding margins are **0.571429% / 1.142857%** equity. Real stops can gap beyond even this reserve. Check Bybit contract quantity step/min notional and mark-price liquidation buffer before any executable sizing.

## New data-integrity finding
Published May-first compound is not a valid time-ordered walk-forward equity series for 2026 without trade-level reconstruction: May precedes July chronologically, but development used July/Aug and later tested sealed May. Thus sealed May can be an untouched *holdout in model selection* while not being a prospective later-in-time forward period. Keep **chronological walk-forward**, **sealed holdout**, and **genuinely later unseen forward** as separate evaluation labels. Do not report the published five snapshots as five calendar-month live-like returns.

## Required replay gates
1. Recover 71 accepted signal UTC records, 67 completed and 4 right-censored; verify their historical chronology and original entry rule without retraining.
2. Match each entry/stop/exit to public trades, mark price and L50 where present; distinguish touch from actual fill; missing microstructure => unknown, never fabricated.
3. Replay LONG after confirmed LOW and SHORT after confirmed HIGH separately, with timestamp-ordered fills, funding, costs, stop gaps, MTM equity and liquidation-distance evidence.
4. Recalculate chronological closed and MTM DD, monthly *calendar* net equity, stop counts, fills, liquidations and MFE retention; preserve identical trade sample and capital reservation across baseline and low-risk variants.
5. Rejected flow/MFE, K0/K1 and ATR trailing overlays remain rejected pending independent forward evidence.

## Outcome
New verified arithmetic reconciliation and risk-budget discrepancy; **no new historical fills, no matched-event replay, no verified MTM DD, no live/forward return or zero-liquidation claim**. No detector training, production changes, or real orders.
