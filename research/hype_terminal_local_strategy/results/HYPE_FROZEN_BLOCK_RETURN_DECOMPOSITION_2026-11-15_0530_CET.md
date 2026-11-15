# HYPE frozen baseline: calendar-block return decomposition and forward evidence gate
Date: 2026-11-15 05:30 CET. Research only. No orders, production edits, retraining, or threshold tuning.

## Directly inspected frozen sources
- research/hype_terminal_local_strategy/results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md
- research/hype_terminal_local_strategy/results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md
- research/hype_terminal_local_strategy/results/HYPE_FORWARD_CHRONOLOGY_AND_TRADE_EVIDENCE_AUDIT_2026-11-15_0425_CET.md

## New calculation: what the reported 5x historical curve actually implies
For each period, compute 100*(end/start-1) using only published *closed-equity* boundary values, without inventing intraperiod marks, fills or returns. Values in dollars; boundaries are approximate and may include gaps between date ranges.

| Period | Start | End | Block closed-equity return |
|---|---:|---:|---:|
| sealed May | 100.00 | 471.51 | 371.5100% |
| Jul12-Aug07 development | 471.51 | 755.20 | 60.1663% |
| Aug08-Sep01 validation | 755.20 | 583.32 | -22.7595% |
| Sep01-Oct01 later OOS | 583.32 | 1037.06 | 77.7858% |
| Oct04-Nov03 later OOS | 1037.06 | 1308.86 | 26.2087% |

**New risk finding:** validation Aug08-Sep01 lost 22.7595% of closed equity, even though the D250 entry detector reported 12 true / 0 false in that period. Correctly identifying a terminal local is not equivalent to profitable execution or exit. This is a calendar-block loss, not a mark-to-market maximum drawdown. The two later-dated OOS blocks have historical simulated returns 77.7858% and 26.2087%, but their entry, fill, stop and MFE tapes have not been independently replayed; these figures are **not** forward executable returns.

## Reproducibility
```python
equity=[100,471.51,755.20,583.32,1037.06,1308.86]
for a,b in zip(equity,equity[1:]):
    print(f"{100*(b/a-1):.4f}%")
```

## Execution evidence and acceptance gate
D250 remains frozen (rev_atr>2.0840049433824706; trade_ratio5>0.2727842248141979; side-normalized flow15<0.4504731635235635). LOW->LONG, HIGH->SHORT only after causal availability. Keep original 1% adverse-price cut, 0.15% assumed roundtrip fees, no tight trail, and K2-available opposite local as untouched baseline. Historical 67 finalized exits and 4 censored signals must remain distinct.

The published $100->$1308.86 is an historical sequential simulation with a sealed May holdout preceding July development. Neither the 35/35 later-dated detector hits nor the later-dated equity blocks certify a truly unseen *post-freeze live* forward trade replay.

Risk alternatives remain **unscored** until an event-ordered matched tape exists. When available, compare fixed baseline and 0.25%-0.5% equity stop-risk, <=1% aggregate stop-risk, staged entry, break-even/profit lock, all on identical fills/costs/funding and one capital ledger. Do not reuse overlapping capital. Distinguish LONG and SHORT slippage, stop gaps, liquidation distance, and stop-first intrabar ambiguity. Do not re-promote previously rejected MFE overlays without independent later-period evidence.

Missing: original 71 timestamped signals, 67 completed rows and four censored, synchronized Public Trades/CVD/L50/liquidations/OI and order execution proxies. No new monthly MTM DD, liquidation count, stop fills, MFE capture, or net cost-aware replay can be asserted from boundary equity alone.
