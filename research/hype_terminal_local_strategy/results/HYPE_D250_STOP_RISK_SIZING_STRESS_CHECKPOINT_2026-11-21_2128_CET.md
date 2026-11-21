# HYPE D250 conservative stop-risk sizing — 2026-11-21 21:28 CET

## Scope and source audit
Read the current branch's `d250_raw_m1_preentry_gate_20261121.py`, previous anchor-minute remediation checkpoint, and `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`. No detector training, threshold changes, live orders or production modifications. Existing 67-trade results remain closed-equity model results, **not** real Bybit execution replay.

## New executable artifact
`research/hype_terminal_local_strategy/d250_conservative_stop_risk_sizer_20261121.py` contains a symmetric LONG/SHORT, fail-closed risk-sizing function and six synthetic unittest scenarios. Run: `python research/hype_terminal_local_strategy/d250_conservative_stop_risk_sizer_20261121.py`. CI and actual test execution are **not verified** in this checkpoint.

### Frozen strategy vs new risk sizing
Do not alter D250 entry conditions or existing baseline. For each candidate, compute stop distance d = |entry-stop|/entry, total stressed fractional notional loss L = d + assumed round-trip costs + assumed adverse stop gap. Allowed notional = min(equity * min(per-trade risk, 1% - preexisting aggregate stop risk)/L, equity * allowed margin fraction * instrument leverage). Reject if stressed stop crossing would reach or pass sourced liquidation price; reject missing/NaN values.

Illustrative **not market-derived** stress: $100 equity, 1% stop, 0.15% round-trip costs, 2% adverse stop gap, 0.5% equity stop-risk budget, no concurrent risk, 25x instrument leverage, 20% margin cap, liquidation 5% adverse. L=3.15% of notional; notional=$15.87301587, exposure 0.15873016x, initial margin $0.63492063, stressed modeled loss $0.50. At 0.25% budget: notional $7.93650794, exposure 0.07936508x, modeled stressed loss $0.25. At existing 0.9% aggregate stop risk and 0.5% requested: remaining 0.1% equity budget, notional $3.17460317 and stressed loss $0.10. These are algebraic scenarios only, not execution forecasts. The 2% gap is a stress assumption, not an empirical upper bound; tail gaps can be larger.

### Critical interpretation
This does **not** prove zero liquidations: liquidation is account-/margin-mode-/maintenance-tier-/mark-price-dependent; a supplied liquidation price is mandatory and must be authenticated. Risk budget is based on stressed stop loss including costs, not nominal leverage alone. Source D250's 71/71 historical selectivity cannot be converted into win-rate or safety of new sizing. Existing rejected MFE overlays remain rejected.

## Blockers to required trade-matched replay
No original 67-row UTC manifest or authenticated matched Bybit Public Trades/L50/OI/liquidations/funding/mark-price tapes were established in this iteration. No monthly net equity, MTM drawdown, stop fills, liquidation count, MFE capture or forward statistics are claimed. Next meaningful test: recover the exact 67 trade IDs and timestamps with provenance; run current raw M1 causality gate, then pair per-trade actual time-indexed tapes and compare frozen 3x/5x baseline against 0.25% and 0.5% sizing with identical chronology and costs. No capital reuse across overlaps.
