# HYPE D250 cost-aware stop-risk gate — 2026-11-23 05:28 CET
Research only. Frozen D250 thresholds unchanged. No live orders, no production changes, no detector retraining.

## New executable artifact
`research/hype_terminal_local_strategy/d250_cost_aware_risk_gate.py`.
Explicitly parameterized LONG/SHORT entry/stop, entry+exit fees, entry+stop slippage, adverse stop gap, maintenance margin buffer, equity, free margin, leverage cap and existing concurrent stop-risk. Hard reject for wrong-side stop, risk >0.5% per trade, aggregate risk >1%, or stop beyond approximate leverage/liquidation buffer. Caps notional by both stop-risk budget and available margin; returns modeled maximum loss and margin. No invented fee or gap constants in the production function.

## Deterministic illustration only — not observed exchange data
$100 equity, 0.5% risk, LONG 100/99 stop, entry+exit fees 0.06% each, slippage 0.03%+0.05%, gap allowance 0.20%, maintenance buffer 0.50%, max leverage 5x:
- adverse stop distance 1.00%; explicit cost+gap allowance 0.40%; total modeled loss/notional 1.40%;
- risk budget $0.50; max notional $35.7143, margin $7.1429 at 5x;
- SHORT 100/101 is symmetric under identical scenario assumptions;
- with already reserved 0.8% equity stop risk, new trade is limited to 0.2% equity ($0.20), not 0.5%.
These values are illustrative and must NOT be reported as Bybit fills or historical PnL. Stop market gaps can exceed assumed allowances. Approximate leverage buffer is not a Bybit liquidation calculation.

## Self-test status
Five deterministic assertions are included in the script. Execution in CI or a local runner is NOT confirmed in this checkpoint. Run:
`python research/hype_terminal_local_strategy/d250_cost_aware_risk_gate.py --self-test`

## Replay blockers / next concrete step
Read immutable 71 accepted signal IDs and actual UTC extremes/K2 timestamps from preserved artifacts; require real bid/ask/mark and historical L50 depth where available. Build time-aligned replay for all 71, preserving four censored paths. Fee tier, funding, stop trigger basis, slippage, gaps, and maintenance margin must be observed or explicitly scenario-stressed, never inferred from candles. Compare baseline and risk-limited variants on identical chronology, accounting for capital overlap and open-position MTM. Report monthly equity and drawdown only after event-matched replay. Previously rejected fixed ATR trail/MFI+flow exits remain rejected.

## Evidence boundary
This iteration adds a reproducible sizing component and numeric deterministic scenario, not matched Bybit execution replay or independent forward validation. No new performance, MFE or liquidation claims.
