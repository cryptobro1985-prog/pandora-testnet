# HYPE true H1-close causal replay — 12 selected strong days
Date: 2026-11-11. Research only; no trading strategy or live orders changed.

Decision: at the closing timestamp of each completed H1 bar that extends the structural HIGH or LOW beyond the prior six *completed H1 candles*. No 6h trading timeframe. Future K2/opposite pivot are strictly teacher/evaluation only. Inputs: existing compact M1 history + twelve 7-layer overlays from GitHub run 43031802445. Dates: SEP03 SEP10 SEP17 SEP18 SEP30 OCT05 OCT08 OCT12 OCT22 OCT26 OCT27 OCT30.

## H1-close universe
140 completed H1 bars made a structural candidate. Of these 25 became finalized terminal H1 (13 LOW, 12 HIGH); 114 did not; 1 was censored. All 25 finalized locals were eligible at their H1 closing time. These are H1 **candidate bars**, not 140 confirmed pivots or 140 executed trades.

## Existing-data differences at H1-close
Descriptive AUC (0.5 chance):
- closing distance from own candle extreme in price units: 0.810
- directional position of close within H1 candle: 0.804
- old-side failure to move price relative to volume: 0.761
- new-side price-impact efficiency over H1: 0.760
- valid L50 imbalance nearest 5 levels: 0.745; 10 levels: 0.729
Median minute of eventual extreme: finalized 23.6 versus nonterminal 49.4. Among 25 true terminals final extreme existed by H1 minute 45/50/55 in 21/22/23 cases respectively. This is not evidence it was reliably recognizable early.

## Day-held-out *diagnostics* (139 evaluable H1-close bar candidates)
Pre-existing feature-family logistic probe, diagnostic decision probability 0.5, not a trading rule.
H1 structure: TP16 FP29 FN9 TN85 (precision 35.6%, recall 64%)
H1 + flow/price impact: TP15 FP34 FN10 TN80
H1 + available rich: TP17 FP27 FN8 TN87 (precision 38.6%, recall 68%)
Not strictly chronological: training of earlier test days may include later days.

## Strict chronological diagnostic
Train SEP03 SEP10 SEP17 SEP18 SEP30 OCT05; test OCT08 OCT12 OCT22 OCT26 OCT27 OCT30. 68 evaluable bars (13 true):
H1 structure: TP10 FP16 FN3 TN39.
H1+flow: TP10 FP23 FN3 TN32.
H1+available rich: TP10 FP18 FN3 TN37, precision35.7%, recall76.9%.
This is NOT sufficient to claim a near-zero-FP entry signal.

## Rich data limitations at hour close
Among 25 finalized terminal candidates: valid L50 snapshot 21/25, but 5/15/30/60s continuous L50 dynamic-window valid 0/25. Valid liquidation 180s 16/25. OI 5m delta valid 23/25. Historical long/short ratio missing. Invalid precomputed basis feature excluded. Missing values masked rather than zero filled.

## Conclusion
When the true H1 terminal local forms, its extreme tends to occur earlier in the H1 candle, followed by price moving against the previous side as the old side loses relative impact and the new side grows more effective. Snapshot L50 sometimes supports that turn. No fixed retracement percent, new indicator, tiers, scores, or code changes were introduced. Existing inputs still overlap markedly between terminal and nonterminal candidates; ideal detection is not proven. The user-requested H1-close timing has now been tested correctly.

Complete details and replay code generated as H1_CLOSE_12_DAY_AUDIT_2026-11-11.md and H1_CLOSE_12_DAY_REPLAY_2026-11-11.zip in this conversation.