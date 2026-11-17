# D250 frozen 67-trade aggregate cost sensitivity — 2026-11-17 19:26 CET

Research only; NOT a trade-level execution replay. Original frozen entry and 1% adverse cut unchanged. Source: HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md and H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md in this branch.

## New arithmetic check
67 completed trades, 49.25% winners = 33 winners and 34 non-winners (33/67=49.2537%). Published 5x mean winning equity return +14.16%; mean losing -4.37%. Using rounded reported group means:
- Approximate arithmetic mean equity return per trade: (33*14.16 - 34*4.37)/67 = 4.7567% (NOT compound and NOT independently verified).
- Implied break-even win fraction for unchanged conditional average payoffs: 4.37/(14.16+4.37) = 23.583%. This is a descriptive algebraic identity, not a forward probability.
- Extra round-trip execution friction of 0.25% notional at 5x exposure reduces arithmetic mean by 1.25 percentage points to 3.5067% per trade, **only if** the same trades/fills/outcomes remain unchanged.
- Extra 0.50% notional reduces arithmetic mean by 2.50 points to 2.2567%. In practice changed fills, stops and path-dependent compounding invalidate this as a net performance forecast.

## Critical consistency and evidence gates
- 71 accepted true-first D250 episodes vs 67 finalized next-opposite-local trade episodes: 4 episodes have no finalized opposite-local trade in the cited audit. Do not treat them as winners or silently discard them from live-forward scoring.
- D250 71/71 is classification precision among selected historical candidates, not 71 executable profitable trades.
- Original 1% adverse-price stop plus assumed 0.15% round-trip notional fees implies ~1.15% price-equivalent loss before any gap/slippage/funding, if executed at threshold; stop cannot be treated as hard realized-loss cap.
- Reported 5x 29.36% drawdown is CLOSED equity only; MTM DD, liquidation proximity, actual fills and monthly net cannot be inferred from these aggregates.
- Causal opposite-local exit median MFE giveback 61.2%; previously rejected flow/trail/K0/K1 overlays remain rejected.

## Replay priority
Locate individual UTC records for all 71 accepted signals, identify 67 finalized and 4 censored, and reconstruct fills on timestamped Public Trades/L50/mark-price where coverage exists. Separately calculate LOW->LONG and HIGH->SHORT, gaps, funding, stop order evidence, position sizing at 0.25-0.5% equity risk and portfolio 1% stop-risk. Run identical sample and costs for unchanged baseline and conservative alternatives. No future opposite extreme as exit. Record missing data explicitly; no synthetic trade fills.

## Result
This iteration is an aggregate arithmetic consistency and cost sensitivity check, NOT historical matched-event replay. No new net equity, MTM DD, liquidation count, or protected MFE is asserted. No training, production changes or orders.
