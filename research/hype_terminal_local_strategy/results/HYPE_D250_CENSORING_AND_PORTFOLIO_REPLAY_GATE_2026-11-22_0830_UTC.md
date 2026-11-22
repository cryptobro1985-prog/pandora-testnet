# D250 censored signals and portfolio replay gate — 2026-11-22 08:30 UTC

Research-only, source-derived accounting; **not** matched Bybit execution replay. No retraining, new thresholds, production changes or orders.

## Source of record
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`: 71 accepted D250 signals, 67 with fully finalized opposite strict H1 Local, median MAE -0.414%, worst observed MAE -1.958%, 61.2% median MFE giveback on causal exits.
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`: 67 completed sequential trades, 22 modeled 1% adverse cuts, 49.25% positive after modeled 0.15% round trip cost.
- `results/HYPE_D250_67_TRADE_OUTCOME_ACCOUNTING_2026-11-22_0735_UTC.md`: rounded 33 winners, 34 nonpositive, at least 12 nonpositive without fixed-cut exits conditional on all cuts being losses.

## New reproducible checks
1. **Outcome censoring:** 4/71 = 5.6338% of accepted signals lack finalized opposite-local outcome; completed-only reporting covers 67/71 = 94.3662%. These four must be carried as open/unknown in chronological MTM, not silently dropped or assumed losers/winners. Their exposure, dates and unrealized PnL cannot be inferred from summaries.
2. **Different outcome definitions:** causal opposite-local exit winrate 67.16% of 67 (~45 winners) from the minimal-rule audit versus 49.25% of 67 (~33 winners) from the 1% loss-cut audit. Difference ~12 positive outcomes **across different exit policies**, not proof that the cut destroyed exactly 12 profitable trades; per-trade matching is required. Similarly, 22 cut exits cannot be mapped to specific winners/losers from aggregates.
3. **MAE versus fixed cut:** worst observed diagnostic MAE of -1.958% exceeds the frozen 1% adverse cut by 0.958 percentage points. Median diagnostic MAE -0.414% is within 1%. These are summary extremes and do not establish how many individual stops fired or their fill price; intrabar ordering and mark/last trigger are missing.
4. **Portfolio ledger invariants:** for every accepted signal require `candidate_time_utc`, `confirmation_time_utc`, `eligible_time_utc`, `side`, `source_event_id`, `next_observed_time_utc`, and a distinct `outcome_status` (open, filled, stopped, opposite_confirmed, censored, rejected). Never enter before available confirmation; never use future opposite extreme as exit. Reserve margin and risk on open positions; enforce <=1% combined stop-risk and no capital reuse.
5. **Cost and safety invariants:** derive notional from risk budget 0.25%-0.5% equity per trade divided by (stop distance + fee + stress gap/slippage + funding reserve). Validate exchange quantity step, minimum notional, current mark-price liquidation buffer, stop-trigger mechanism, and fail closed on missing data. Compare unchanged original with low-risk variants on identical chronological entries and available fills; no made-up L50/OI/liquidation values.

## Arithmetic reproduction (Python 3)
```python
n_accepted, n_finalized = 71, 67
print(round(100*(n_accepted-n_finalized)/n_accepted, 4)) # 5.6338
print(round(100*n_finalized/n_accepted, 4)) # 94.3662
print(round(n_finalized*0.6716), round(n_finalized*0.4925)) # 45 33
print(round(1.958-1.0, 3)) # 0.958 percentage points
```

## Evidence gate and next action
No individual UTC entry/exit manifest or matched rich Bybit M1/Public Trades/CVD/L50/OI/liquidation/mark execution tapes are provided in these source reports. **Do not assert** net monthly equity, MTM drawdown, stops actually filled, liquidations, forward performance, or MFE retention. Recover original event-level manifest and coverage masks before a same-sample replay. Previously rejected profit protection overlays remain rejected; frozen D250 unchanged.
