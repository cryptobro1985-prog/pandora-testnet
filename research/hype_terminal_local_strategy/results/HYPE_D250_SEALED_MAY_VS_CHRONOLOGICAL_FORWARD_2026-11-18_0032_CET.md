# HYPE D250 chronology gate: sealed May is NOT forward in calendar time — 2026-11-18 00:32 CET

Research only. No retraining, threshold changes, production writes, or orders.

## Direct source evidence
Read the frozen `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md` and `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md` on this branch.

The entry rule was selected on **Jul12–Aug07** and validated on **Aug08–Sep01**. The original report labels Sep01–Oct01, Oct04–Nov03 and *sealed May* as untouched OOS. May is a legitimate **held-out retrospective transfer** if it was truly sealed, but it is **not chronological forward**, because May precedes July training. Do not aggregate May with September/October as proof of future deployment.

The 5x capital milestones in the risk report are ordered: May $471.51, Jul12–Aug07 $755.20, Aug08–Sep01 $583.32, Sep01–Oct01 $1,037.06, Oct04–Nov03 $1,308.86 (start $100). This is chronological by **market date** but uses a retrospective May block that precedes development. It is NOT an executable sequential forward test of a July-frozen rule starting in May. The final $1,308.86 is a modeled retrospective compound over selected disjoint windows, not an uninterrupted deployment return.

## Reproducible audit
Frozen period facts from original reports:

| Block | Calendar position | Research role | D250 first true / false | Forward status |
|---|---|---|---:|---|
| May | before development | sealed retrospective OOS | 15 / 0 | **NOT chronological forward** |
| Jul12–Aug07 | development | train | 9 / 0 | train |
| Aug08–Sep01 | after development | validation | 12 / 0 | validation |
| Sep01–Oct01 | after freeze | untouched OOS | 23 / 0 | forward-chronology eligible, if freeze provenance established |
| Oct04–Nov03 | after freeze | untouched OOS | 12 / 0 | forward-chronology eligible, if freeze provenance established |

The reported 50/50 OOS first-signal results = 15 May + 23 Sep + 12 Oct/Nov. Of these, **35/35** are in calendar periods *after* the July/Aug development window, while **15/15** are sealed back-in-time transfer. These are first-signal classification counts, NOT profitable or filled trades. The 35/35 are not automatically independently forward if rule selection or later reporting inspected those periods; audit actual freeze timestamps/commits.

## Quantified effect on evidence interpretation
- Published 71/71 zero false first = 9 train + 12 validation + 23 Sep + 12 Oct/Nov + 15 May.
- Published 50/50 OOS = 35 post-development calendar + 15 prior-calendar May.
- No valid inference that 50 prospective trading entries were independently observed.
- 67 completed simulated episodes are not a per-trade execution ledger and cannot be partitioned by calendar without the original UTC IDs.

## Immediate executable acceptance contract
1. Preserve unchanged D250 thresholds and 1% adverse cut.
2. Obtain the original 71 first-signal IDs/UTC, including the 67 completed and four censored; provenance must distinguish original frozen event timestamp from report timestamp.
3. Require `signal_utc > freeze_utc` for genuine forward; May must be `SEALED_BACKTEST_TRANSFER` regardless of its 15/15 result.
4. Reconstruct same chronological cohort for unchanged baseline and risk 0.25%/0.5% alternatives, with mark-to-market DD, gap/slippage, fees/funding, liquidation and MFE only when actual event coverage permits.
5. Reject any label `TRUE_FORWARD` if `freeze_utc` is absent, or if the signal predates freeze.
6. Rich inputs unavailable on a timestamp are unknown, never imputed zero. No reuse of overlapping capital. Keep rejected profit overlays rejected.

## Status
Concrete new source-level audit: calendar-forward vs sealed-retrospective OOS separated (35 vs 15 signals). **No new trade replay or net PnL**; original UTC ledger and matched event-level source bytes remain absent. Do not promote to live.
