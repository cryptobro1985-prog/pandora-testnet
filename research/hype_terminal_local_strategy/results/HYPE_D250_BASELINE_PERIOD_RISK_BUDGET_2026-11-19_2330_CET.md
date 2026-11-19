# HYPE D250 — frozen 67-trade baseline accounting and risk-budget incompatibility (2026-11-19 23:30 CET)

Research-only, source-derived arithmetic checkpoint. No training, orders, production changes or thresholds changed.

## Sources checked at exact branch
- `research/hype_terminal_local_strategy/results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md` (blob be76b9a61c86ec59c94b885eea4b15ee97cc1c05)
- `research/hype_terminal_local_strategy/results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md` (blob 54865475546c10cd555199c65a2a81ce0f14aab7)
- `research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md` (blob d4cb87ed203f19f8b5e89752392947f7e9e14fde)
- previous 67-trade provenance and Git inventory checkpoints.

## New reproducible calculation A — 5x baseline period endpoint decomposition
The frozen asymmetric-risk report lists these *modeled* 5x account-exposure endpoint balances. Period returns are computed by `100*(end/start-1)` using the immediately preceding endpoint, **not** as independent month returns. May precedes July chronologically, but there are missing intervals, and the report does not disclose trade-level capital flows or MTM.

| Period | Start $ | End $ | Modeled endpoint return |
|---|---:|---:|---:|
| May | 100.00 | 471.51 | 371.510% |
| Jul12-Aug07 | 471.51 | 755.20 | 60.166% |
| Aug08-Sep01 | 755.20 | 583.32 | -22.760% |
| Sep01-Oct01 | 583.32 | 1037.06 | 77.786% |
| Oct04-Nov03 | 1037.06 | 1308.86 | 26.209% |

The Jul/Aug negative endpoint interval shows that aggregate final growth does not establish consistently positive period performance. These are endpoint-to-endpoint implied changes, **not** independently verified monthly net equity and **not** monthly maximum DD. Do not interpolate equity curves or count liquidations from them.

## New reproducible calculation B — original leverage vs proposed 0.25–0.5% stop-risk budget
For exploratory comparability ONLY, assume stop distance 1.00% of entry price, round-trip fee 0.15% of entry notional, no funding, slippage or gap. Modeled full-loss fraction per unit notional = 0.0115. Risk-based account exposure = equity risk fraction / 0.0115.

| Stop-risk budget | Maximum nominal / $100 equity | Account exposure | Initial margin / $100 at 25x instrument leverage |
|---|---:|---:|---:|
| 0.25% | $21.7391 | 0.217391x | $0.8696 |
| 0.50% | $43.4783 | 0.434783x | $1.7391 |

Under this simplified loss model, 3x exposure incurs 3.45% equity loss for a stop, and 5x incurs 5.75%, matching frozen report worst modeled trade values. Therefore 3x/5x baselines violate a proposed **0.5%** stop-risk limit by factors 6.9x and 11.5x respectively. They cannot be presented as risk-budget-compliant strategies. The 0.25%-0.5% candidates would require much smaller notional, with additional reduction for gap/slippage/funding, and their historical compound cannot be inferred by scaling the published endpoints.

The 1% adverse stop may differ from the structural stop, and the actual stop distance, execution fees on entry/exit notionals, price gaps, trigger source, mark liquidation and funding must be resolved per trade before the final risk budget is enforceable. For a total 1% open stop-risk limit, enforce `sum(position_stop_loss_worst_case) <= 0.01*current_equity` including reserved risk from open orders and gap buffer. This is a proposed accounting invariant, not a tested strategy.

## Data status / gate
No matched 67-row UTC trade manifest or bid/ask/mark/L50 event tape was recovered in this iteration. The calculations above are **new deterministic analysis of saved report numbers**, not 67-trade event replay. Matched full executions verified: 0/67. New fill, liquidation, MTM DD, MFE retention, unseen-forward and independent monthly net-equity results: NOT COMPUTED. Previously rejected profit-lock overlays remain rejected.

## Next execution action
Locate historical 67-trade manifest and actual quote/mark/L50 streams in existing Actions/external artifacts; join causal D250-known timestamps, stops and K2-known opposite exits. Run unchanged 3x/5x baseline and risk-based 0.25/0.5% variants with identical samples and execution assumptions, then measure true MTM DD and net equity. Never claim zero liquidations from missing mark data.
