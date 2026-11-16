# HYPE frozen-entry chronological equity and evidence audit — 2026-11-17 00:32 CET

Research only. No detector retraining, new thresholds, production changes or orders.

## New concrete audit: chronological equity order in saved baseline

Read the original `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md` directly on this branch. Its 5x sequential account ledger is printed as:

| Printed sequence | End equity USD | Printed period |
|---|---:|---|
| 1 | 471.51 | sealed May |
| 2 | 755.20 | Jul12-Aug07 |
| 3 | 583.32 | Aug08-Sep01 |
| 4 | 1037.06 | Sep01-Oct01 |
| 5 | 1308.86 | Oct04-Nov03 |

**Finding:** printed order puts May before July, consistent with calendar order, BUT the same report explicitly says the 1% stop was selected on July/Aug development and then tested on *sealed May*. Thus May is a backward-in-time holdout, not a truly unseen **forward** test following the development period. It must never be labeled a chronological forward result. May is a temporal reverse holdout. The printed sequential compound also cannot be treated as a deployment-forward equity curve without a trade-level calendar-ordered ledger and capital-state reconstruction.

The sealed Sep/Oct and Oct/Nov periods are candidate later-period forward evaluations **only if** their data were not used in feature, threshold or policy selection. This checkpoint does not establish that independence. The original report does not provide immutable trade IDs, exact UTC entry/exit timestamps, per-trade notional/fills, funding, mark prices or individual MTM curves. Its 18.56% (3x) and 29.36% (5x) DD are **closed equity only**, not MTM.

## Reproducible numeric reconciliation

Original 5x sequence printed above yields period equity multipliers:
`[471.51/100,755.20/471.51,583.32/755.20,1037.06/583.32,1308.86/1037.06]`.
Those are **ledger-block** ratios, not independently investable calendar-month returns. July and August windows overlap boundary days and September/October windows are not calendar months.

The original paper reports 67 completed sequential trades, 22 1%-cut exits, and 49.25% positive after costs. At two-decimal rounding 49.25% of 67 is consistent with 33 wins. This is not 67 validated exchange fills.

## Implications for the requested replay

1. Recover immutable 67-trade ID ledger and signal timestamps first. Use true UTC chronological ordering, a single evolving cash account and prohibit overlap reuse. Preserve exact original entry policy D250 and stop policy as baseline.
2. Split by LOW→LONG and HIGH→SHORT, with pre-confirmation MAE, order submission time, stop level, mark-price liquidation precedence, fee/funding and slippage provenance.
3. Event coverage gate passing is **not** an executed fill. Missing five interior M1 minutes or missing mark/book data yields UNKNOWN, not zero liquidations.
4. Compare same-ID baseline, 0.25% and 0.5% stop-risk sizing (total 1% max), staged entries and protective exits only after reconstructing same-tape executions. Preserve rejected overlays as rejected.
5. Monthly **calendar** net equity, intratrade MTM DD, closed DD, stops, fills, liquidations, MFE capture/giveback and truly later untouched forward results are NOT VERIFIED in this checkpoint.

## Evidence
- `research/hype_terminal_local_strategy/results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`
- `research/hype_terminal_local_strategy/results/HYPE_EXECUTION_PROVENANCE_GAP_RISK_2026-11-16_2326_CET.md`
- `research/hype_terminal_local_strategy/trade_event_coverage_gate_20261116.py`

### Exact replayable calculation (Python stdlib)
```python
e=[100,471.51,755.20,583.32,1037.06,1308.86]
for i in range(1,len(e)):
    print(i,round(e[i]/e[i-1],6),round(100*(e[i]/e[i-1]-1),3))
assert round(100*33/67,2)==49.25
```

**Verdict:** a substantive audit finding about temporal validation, not a new performance result. No claims of new trades, monthly net, MTM, verified fills, or no liquidations.
