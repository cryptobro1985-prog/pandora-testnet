# HYPE D250 independent risk authorization / equity reconciliation — 2026-11-20 10:27 CET

Research only; no production orders, no detector training, no thresholds changed.

## New concrete work
Read the frozen 2026-11-12 D250 walk-forward and asymmetric-risk reports plus current `portfolio_accounting_research.py` and `portfolio_accounting_failclosed_gate_20261120.py` directly from the specified research branch. Implemented `independent_risk_reconciliation_20261120.py` to recompute notional from raw entry, stop, costs, gap and funding reserve rather than trusting `authorized_stress_loss`; reconcile each entry equity against the actual preceding closed-equity outcome; cap aggregate authorized stop risk at 1% and per-trade budget at 0.5%. Seven embedded synthetic assertions are provided; execution in GitHub Actions has NOT been verified.

## Quantitative stress geometry (illustrative, not Bybit fills)
For equity $100, 1% entry-to-stop distance, 0.15% round-trip cost reserve, 2% gap reserve, zero funding reserve, risk 0.5%: notional = 0.5/(0.01+0.0015+0.02) = $15.8730. At 0.25%: $7.9365. With already committed stop risk $0.90, the 1% portfolio ceiling leaves only $0.10, reducing notional to $3.1746. A 3.14% stop with the same reserves yields $9.4518 notional for 0.5% risk.

Important: these are loss-budget calculations, not guaranteed loss bounds under arbitrary gaps. Real stop execution can exceed reserves.

## New fail-closed distinction
The original accounting evaluator compounds `account_exposure * (gross - fees - funding)` and allows default funding=0. The previous gate checked caller-provided `entry_equity`, `authorized_notional` and `authorized_stress_loss` against one another but not against sequentially realized equity or independent stop economics. The new module specifically addresses those two internal consistency gaps. It does NOT prove data provenance, Mark Price liquidation safety, historical fills, actual funding, L50 execution, or MFE protection.

## Historical result integrity
Frozen D250: 71/71 zero observed false-first signals on tested episodes, 22.4% coverage, 50/50 OOS; these are not live fills or a guarantee. Original 67-trade 3x account exposure ended $531.16 from $100, closed DD 18.56%; 5x ended $1308.86, closed DD 29.36%. These cannot be rescaled into risk-sized returns without the original timestamped trade tape. Causal opposite-local exits gave median MFE giveback 61.2%. Prior rejected trailing/flow exits remain rejected.

## Replay status / next exact dependency
No matched per-trade Bybit Public Trades + bid/ask/L50 + Mark Price + funding tape was retrieved in this iteration. Thus zero newly verified historical fills, and no new monthly net equity, MTM DD, liquidation count or independent forward performance. Required next: individual 67 trade IDs with UTC entry/confirmation/exit timestamps, direction, entry price and stop; event provenance; Mark Price and maintenance margin; funding; book depth. Replay original and alternatives on identical chronological fills, then seal unseen forward. No live promotion.
