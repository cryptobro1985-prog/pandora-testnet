# D250 leverage ceiling sensitivity — 2026-11-23 07:32 CET

Research-only deterministic stress calculation, **not Bybit matched execution replay**. Existing source files read directly from branch: `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md` (blob `54865475546c10cd555199c65a2a81ce0f14aab7`) and `d250_cost_aware_risk_gate.py` (blob `50fa8130b7fd8f211deb7124612ddbaefca81e31`). No detector retraining or threshold modification.

## New calculation

Apply the actual walk-forward report's **median diagnostic structural stop of 3.140%**, and compare to 1.00% adverse-price cut from the separate asymmetric-risk baseline. Each is a **different exit policy**; do not combine them or claim they were observed on the same trades. Scenario inputs: 0.5% equity stop-risk, $100 equity, 0.06% entry fee, 0.06% exit fee, 0.03% entry slip, 0.05% stop slip, maintenance margin proxy 0.5%, and three stop gaps (0.2%, 1%, 3%). Notional = $0.50 / (stop fraction + gap + entry/exit fees + entry/stop slippage). Approximate strict leverage ceiling: integer L satisfying stop + gap + stop slip + maintenance proxy < 1/L. This is **not** a Bybit liquidation formula.

| Stop % | Gap % | Required buffer % | Highest integer leverage proxy | Notional $ | Margin at that leverage $ | 25x proxy passes? |
|---:|---:|---:|---:|---:|---:|:---:|
| 1.00 | 0.2 | 1.75 | 57x | 35.71 | 0.63 | YES |
| 1.00 | 1.0 | 2.55 | 39x | 22.73 | 0.58 | YES |
| 1.00 | 3.0 | 4.55 | 21x | 11.90 | 0.57 | NO |
| 3.14 | 0.2 | 3.89 | 25x | 14.12 | 0.56 | YES |
| 3.14 | 1.0 | 4.69 | 21x | 11.52 | 0.55 | NO |
| 3.14 | 3.0 | 6.69 | 14x | 7.89 | 0.56 | NO |

**Interpretation:** With the observed median diagnostic structural stop, 25x passes only the 0.2% gap scenario, and only with a thin proxy buffer; 1% and 3% gaps imply ceilings 21x and 14x. Even a 1% stop fails at 25x if gap reaches 3%. Reducing nominal position size to 0.5% equity risk **does not itself move the stop ahead of liquidation** at fixed isolated leverage. This is a scenario sensitivity calculation, not a claim of real liquidation frequency. The real liquidation level depends on Bybit instrument tier, margin mode, mark price, funding, account equity and dynamic margin.

## Reproducibility

Read the two blob SHAs above. Run this standalone Python 3 snippet (no external packages):

```python
import math
for stop in (0.01, 0.0314):
    for gap in (0.002, 0.01, 0.03):
        buffer = stop + gap + 0.0005 + 0.005
        max_l = math.ceil(1 / buffer) - 1
        notional = 0.50 / (stop + gap + 0.0005 + 0.0003 + 0.0012)
        print(stop, gap, round(buffer, 6), max_l, round(notional, 4), buffer < 1/25)
```

## Gate for next real replay

Need immutable 71-signal timestamps, quote/trade/mark streams and funding/maintenance tiers for each trade. Separate LOW->LONG and HIGH->SHORT; preserve the original 67 sequential-trade baseline unchanged. Only then compute net monthly equity, open-equity MTM DD, realized DD, fills, gaps, liquidations, MFE giveback and independent forward. No profit-protection overlay promoted. **No real trades, no production change.**
