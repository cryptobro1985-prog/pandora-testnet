# HYPE frozen-entry execution evidence and loss attribution — 2026-11-13 21:32 CET

Research-only; existing branch; no detector training, no production change, no real orders.

## Verified input provenance
Read directly on this branch:
- results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md
- results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md
- results/HYPE_GAP_SIX_LOSS_SENSITIVITY_2026-11-13_2033.md
- research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md

Frozen D250: rev_atr > 2.0840049433824706; trade_ratio5 > 0.2727842248141979; flow15 < 0.4504731635235635. LOW -> LONG, HIGH -> SHORT only after causal confirmation. 71/71 accepted true on tested historical episodes, 22.4% coverage; 50/50 OOS. This is not prospective execution validation.

## New reproducible attribution calculation (integer counts, not new tape replay)
Frozen asymmetric report says 67 sequential completed trades; 22 adverse-cut exits; 49.25% of closed trades positive after costs. The only integer winner count consistent with rounded 49.25% is 33 winners (33/67 = 49.2537%); hence 34 non-winning trades. Therefore **at least 12 non-winning trades were not 1%-stop exits** (34 - 22 = 12), even under the conservative assumption that every stop exit was non-winning. If any stop exit was positive, the count of non-winning non-stop exits is higher. This exposes an exit problem independent of stop-hit execution: a mandatory stop alone does not remove losses from causal opposite-local exits.

Do NOT claim exactly 12 losing opposite-local trades: flat trades, positive stopped trades, and classification details are not available in the aggregate report. Need individual ledger to partition precisely.

## New capital-usage consistency audit
Original 25x instrument leverage with 20% account margin implies 5x account notional, not 25x account notional. Prior 1% stop + 1% adverse gap + 0.15% fee scenario gives c=2.15% of notional. At original 5x account notional, scenario loss is 10.75% equity per stop (before funding); at risk-sized 0.23256x notional, 0.50% equity. This is **21.5 times** smaller nominal exposure, so previous $100->$1,308.86 5x compounded simulation cannot be transferred to the risk-sized alternative. This is a counterfactual sensitivity, not a new trade replay.

At original 5x notional, 25x isolated margin = 20% equity; at risk-sized 0.23256x, isolated margin = 0.93024% equity. Both positions have the same approximate position-level liquidation distance at identical isolated leverage, despite very different account loss budgets. Any real execution comparison must record actual liquidation prices/mark prices and prevent stop placement beyond liquidation.

## Evidence search
GitHub connector code searches for HYPE_ASYMMETRIC_RISK_FINAL, entry_ts exit_ts HYPE, HYPE trade ledger, and hype rich m1 on the repository's indexed default branch returned no matches. IMPORTANT: connector code search is default-branch indexed, so zero matches do NOT establish that timestamped trades/rich partitions are absent from the research branch. The four named branch files above were successfully fetched directly.

## Replay contract for next genuinely empirical iteration
1. Materialize immutable 67-trade ledger (side, candidate extreme timestamp, confirmation availability timestamp, entry decision timestamp, entry price, stop, opposite-local K2 availability, exit timestamp, capital state).
2. Match Bybit Public Trades, mark/index, L50 book, OI, liquidations, funding by event timestamp and explicit availability cutoff. Missing fields = NA, not zero.
3. Independently compute LOW->LONG and HIGH->SHORT pre-confirmation MAE, entry geometry, post-entry MAE/MFE, worst stop gap, fill depth and liquidation buffer.
4. Replay **unchanged original** and challengers on identical chronological trades and fees/funding/slippage: 5x baseline, 0.25/0.5% equity-risk notional, staged entry, mandatory stop, BE/profit lock, and opposite-local hold. Enforce one capital ledger, no overlapping capital reuse.
5. Monthly net equity, closed and mark-to-market DD, count of stops, fills, liquidations, captured/given-back MFE, and untouched forward. No thresholds re-fit; prior rejected overlays stay rejected unless independent evidence changes the verdict.

## Verdict
This iteration adds an auditable loss-attribution bound (>=12 non-winning non-stop exits under stated assumptions) and exposure-comparability correction. **No matched tick-level replay completed; no new observed fills, liquidation count, monthly net or forward return.** Do not promote to live trading.
