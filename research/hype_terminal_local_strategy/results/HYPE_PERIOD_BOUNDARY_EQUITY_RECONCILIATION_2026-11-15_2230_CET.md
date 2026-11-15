# HYPE frozen 5x baseline: period-boundary equity reconstruction and evidence limits — 2026-11-15 22:30 CET

Research only. New reproducible calculation from original frozen report; NOT a tape replay, NOT a forward validation, no live trades.

## Input provenance
Read existing branch files:
- research/hype_terminal_local_strategy/results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md
- research/hype_terminal_local_strategy/results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md
- research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md
- research/hype_terminal_local_strategy/strict_execution_provenance_research.py

Frozen 5x 1%-cut baseline equity checkpoints: 100, 471.51, 755.20, 583.32, 1037.06, 1308.86 USD in reported May, Jul12-Aug07, Aug08-Sep01, Sep01-Oct01, Oct04-Nov03 order. These are historical modeled *closed* equity values, not exchange account statements. Missing calendar gaps are not zero-return observations.

## New period-to-period audit (not independent monthly net)
| Period | Starting closed equity | Ending closed equity | Period compounded return |
|---|---:|---:|---:|
| sealed May | $100.00 | $471.51 | +371.510% |
| Jul12-Aug07 | $471.51 | $755.20 | +60.166% |
| Aug08-Sep01 | $755.20 | $583.32 | -22.760% |
| Sep01-Oct01 | $583.32 | $1037.06 | +77.786% |
| Oct04-Nov03 | $1037.06 | $1308.86 | +26.209% |

The negative Aug08-Sep01 segment loses 22.760% of *closed equity* from the previous checkpoint. A fixed 0.25%-0.5% equity risk per trade cannot be claimed to reproduce these returns; the original simulation is 5x account notional exposure. The May result is sealed relative to Jul-Aug parameter selection but chronologically earlier than it: label it historical holdout, NOT forward. Jul12-Aug07 is development, Aug08-Sep01 validation; only subsequent Sep/Oct-Nov periods are chronological post-selection tests, conditional on the documented freeze date.

The 29.36% maximum *closed-equity* drawdown reported in the source is more severe than the 22.759% boundary-to-boundary drop here, as expected because checkpoints omit intraperiod equity. Neither metric is mark-to-market drawdown. No inference about actual liquidations is supported.

## Data gate before any trade-level claims
1. Obtain immutable per-trade manifest with trade ID, LOW/HIGH, strict H1 K2 availability timestamp, D250 signal timestamp, order submit/fill timestamp, price, and first causally available opposite local. Match these to actual archived M1 Public Trades, bid/ask/L50, mark, funding and liquidation/OI coverage, recording missing sources explicitly.
2. Enforce entry_ts >= max(H1 K2 available, D250 available, source watermark), with no same-side invalidation and no opposite K2 first. Split LOW->LONG and HIGH->SHORT.
3. Replay original 5x baseline *unchanged* and candidate 0.25%/0.5% stop-risk sizing on the SAME ordered events, with identical realistic fee/funding/slippage and shared equity, no overlapping capital reuse. Evaluate mandatory stop fill sequence, adverse gap, liquidation distance, staged entry, and rejected overlays only as separately labelled challengers.
4. Record each period's closed AND intratrade MTM equity, max DD, stop count, fill count, liquidation count, and realized vs peak MFE. Treat 67 frozen modeled trades and 67 geometry cases as unjoined until identifiers prove matching.
5. Preserve previous rejection of flow/MFE exit, K0/K1 and tight trailing. No threshold tuning, no new detector training, no production changes.

## Reproduction
```python
equity=[100,471.51,755.20,583.32,1037.06,1308.86]
names=['sealed May','Jul12-Aug07','Aug08-Sep01','Sep01-Oct01','Oct04-Nov03']
for name,a,b in zip(names,equity,equity[1:]):
    print(name, round(100*(b/a-1),3))
assert round(100*(1-equity[3]/equity[2]),3)==22.759
```

## Status
Completed new period-boundary arithmetic using fetched frozen source. No verified tape matched to fills; no new evidence of positive risk-adjusted returns or zero liquidations. This checkpoint is an evidence/accounting reconciliation, not the requested full execution replay.
