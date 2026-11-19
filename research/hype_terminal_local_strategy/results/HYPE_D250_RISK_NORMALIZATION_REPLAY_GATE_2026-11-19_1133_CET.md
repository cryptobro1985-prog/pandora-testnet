# HYPE D250 risk-normalization and event-replay gate — 2026-11-19 11:33 CET
Research only; no orders, production modifications, threshold changes, or detector training.

## Inputs verified directly on target branch
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md: frozen D250 rev_atr > 2.0840049433824706, trade_ratio5 > 0.2727842248141979, flow15 < 0.4504731635235635; 71/71 historical accepted first signals, 50/50 OOS; 67 opposite-local finalized entries, median 61.2% causal-exit MFE giveback. This is signal classification, not verified executable fills.
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md: 67 sequential modeled trades; 1% adverse-price cut; 0.15% round-trip assumed fee; 3x account exposure closed DD 18.56%, 5x closed DD 29.36%. Neither is a risk-capped 0.5%-per-trade strategy.
- quote_event_stop_replay_research.py at blob da025cee026e7dc43b93827d05bb317668dc8416: risk sizing uses risk_fraction/(stop_pct+roundtrip_cost_fraction), quote-side stop and opposite-local flag; no L50 fill verification, liquidation simulation, funding, mark-to-market equity or matched historical event manifest.

## New quantitative comparison (arithmetic evaluated this run)
Equity $100, entry VWAP $100, adverse stop 1%, assumed round-trip cost 0.15% of entry notional, target risk 0.5% equity. Notional = $0.50/(0.01+0.0015) = $43.47826087; quantity = 0.4347826087.
- LONG stop bid $99: net -$0.500000 (0.5000% equity).
- LONG stop gap bid $97: net -$1.369565 (1.3696% equity).
- SHORT stop ask $101: net -$0.500000 (0.5000% equity).
- SHORT stop gap ask $103: net -$1.369565 (1.3696% equity).
- With a 3.14% structural stop and the same 0.15% cost, risk-normalized notional is $15.19756839, NOT $43.48.
- Historical 3x/5x account exposure at the assumed 1% stop + 0.15% costs corresponds to nominal planned loss 3.45%/5.75% equity respectively, 6.9x/11.5x the new 0.5% risk target. Thus the reported $531.16 or $1,308.86 terminal equity cannot be carried over as a result for conservative sizing. This is not a new historical backtest.

## Concrete replay gate
For each of the 67 candidate trade events, require entry decision UTC and observable information timestamp; actual next quote and executable bid/ask; quantity and fill depth across L50; funding time and actual funding; mark-price trajectory and maintenance/liquidation rules; ordered stop and opposite-confirmation events; independent chronological unseen segment. Missing fields => unresolved, never zero-imputed. Preserve side-specific LOW->LONG and HIGH->SHORT reports, original baseline untouched and identical fees/capital occupancy for every challenger. Compute monthly net equity, intratrade MTM DD, closed DD, stop gap, liquidation count, MFE and MAE only for sufficiently observed trades. No causal control-transfer exit promotion until truly unseen evidence improves on the frozen baseline.

## Findings / verdict
The current quote replay can be tested for arithmetic, but is not a matched per-trade Bybit execution replay. No new historical fill, monthly PnL, MTM DD, or liquidation result is claimed. Important next engineering priority is matching 67 entry UTC IDs to actual archived quote/L50/mark/funding records, not adding another synthetic risk overlay. Existing rejected MFE overlays remain rejected.
