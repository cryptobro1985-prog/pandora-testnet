# HYPE frozen-entry risk sizing: gap sensitivity and six-loss sequence — 2026-11-13 20:33 CET

Research-only; no orders, detector refit, or production changes.

## Inputs verified from the existing branch
- Frozen D250 post-local rule: 71/71 accepted true, 22.4% coverage; not a 100% forward guarantee.
- Frozen 1% adverse-price cut: 67 sequential simulated trades, 22 fixed-cut exits, six consecutive losses maximum, 5x exposure closed DD 29.36%, 3x 18.56%. No tick-verified fills.
- Prior synthetic stop-bar and OHLC tests are NOT empirical execution data; no matched 67-trade tape materialized in this iteration.

## New deterministic sensitivity: risk sizing across adverse gap severity
Define total price-equivalent adverse cost c = 1% stop + extra gap + 0.15% assumed roundtrip notional fees; funding excluded. Max account notional/equity for *scenario* 0.5% equity loss is 0.005/c. Margin allocation if 25x instrument leverage is notional/25; this is **not** a liquidation-price guarantee.

| Extra adverse gap | Total cost c | Notional/equity for 0.5% risk | Isolated initial margin/equity at 25x | Loss using fixed 0.23256x notional |
|---|---|---|---|---|
| 0.0% | 1.15% | 0.43478x | 1.739% | 0.267% |
| 0.5% | 1.65% | 0.30303x | 1.212% | 0.384% |
| 1.0% | 2.15% | 0.23256x | 0.930% | 0.500% |
| 2.0% | 3.15% | 0.15873x | 0.635% | 0.733% |
| 3.0% | 4.15% | 0.12048x | 0.482% | 0.965% |

## New risk interpretation
The 0.23256x account notional from the prior 1% gap case **does not** maintain a 0.5% risk budget if the gap grows. At a 3% extra adverse gap, the same fixed notional loses 0.965% of equity before funding, nearly twice the nominal budget. Sizing at a 3% gap instead limits *that scenario* to 0.5% but still cannot cap arbitrarily large jumps.

With six consecutive 0.5% equity losses, compounded loss = 2.963% of starting equity; at six consecutive 1.0% losses = 5.852%. These are mathematical loss-sequence scenarios, not replayed historical equity. The six-loss count is observed in the frozen 67-trade *simulated* baseline, not guaranteed maximum forward streak.

### Critical margin distinction
At 25x, 0.23256x notional consumes only ~0.930% of equity as initial isolated margin, but its isolated price-loss capacity is still roughly 4% of notional before maintenance, fees, funding, mark-price divergence and liquidation tiers. Smaller *account exposure* does not increase the *position-level* isolated stop-to-liquidation distance. Instrument leverage must be independently screened and Bybit actual liquidation prices logged per entry.

## Data discovery performed
Fetched the branch's existing HYPE_ASYMMETRIC_RISK_FINAL, H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD, HYPE_CAUSAL_EXIT_REPLAY_SCAFFOLD, HYPE_STOP_BAR_MFE_BOUNDS, and HYPE_EXECUTION_STOP_GAP_STRESS reports. Inspected the branch's terminal-local strategy directory and results listing: no directly consumable timestamped 67-trade event table was found there. This does not prove the event table does not exist elsewhere in the repository or workflow artifacts.

## Next evidence requirement (not completed)
Locate real 67-entry timestamps and corresponding Bybit trades/mark/L50/OI/funding partitions, replay immutable events on same chronology for unchanged 5x baseline and risk-sized challengers, report LONG/SHORT separately, monthly net, closed and MTM DD, stops/gaps, MFE, capital overlap and actual liquidation distances. Keep prior MFE overlays rejected pending truly unseen forward evidence. No live readiness claim.
