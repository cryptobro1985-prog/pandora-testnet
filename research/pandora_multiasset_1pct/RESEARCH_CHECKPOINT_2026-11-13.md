# Pandora Multi-Asset 1%/day — research checkpoint
Date: 2026-11-13
Branch: research/pandora-multiasset-1pct-20261113
Status: RESEARCH_ONLY; REAL_ORDERS_OFF
Goal: search for robust net portfolio returns around 1%/day with bounded risk. This is a hypothesis/target, not a guaranteed result.

## Fixed universe
ZEC, HYPE, NEAR, SOL, ENA, 1000PEPE, DOGE, SUI, AAVE, WLD (USDT linear perpetual).
Evidence: research/caterpillar/README.md and pandora_scanner.py.

## Verified project inventory
- research/caterpillar provides a causal H1-local / public trade flow PAPER engine with independent directional hypotheses, exit/re-entry research, per-token MFE/MAE, checkpoint and report logic.
- research/caterpillar/VALIDATION.md documents 106 passing tests including synthetic fixtures, **not** a validated real-market result.
- research/caterpillar/AUDIT_V2.md explicitly states real 30–60 day archive run and 6-hour Bybit OOS were not completed in the implementation task.
- research/hype_all_in_one/MANIFEST.json documents the HYPE-only 116-field canonical contract (86 causal/quality inputs, 28 target/eval, 2 metadata). Do not assert all 116 exist for all 10 symbols.
- GitHub Actions data/artifact access, coverage, time alignment, and source provenance must be audited per symbol before using microstructure claims.

## Exploratory result from chat session (NOT a reproducible saved run)
Data source: Binance Futures HYPEUSDT and ten-token 1h candles, downloaded through market-data connector. Ten assets each yielded 1,200 aligned 1h bars for 2026-09-23 01:00 UTC to 2026-11-12 00:00 UTC. A separate quick scan of 18 naive one-position portfolio momentum/breakout/ATR configurations used a chronological 70/30 split. Provisional configuration (12h range breakout, preceding 24h move >=3%, trail 3.5 ATR, risk <=0.4% at stop, notional <=10% equity, assumed 0.16% roundtrip notional costs) showed +4.82% discovery and +0.57% held-out portion. This does NOT establish ~1%/day; reproducibility, fills, costs, liquidity, funding, open-position accounting, and daily PnL calculations need independent audit. Do not promote based on this checkpoint.

## Priority research tasks
1. Inventory available Bybit historical publicTrade, OHLCV, book L50/L1, OI, funding, mark and liquidation data per symbol/date, including missingness and event/receive timestamps. Never impute missing as zero.
2. Preserve event-time causal ordering. Use H1 structural inputs only after hour close, M15 entry signals only after bar close, and actual next-available bid/ask execution with latency/slippage/funding fees.
3. Compare trend continuation, local-reversal and correction/re-entry families without retroactive indicator repainting. HYPE-specific learned models require a separate transfer/generalization test before application elsewhere.
4. Reconstruct a **shared portfolio equity curve** and position overlap, not per-token separately compounding simulated balances; respect time and cross-asset correlations.
5. Predeclare chronological walk-forward folds including purge/embargo for overlaps; freeze parameters before fresh forward, and track multiple-hypothesis testing / selection bias.
6. Search exposure using conservative starting constraints: position risk 0.25% equity; total outstanding stop-risk <=0.75%; portfolio daily loss cutoff 1%; leverage 1–2x maximum exploratory; no trading if execution/liquidation/freshness checks fail. These are research parameters, NOT optimal settings or guarantees.
7. Optimize for net geometric growth **subject to** drawdown, worst day, PnL stability, liquidity and coverage. Report count and fraction of >=1% net daily returns as outcome, but never mathematically enforce guaranteed green days.
8. Produce table per token and time fold: bars/trades coverage, number of signals/fills, net expectancy and costs, max drawdown, losing streak, slippage sensitivity, MFE capture/giveback, fraction of profitable days, 1%-days, and confidence bounds.
9. Reject overfit. Do not automatically raise leverage to force 1% returns. Protect capital and leave real orders OFF.
10. Save each new result as an auditable file under research/pandora_multiasset_1pct/ and use separate pull request for code changes.

## Explicitly unfinished
No validated multi-year OOS / live forward result; no verified 1%-per-calendar-day system. Current checkpoint is an evidence inventory and design for the next reproducible experiment, not a completed research result.
