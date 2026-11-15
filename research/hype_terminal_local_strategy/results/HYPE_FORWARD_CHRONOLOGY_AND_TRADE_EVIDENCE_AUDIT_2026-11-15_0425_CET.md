# HYPE post-local: chronology and trade-evidence audit
Date: 2026-11-15 04:25 CET. Research only; no detector training, production change, or live orders.

## Inputs inspected directly in the target branch
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md
- HYPE_AGGREGATE_COST_SENSITIVITY_2026-11-15_0334_CET.md

## New finding: chronological OOS is narrower than the reported 50/50
Frozen rule was selected on Jul12-Aug07 and validated on Aug08-Sep01. Its 50/50 untouched OOS signal score consists of Sep01-Oct01 (23/23), Oct04-Nov03 (12/12), **and sealed May (15/15)**. May precedes July development in calendar time. It can be a sealed holdout, but cannot be *prospective chronological forward* after the July/Aug rule-selection process.

The strictly later-dated forward subset reported is therefore 35/35 (23+12) with zero observed false-first, not 50/50. Exact two-sided Clopper-Pearson 95% lower precision bound for 35 successes in 35 Bernoulli trials is (0.025)^(1/35) = 0.8999675644 (~90.0%). This is only a descriptive conditional interval, and independence/multiplicity assumptions are unproven. 50/50 OOS and 71/71 total are not wrong, but they describe different evidence classes. Neither guarantees live trading precision or profitability.

## Chronology and ledger reproducibility gate
The asymmetric-risk report prints an equity path in the order May -> Jul12-Aug07 -> Aug08-Sep01 -> Sep01-Oct01 -> Oct04-Nov03. This is chronological calendar order, but **the May equity leg is an earlier-dated holdout, not a forward result after July training**. Do not label the complete $100->$1308.86 curve a strictly forward walk-forward result. The reported curve is an aggregate historical sequential simulation with an early sealed holdout.

The 67 trades with finalized opposite locals are not identical to all 71 signals (four censored). No independent event-ordered fill/stop tape or reproducible per-trade equity ledger was available from the three inspected reports. Therefore no new month-by-month net equity, MTM DD, actual stop fills, funding, liquidations, or MFE capture can be certified in this audit. The 67 trades and 22 cut exits are simulation outputs, not evidence of executable fills.

## Trading implications (frozen; not a new overlay)
- Keep D250 rev_atr>2.0840049433824706, trade_ratio5>0.2727842248141979, side-normalized flow15<0.4504731635235635.
- LOW->LONG and HIGH->SHORT only once availability time is causal, and candidate survives same-side invalidation.
- Keep original 1% adverse-price cut and opposite K2-available exit as unchanged comparison baseline; previously rejected MFE overlays stay rejected.
- For exploratory alternatives, bound notional by equity stop-risk / (adverse stop distance + two-way fees + reserved adverse slippage/funding), independently for LONG and SHORT, then check liquidation buffer and cumulative concurrent risk <=1%. This does not guarantee a maximum realized loss in a gap.
- A future protection rule based on sustained opposite price-impact efficiency/control transfer must be developed on a development window and validated on a truly later untouched window; no retrospective threshold promotion.
- Missing rich L50/OI/liquidation observations must be labeled missing, not imputed as zero.

## Required next reproducible replay
Recover the original 71 signal timestamps, 67 completed trade rows and four censored rows; join Bybit public-trade event-time/receive-time, M1 CVD, L50 snapshots, liquidation/OI records and funding at entry/exit. Audit event coverage and liquidity, preserve stop-first intrabar uncertainty, compare unchanged 5x baseline and 0.25-0.5% stop-risk alternatives with one shared ledger and no capital overlap. Publish per-calendar-month net equity, MTM and closed DD, stop gap/fill count, liquidation distances, MFE captured/given back, plus post-freeze later-date forward results. Until that exists, report metrics as unverified.

## Reproduction
Python: `from scipy.stats import beta; print(beta.ppf(0.025,35,1))` -> `0.8999675644278949`.
No future market information, no order simulation, and no new trade-return claim in this checkpoint.
