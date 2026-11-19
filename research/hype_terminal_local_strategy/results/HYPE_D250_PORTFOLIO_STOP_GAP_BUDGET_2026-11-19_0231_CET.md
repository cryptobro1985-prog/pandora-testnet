# D250 portfolio stop-gap risk budget — 2026-11-19 02:31 CET

Research-only incremental deterministic calculation. No detector training, new thresholds, production change, or real orders. Not an exchange replay.

## Inputs read from this exact branch
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md: D250 frozen thresholds rev_atr > 2.0840049433824706, trade_ratio5 > 0.2727842248141979, flow15 < 0.4504731635235635; 67 causal opposite-local exits, median MFE giveback 61.2%, median structural-stop distance 3.14%.
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md: development-selected 1% adverse-entry stop; 0.15% round-trip cost assumption, 67 simulated sequential trades; no matched fills.
- HYPE_D250_COST_AWARE_NOTIONAL_STRESS_2026-11-19_0133_CET.md: initial single-trade stop gap sensitivity.

## New analysis: concurrent-risk aggregation and minimum-order feasibility
For E=$100, each trade's risk fraction r, trigger stop d=0.01, assumed round-trip fees f=0.0015, budgeted incremental adverse gap g: notional N=E*r/(d+f+g). This assumes fees are entirely represented by f and excludes unknown funding/entry slippage; production sizing must subtract these from available risk. 25x margin=N/25 is illustrative only, NOT a liquidation safety test.

| Risk/equity | Budgeted gap | Notional $ | 25x initial margin $ | Equity loss if actual gap=3% |
|---:|---:|---:|---:|---:|
| 0.25% | 0.5% | 15.1515 | 0.6061 | 0.6288% |
| 0.25% | 1.0% | 11.6279 | 0.4651 | 0.4826% |
| 0.25% | 3.0% | 6.0241 | 0.2410 | 0.2500% |
| 0.50% | 0.5% | 30.3030 | 1.2121 | 1.2576% |
| 0.50% | 1.0% | 23.2558 | 0.9302 | 0.9651% |
| 0.50% | 3.0% | 12.0482 | 0.4819 | 0.5000% |

**Portfolio result:** Two simultaneously open 0.50%-budget positions, each sized using 0.5% gap, have planned aggregate stop loss 1.00% of starting equity, but at a common 3% adverse gap could lose **2.5152%** before funding/other costs. Two 0.25%-budget positions would lose 1.2576%. Therefore the stated 1% aggregate stop-risk limit is only a *scenario-based budget*, not a worst-case bound. Shared market-gap correlation matters. A single HYPE symbol should not open opposite overlapping positions; sequential capital must be locked until an exit fill is confirmed.

**Feasibility gate:** At $100 account equity and 3% stress gap, the 0.25% trade risk allows only $6.0241 notional. If the venue's current minimum order notional or minimum quantity exceeds the permitted notional, the only risk-compliant action is SKIP; do not round up. Actual minimums, fee tier, funding, mark-price liquidation path and maintenance margin are not verified in this checkpoint.

**Entry/exit causal gate:** LOW->LONG uses post-confirmation ask fills and stop SELL bid depth; HIGH->SHORT uses post-confirmation bid fills and stop BUY ask depth. Check opposite H1 confirmation timestamps, same-side re-extremes, gap coverage and no future features. Do not infer zero liquidations from stop placement alone. Keep previously rejected MFE trailing and K0/K1 overlays rejected.

## Reproducibility
For each r in [0.0025,0.005] and g in [0.005,0.01,0.03], compute N=100*r/(0.01+0.0015+g), margin=N/25, stressLossPct=N*(0.01+0.0015+0.03) (since E=$100). Concurrent two-position stress loss is 2*stressLossPct. Round only for display.

## Evidence status and next gate
No matched 67-trade UTC tape, L50 bid/ask execution, funding, mark-price liquidation series or unseen-forward replay was evaluated here. No monthly net equity, closed/MTM DD, fills, stop counts, liquidation counts, or MFE capture claimed. Next iteration must prioritize actual matched event data and full chronological execution replay; further hypothetical sensitivity grids alone cannot establish profitability.
