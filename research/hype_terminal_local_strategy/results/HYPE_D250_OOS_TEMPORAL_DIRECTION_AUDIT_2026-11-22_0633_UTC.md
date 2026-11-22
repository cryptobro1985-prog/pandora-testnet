# D250 temporal direction / true forward evidence audit — 2026-11-22 06:33 UTC

Research only. No detector retraining, no threshold changes, no real orders. This is a reproducible audit of original source tables, NOT per-trade execution replay.

## Provenance
Read directly from this branch:
- results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md
- results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md
- research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md

## New finding: OOS is not all forward in calendar time
The original frozen D250 table reports Jul12-Aug07 train 9/0, Aug08-Sep01 validation 12/0, Sep01-Oct01 untouched OOS 23/0, Oct04-Nov03 untouched OOS 12/0, and **May 2026 sealed OOS 15/0**. May occurs BEFORE July development, so sealed May is a legitimate untouched *backward-in-time holdout*, but **not** a chronological forward test.

Reconcile the reported 50/50 OOS:
- 23 + 12 = **35/35 chronological later-period OOS**, after the July/Aug development.
- 15/15 sealed May is **backward holdout**, not forward.
- 35 + 15 = **50/50 untouched holdout**.
- 9 + 12 + 35 + 15 = **71/71 total**.
- Development + validation: 21/21, not untouched forward.
- The original reported ~22.4% coverage is 71/317, not 71/67 executable trades.
- 67 fully finalized opposite-local pairs leave **4 of 71 accepted episodes without a finalized pair** in that report; the four are not assumed profitable or stopped.

Using exact one-sided Clopper-Pearson 95% lower confidence bound for p with n successes and zero failures: p_low = 0.05^(1/n).
- 35/35 later chronological OOS: 91.80% lower bound.
- 50/50 mixed-direction untouched OOS: 94.18% lower bound.
- 71/71 entire tested set: 95.87% lower bound.
These are descriptive binomial bounds only, NOT multiple-testing-adjusted, and do not imply trade profitability or independent market regimes. For conventional two-sided 95% bounds, use 0.025^(1/n), yielding 90.00%, 92.89%, 94.94% respectively. This explains the ~92.9% and ~94.9% previously reported figures for 50 and 71.

## Implication for safe trades
- LOW->LONG and HIGH->SHORT frozen entry is unchanged.
- Report **35/35 later-period historical untouched signals** as the chronological forward-in-time historical check, not 50/50.
- Neither May holdout nor Sep/Oct historical replay is *prospective* live unseen forward data collected after 2026-11-12 rule freeze.
- Do not mix the 118/118 separate earlier cascade, 71/71 D250, 67 completed trades, or 411 all-local trades.
- 22 fixed-cut exits among 67 completed trades is a modeled count, not verified stop fills.
- Prior rejected flow+MFE, K0/K1 and pyramiding exits stay rejected.
- The current result is an evidence-accounting correction; no new realized return, monthly net equity, MTM DD, fill count or liquidation count is established.

## Reproduction
Read the five original rows (9,12,23,12,15) and their date ranges from H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md. Partition by date relative to Jul/Aug development, sum 23+12=35 and 15 separately. Confidence bounds: Python `0.025**(1/n)` for two-sided 95% all-success lower bound, `0.05**(1/n)` for one-sided 95%. No price series or simulated fills used.

## Next required execution replay
Recover immutable UTC ledger for 67 completed pairs and four censored/unmatched accepted episodes, join Public Trades/mark/L50/liquidations/OI by timestamp with missingness masks, and compare original 3x/5x against stop-risk 0.25/0.5%, fixed/structural stops, staging and opposite-local exits on the SAME sequential paths. No future extreme exit, no overlapping capital, no inferred fills. If artifacts cannot be recovered, mark the replay blocked rather than substitute snapshot classification.
