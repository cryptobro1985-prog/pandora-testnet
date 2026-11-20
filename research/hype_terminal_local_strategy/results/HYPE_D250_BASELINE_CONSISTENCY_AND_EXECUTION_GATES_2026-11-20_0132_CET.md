# HYPE D250 baseline consistency and execution evidence gate — 2026-11-20 01:32 CET

Research only. No retraining, new branch, production change or orders.

## Direct source inspection
Read on the requested branch:
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md
- HYPE_D250_REPOSITORY_EXECUTION_DATA_INVENTORY_2026-11-19_2132_CET.md
- HYPE_D250_STRUCTURAL_STOP_SIZING_SENSITIVITY_2026-11-20_0030_CET.md
- HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md

## New audit: baseline reporting consistency
The 2026-11-12 asymmetric report explicitly says:
- 3x exposure: $100 -> $531.16, closed-equity DD 18.56%.
- 4x exposure: $100 -> $848.72, closed-equity DD 24.11%.
- 5x exposure: $100 -> $1,308.86, closed-equity DD 29.36%.
- 5x intermediate equity checkpoints: sealed May $471.51; Jul12-Aug07 $755.20; Aug08-Sep01 $583.32; Sep01-Oct01 $1,037.06; Oct04-Nov03 $1,308.86.
Thus $531.16 is the **3x** final balance, NOT the 5x balance; do not conflate the two. Period checkpoints are for 5x only. The May-first ordering in the summary is a reporting order and cannot be used as a chronological equity ledger without individual timestamps.

22/67 = 32.8358% of completed simulated trades hit the fixed-cut branch. 49.25% profitable closed trades corresponds approximately to 33/67; these are NOT the 67/67 oracle-positive gross-to-extreme trajectories or 67.16% opposite-K2 wins. The reports do not establish overlap between 22 stop-outs and the 33 net winners, so do not infer a stop-conditioned win rate.

## New audit: risk budget arithmetic and execution gap
At a $100 equity account, 1% adverse-price cut and 0.15% assumed round-trip notional fees (no gap/funding), max nominal is $21.7391 for 0.25% equity risk and $43.4783 for 0.5% equity risk. 3x exposure risks 3.45% equity and 5x risks 5.75% equity at that modeled stop, before gap/funding. The 0.25%-0.5% variants cannot inherit the 3x/5x compound returns or closed DD.

A $100 account's aggregate stop-risk limit of 1% allows at most $1 modeled loss reserved across all concurrent trades; it does not mean $1 margin or $1 notional. For each order compute size from adverse fill distance + both executed-notional fees + estimated gap/slippage + funding, then check instrument leverage, mark-price liquidation buffer and free margin separately. If reliable upper bound on stop execution gap is unavailable, flag risk as unbounded/unknown rather than claim guaranteed 0.5%.

## Causal timestamp gate
The frozen D250 report says age 250 minutes after candidate extreme, and opposite strict H1 local not yet occurred. This alone does NOT document the exact K2-availability timestamp of the original local in each trade. Require original_local_k2_available_ts <= first_trade_eligible_ts <= entry_fill_ts; if K2 is unavailable by D250, defer entry. Also require exit_signal_available_ts <= exit_order_ts <= exit_fill_ts. An opposite local's hindsight extreme timestamp is NOT the exit signal timestamp.

## Historical evidence status
The previously recorded complete Git tree inventory found no 67-row UTC bid/ask/mark/L50 tape within the inspected research directory. This run read frozen source reports, not a matched event tape. **0/67 matched executions verified in this run.** No monthly net equity, MTM DD, fill/slippage distribution, actual stop precedence, liquidation count, funding or MFE retention is newly computed. Do not interpret these arithmetic checks as historical replay.

## Replay next-step contract
Recover 67 UTC rows and source hashes from Actions artifacts/external storage, join every trade to timestamped public trades, bid/ask, mark, L50 and funding (unknown if absent). Preserve same trade IDs and time order for original 3x/5x, risk 0.25/0.5%, staged-entry and BE/profit-lock comparisons. Reject capital overlap and timestamp lookahead. Keep previously rejected profit overlays rejected unless genuinely unseen-forward evidence supports them.

## Frozen invariants
D250 thresholds: rev_atr > 2.0840049433824706, trade_ratio5 > 0.2727842248141979, side-normalized flow15 < 0.4504731635235635. LOW->LONG, HIGH->SHORT. No retuning. No live orders.
