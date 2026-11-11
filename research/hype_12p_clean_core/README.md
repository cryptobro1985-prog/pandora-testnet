# HYPE 12-parameter clean-core cohort V1

Source: historical master artifact 13650399622 (2026-07-12 17:00 UTC through 2026-11-03).

Strict full-day rule: retain only UTC days where the rich causal stack needed by the terminal-local signature is present, including structure, executed flow, price response/efficiency, L50 book, liquidations, open interest, and mark/index/funding context. Missing microstructure is never imputed as zero.

Clean full UTC days found:
- 2026-07-17
- 2026-07-18
- 2026-07-29

Candidate snapshot counts: 136 / 210 / 150 respectively (496 total).
Each clean day also has 1440 compact M1 rows.

The 12 retained causal groups:
1. structure/extreme position;
2. candidate survival + retracement;
3. reversal price response;
4. aggressor flow imbalance;
5. buy/sell pressure;
6. price-impact efficiency;
7. trade activity/concentration;
8. L50 book state;
9. near-book depth;
10. liquidation climax/exhaustion;
11. open-interest context;
12. mark/index/funding context.

Additional causal structure context is retained: candidate side/extreme, 60m/6h/24h position, basis, near-touch depth and M1 context.

Teacher fields (strict Local labels) are evaluation-only and must never enter predictors.

Excluded from strict full-day core:
- 2026-08-08..2026-09-01: compact M1/flow is available, but not the full rich microstructure stack.
- 2026-09-01..2026-10-01: same limitation.
- 2026-10-04..2026-11-03: historical audit explicitly marks L50, liquidations and OI unavailable in archive-only pass.
- Other Jul-Aug days: at least one liquidation hourly source is missing.

Important data-quality caveat: prior audit showed the old Jul-Aug book_valid flag admitted some crossed books. Therefore this V1 is source-complete, not yet promotion-grade clean-book certification. Crossed-book masking must be applied before any promoted model score.
