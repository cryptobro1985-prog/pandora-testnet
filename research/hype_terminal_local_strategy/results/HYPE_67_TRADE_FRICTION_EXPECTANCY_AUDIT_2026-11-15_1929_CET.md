# HYPE frozen 67-trade aggregate expectancy and friction tolerance audit — 2026-11-15 19:29 CET

Research only. **New arithmetic audit of preserved aggregates, not event-level replay.** Read original `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`, `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`, `HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md`, and 18:25 risk stress checkpoint from this branch. Frozen D250, original 1% cut, no tight trail, no changes.

## New calculation: aggregate expectancy versus additional execution friction

Original 67 sequential simulated completed trades report positive-close rate 49.25%, average positive *equity* return +14.16% at 5x account exposure, average negative equity return -4.37%, assumed 0.15% round-trip notional cost. At 67 trades, 49.25% rounds to 33 winners and 34 losers. Treat displayed means as rounded, not exact per-trade ledger.

- Winner contribution to sum of trade equity returns: 33 * 14.16 = **467.28 percentage points**.
- Loser contribution: 34 * -4.37 = **-148.58 percentage points**.
- Sum: **+318.70 percentage points**; arithmetic average **+4.7567% equity/trade** at nominal 5x, or **+0.95134% of notional/trade**.
- Ratio of positive to absolute negative return sums: **3.1452**, consistent with reported profit factor 3.14.
- Under the *very restrictive assumption* that all 67 trades retain the same fixed 5x account exposure, unchanged fills and chronology, and an identical extra round-trip friction charge per notional, the **arithmetic** average reaches zero with **0.95134 percentage points additional notional friction** over the original 0.15% modeled. This is NOT a break-even bound for geometric compound, MTM, adverse fill timing, stops, funding variation, or forward periods.

| Additional round-trip friction / notional | Approx. average equity return/trade at 5x |
|---|---:|
| 0.00% | +4.7567% |
| 0.10% | +4.2567% |
| 0.25% | +3.5067% |
| 0.50% | +2.2567% |
| 0.95% | +0.0067% |
| 1.00% | -0.2433% |

**Critical distinction:** a 1% *adverse stop gap* is NOT an identical 1% friction on all 67 trades. It is concentrated in stop-exposed episodes and can change event ordering, equity, liquidations and compounding. Do not use this arithmetic cushion to justify higher exposure or to assert net edge. With 22 modeled fixed-cut exits, any extra 0.5% of notional on just those exits corresponds to 22/67 * 5 * 0.5% = **0.8209 percentage points** of average equity return/trade at 5x, conditional on same 22 exits and fixed exposure. Actual stops may differ on replay.

## Reproducible calculation

```python
n=67; w=33; l=34; avg_win=14.16; avg_loss=4.37; exposure=5.0
total=w*avg_win-l*avg_loss
print('sum_equity_return_pp',total)
print('mean_equity_return_pct',total/n)
print('profit_factor',w*avg_win/(l*avg_loss))
print('arithmetic_extra_notional_friction_break_even_pct',total/n/exposure)
for d in (0,.10,.25,.50,.95,1.00):
    print('extra_friction_pct_notional',d,'mean_equity_pct',(total/n-exposure*d))
print('stop_only_extra_0.5_pct_notional_mean_equity_drag_pct',22/67*5*.5)
```

## Execution/replay priority

1. Find per-trade timestamped 67-trade manifest and recovered M1 tape. Do not confuse the 4 unfinalized opposite-local episodes with executed positions.
2. For each LOW->LONG and HIGH->SHORT require K2 H1 availability and D250 feature cutoff before entry; verify event order and M1 gaps.
3. Replay 1% stop first-hit and opposite K2 exit with same fees, measured bid/ask spread/slippage and funding; absent L50/mark => UNKNOWN, not filled/zero liquidation.
4. Build a single non-overlapping ledger and compare unchanged 5x baseline against 0.25%/0.5% stop-risk scenarios (<=1% aggregate), plus staged entry and BE/profit-lock only as challengers. Preserve rejected MFE overlays as rejected absent independent evidence.
5. Report monthly net equity, MTM/closed DD, fill/stop/liquidation counts, MFE captured/given back and strictly chronological unseen forward; **none can be inferred from aggregate arithmetic**.

No new detector training, thresholds, branches, production changes or real orders.
