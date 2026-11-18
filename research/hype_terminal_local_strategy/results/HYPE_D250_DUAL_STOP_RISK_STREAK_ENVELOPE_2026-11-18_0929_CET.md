# D250 stop-distance / six-loss-streak risk envelope — 2026-11-18 09:29 CET

Research only. New deterministic scenario computation, NOT a matched historical replay. Frozen D250 and historical baseline unchanged.

## Source
Read on target branch: H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md and HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md and prior risk reconciliation. The frozen report states median structural stop distance 3.140% from entry, versus the separate 1.00% adverse cut, and maximum historical loss streak 6. These are **different** stop regimes, not interchangeable.

## Exact model
Account notional/equity = target_equity_risk / (stop_price_distance + 0.0015 assumed round-trip notional fees + adverse_gap). Initial margin/equity at 25x instrument leverage = notional/equity / 25. The gap is an explicit stress scenario, not a historical estimate. For six consecutive fully filled stop losses with exact recalculation each trade: drawdown = 1-(1-target_equity_risk)^6. No funding, variable taker fees, mark/last basis, or nonlinear orderbook impact modeled. This is not a liquidation simulation.

| Stop model | Additional adverse gap | Loss/notional | Max notional/equity at 0.25% risk | Max notional/equity at 0.50% risk | Margin/equity at 25x for 0.50% risk |
|---|---:|---:|---:|---:|---:|
| 1% cut | 0.00% | 1.15% | 0.2174x | 0.4348x | 1.739% |
| 1% cut | 0.50% | 1.65% | 0.1515x | 0.3030x | 1.212% |
| 1% cut | 2.00% | 3.15% | 0.0794x | 0.1587x | 0.635% |
| 3.14% median structural | 0.00% | 3.29% | 0.0760x | 0.1520x | 0.608% |
| 3.14% median structural | 0.50% | 3.79% | 0.0660x | 0.1319x | 0.528% |
| 3.14% median structural | 2.00% | 5.29% | 0.0473x | 0.0945x | 0.378% |

Six stop losses in sequence: 0.25% target risk -> 1.491% compounded closed-equity drawdown; 0.50% target risk -> 2.963%. This only holds if actual fills never exceed the budget; it is NOT a bound under gaps.

## Newly identified comparability issue
A risk-budgeted replay must separately model the 1% early adverse cut and the much wider structural stop. It must not size from the 1% stop while allowing the 3.14% structural stop to remain the operative exit: at 0.50% risk sizing for a 1% cut plus 0.5% gap (0.3030x), a 3.14% structural stop plus the same 0.5% gap and 0.15% fees would instead cost 1.148% of equity, above the intended 0.50% risk. If both stops are active, verify exchange-side precedence and mark-trigger mechanics, not just theoretical stop prices.

## Replay evidence status
No individual UTC ledger, orderbook-matched stop fill, per-month equity curve, liquidation-distance, or forward execution evidence reconstructed here. No historical profit or observed liquidation claims. Frozen detector and rejected exit overlays remain unchanged. No live orders.
