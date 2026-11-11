# HYPE completed-M1 CV workflow checkpoint — 2026-11-11

Status: VERIFIED STATIC MISMATCH / CI PENDING / NO EDGE CLAIM.

One issue: workflow default and execution both used `completed_m1_events`, while post-run validation expected `legacy_age_grid` if no dispatch input. Changed assertion to `completed_m1_events`.

Pre-fix run [43003617117](https://github.com/cryptobro1985-prog/pandora-testnet/actions/runs/43003617117) failed in **Regression tests before costly CV**, before the inconsistent assertion would run. Therefore this fix is NOT proven to resolve the actual current CI failure. Run [43003617029](https://github.com/cryptobro1985-prog/pandora-testnet/actions/runs/43003617029) also failed in PAPER regression tests. The exact regression traceback has not been retrieved.

Next: obtain regression traceback, fix root cause with a focused test, rerun CV CI, inspect results. No retraining or threshold search on already inspected OOS. Primary 0.33–0.40% causal Local concept unchanged. No new first-signal, MFE, MAE, DD or PnL metrics. Real orders OFF.
