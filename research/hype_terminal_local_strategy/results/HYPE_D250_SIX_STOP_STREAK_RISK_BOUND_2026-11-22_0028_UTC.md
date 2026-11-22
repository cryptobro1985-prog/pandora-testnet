# HYPE D250 — six consecutive stop losses: account-risk boundary (2026-11-22 00:28 UTC)

Research only. Frozen entry D250 and original 67-trade simulation unchanged. No orders, detector training, or production changes.

## Source checked in target branch
- `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`: 67 sequential simulated trades, maximum loss streak **6**, 1% adverse price cut, round-trip cost assumption 0.15% notional, 3x/5x account exposure, 18.56%/29.36% closed DD; not tick-execution or MTM validated.
- `HYPE_D250_STOP_GAP_EXPOSURE_STRESS_2026-11-22.md`: additional adverse stop gap stress at 0, 0.5%, 1%, 2%.
- `d250_conservative_stop_risk_sizer_20261121.py`: risk budget applies to modeled stop-loss including assumed gap/cost, not a guaranteed maximum. The sizing function does not itself check live margin state, mark/liquidation freshness, exchange lot-size/min-notional, or enforce the separate clearance gate.

## New reproducible calculation
Let `L = exposure_x * (0.01 + 0.0015 + gap)` be the equity loss per stopped trade, ignoring funding and nonlinear liquidation. Six sequential equal-percentage losses leave `E6/E0 = (1-L)^6`; this is a stress thought experiment, NOT an observed six-trade fill sequence.

| Exposure / risk setting | Extra gap | Per-stop equity loss | Equity after 6 stops from $100 | Six-stop DD |
|---|---:|---:|---:|---:|
| Historical 3x exposure | 0% | 3.45% | $81.00 | 19.00% |
| Historical 5x exposure | 0% | 5.75% | $70.06 | 29.94% |
| Historical 3x exposure | 2% | 9.45% | $55.10 | 44.90% |
| Historical 5x exposure | 2% | 15.75% | $35.73 | 64.27% |
| Risk-sized 0.25% per stop | Assumed gap already budgeted | 0.25% | $98.51 | 1.49% |
| Risk-sized 0.50% per stop | Assumed gap already budgeted | 0.50% | $97.04 | 2.96% |

The final two rows assume actual total stop loss equals the risk budget; a larger-than-reserved gap breaks this bound. Portfolio-wide 1% aggregate stop risk is a separate constraint; simultaneous correlated gaps can exceed it.

## Implementation issue identified
`d250_conservative_stop_risk_sizer_20261121.py` returns `SIZED` based on a supplied liquidation_price and a simple stop-vs-liquidation check. The independently created `d250_liquidation_clearance_research_gate_20261121.py` is NOT invoked by that sizing function. Consequently `SIZED` must not be interpreted as a validated executable order. Require the separate fail-closed clearance check, current Bybit instrument filters, account margin/mark state, min quantity and notional, and portfolio reservations before considering any execution simulation.

## Replay gate
Only claim improved risk-adjusted net returns after matching the original UTC 67-trade manifest and actual M1/public-trades/L50/mark/funding events. Keep original fills/costs/sample and chronological capital usage identical across baseline and risk-sized variants. Distinguish LOW->LONG from HIGH->SHORT, record stop gaps, mark-to-market DD, fill quality, and unseen-forward outcomes. Previously rejected MFE overlays remain rejected.

## Status
New: six-loss streak sensitivity and concrete unintegrated risk-gate finding. Not verified: actual 67-trade event replay, observed fills, liquidations, monthly net equity, MFE retention, or independent forward.
