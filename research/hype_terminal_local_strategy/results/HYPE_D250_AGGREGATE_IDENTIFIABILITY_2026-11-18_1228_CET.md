# HYPE D250 — 67-trade aggregate identifiability and conservative sizing (2026-11-18 12:28 CET)

Research only. No detector retraining, no orders, no production changes. Frozen D250 and original baseline unchanged.

## Verified source and evidence search
Read HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md, H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md and the previous chronology checkpoint on the target branch. GitHub default-branch code-search queries `HYPE 67 trades csv`, `HYPE public_trades parquet`, `HYPE entry_timestamp` returned no results. IMPORTANT: default-branch search cannot establish absence of artifacts on this research branch, GitHub Actions or external storage. No event ledger was recovered; no exchange replay was performed.

## New algebraic consistency check
67 trades x 49.25% reported positive closed trades implies 33 wins and 34 non-wins (33/67=49.2537%), assuming all 67 are closed and no zero-return trades are classified positive.

At fixed 5x account exposure, the published mean equity returns are +14.16% per winner and -4.37% per loser. Their arithmetic weighted expectancy is:
(33*14.16 - 34*4.37)/67 = 4.7573% equity per trade.
Gross sum of reported equity returns = 318.74% of an initial-unit equity; this is NOT compounded PnL. The reported $100->$1308.86 is a sequential compounded figure and cannot be independently recomputed from group averages. Means are rounded and conceal trade order, tail outcomes and time exposure.

Approximate win/loss payoff ratio = 14.16/4.37 = 3.2403; approximate break-even win fraction = 4.37/(14.16+4.37)=23.58%. These descriptive quantities are NOT forward estimates; they derive from the same selected historical sample and do not validate fills.

## Same stop, conservative risk sensitivity (NOT replay)
At 1% adverse-price cut, assumed 0.15% round-trip fee and 0.50% additional adverse execution, total modeled loss fraction per unit notional is 1.65%. A risk budget of 0.25%-0.50% equity gives maximum notional/equity 0.1515x-0.3030x. At $100 this is $15.15-$30.30, subject to venue min notional and leverage/margin constraints. For a 1% portfolio total stop-risk budget, cap combined open exposure to 0.6061x only if every open position has the same modeled 1.65% loss/notional; heterogeneous stops require summing individual stop risks. Actual gap losses may exceed the budget.

The 5x historical baseline with 1% stop and 0.15% cost has a modeled -5.75% equity loss per fully stopped trade before any extra adverse execution, incompatible with a 0.5% per-trade risk mandate. A rescaled *theoretical* arithmetic expectancy is not a net forward result; funding, fixed minimums, slippage, liquidity and nonlinearity prevent reliable linear extrapolation.

## Causal replay acceptance contract
For each LOW->LONG or HIGH->SHORT: record local extreme UTC, confirmation UTC, D250 decision UTC, source timestamps, same-side invalidation, opposite-local availability, signal side, order send and fill UTC, executable bid/ask and L50 depth, mark/last stop trigger, actual stop fill or causal opposite-local exit, funding, tiered maintenance margin and account equity before/after. Include stop gaps and intratrade MTM. Without matched trades/events, monthly net equity, MTM DD, fill count, liquidation count and captured MFE remain NOT VERIFIED.

## Research decision
Do not promote profit-lock overlays (previously rejected), do not call May prospective forward, do not infer zero liquidation from the aggregates. Next iteration must retrieve a concrete branch/Actions artifact containing per-trade UTC rows and matched event data, or report the exact storage gap rather than fabricate replay.
