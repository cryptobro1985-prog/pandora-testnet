# HYPE frozen-entry: historical regime stability checkpoint — 2026-11-13

Research-only, no orders, no production change, no detector retraining.

## Exact source and new calculation
Input: `research/hype_terminal_local_strategy/results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`. This is the *reported* frozen post-local 1% adverse-price stop / causal opposite-local exit at 5x account exposure, 0.15% roundtrip notional cost, 67 sequential historical trades. Use reported end-of-regime equity as empirical source, **not reconstructed fills**.

A new reproducible `research/hype_terminal_local_strategy/frozen_regime_equity_audit_20261113.py` computes each regime's return from adjacent recorded equity endpoints. Executed independent Decimal calculation, matching:
| Recorded regime | Start equity | End equity | Regime net return |
|---|---:|---:|---:|
| sealed May | 100.00 | 471.51 | +371.51% |
| Jul12-Aug07 | 471.51 | 755.20 | +60.17% |
| Aug08-Sep01 | 755.20 | 583.32 | **-22.76%** |
| Sep01-Oct01 | 583.32 | 1037.06 | +77.79% |
| Oct04-Nov03 | 1037.06 | 1308.86 | +26.21% |

These are NONCONTIGUOUS preserved slices, not a continuous investable five-month curve; each ratio uses the carried-forward simulation equity. 5x exposure was historically reported to have 29.36% maximum **closed-equity** drawdown, and no reliable intra-trade DD is available. These regime returns are not evidence of >=30% every month. August's negative return is a material failure of that objective even on preserved history; Oct04-Nov03 is also below 30%. The spectacular May figure should not be extrapolated.

## Hypothesis decision
Hypothesis rejected: "Frozen 1%-cut 5x strategy reliably earns >=30% every historical regime." Rejected on actual reported Aug08-Sep01 and Oct04-Nov03 returns. Also cannot assert zero liquidation from closed-only equity. This is an empirical check against previously stored real-market simulation outputs, not a fresh trade-level backtest.

## Execution-specific implications
The previous frozen D250 high-precision signal is a late entry (71/71 historical first-signals, ~22.4% coverage); a strict 285m detector (101/101 historical) is a different cohort and cannot be blended with D250 results. Existing rich high-confidence paths in `research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.json` are not permission to use future labels. A true confirmed local does not prove a positive *subsequent trade* after costs.

At 1% price stop + 0.15% roundtrip fees + 0.10% illustrative slippage reserve, planned 5x exposure stop loss is ~6.25% of equity, whereas a 0.5% risk budget permits ~0.4x notional/equity; this is sizing algebra, not observed slippage. Gap stops can exceed estimates. The old high-leverage compound must not be relabelled a low-risk result.

## Data recovery and next falsifiable experiment
Read `research/hype_all_in_one/MANIFEST.json` and `research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.json`: master artifact `HYPE-HISTORY-20260712-20261103-MASTER`, `local116-HYPE`, `HYPE-RICH-STRONG-*`, `HYPE-7LAYER-*` are named, but not materialized here. GitHub code search on the default branch for trade row identifiers and master name returned no matches (this search is not exhaustive of the research branch). Previously checked failed July run 42660911066 had no run artifacts. No aligned per-fill 67-row tape obtained in this run.

Next recover a specific surviving artifact ID or regenerate trade rows from original Bybit event data; same entries/exits across 0.2x/0.4x/0.8x/3x/5x and per-side LOW/HIGH, timestamped fill/stop/fee/funding, conservative intra-bar ordering, MFE/MAE, mark-to-market DD and liquidation buffer. Do not invent monthly results. Rejected profit-lock overlays remain rejected until unseen chronological evidence overturns them.
