# HYPE portfolio stop-risk guard — 2026-11-14 09:32 UTC

Research only. No production changes, no live orders. Frozen D250 remains unchanged.

## Actual new work
Read the preserved frozen D250 walk-forward, 67-trade asymmetric stop audit, unified entry/MFE contract and current manifest gate from this branch. Added executable research-only `portfolio_stop_risk_guard_20261114.py` to enforce side-correct stop geometry, risk per trade, remaining portfolio stop-risk capacity, explicit round-trip cost and assumed adverse gap. It refuses invalid/missing numbers, nonfinite values, wrong-side stops, and full portfolio capacity. This is a **scenario guard**, not a historical execution replay.

## Reproducible calculation
Assumptions for numerical scenario ONLY: equity $100, LONG entry 100 stop 99 (or SHORT entry 100 stop 101), price-stop 1%, round-trip costs 0.15% of notional, stress adverse gap 1%, risk budget 0.5% equity, max aggregate stop risk 1% equity, max notional 1x equity. Combined modeled loss per notional 2.15%. Notional $0.50 / .0215 = $23.25581395; exposure 0.23255814x; stressed loss $0.50. With $0.80 existing modeled stop risk, available budget $0.20 and notional $9.30232558. With $1.00 existing risk, new trade is rejected. At 0.25% risk, notional $11.62790698. These are conditional arithmetic, not guarantees or actual Bybit fills.

## Source-level reconciliation
- D250 has 71/71 true-first on the preserved tested episodes, 50/50 OOS, only 22.4% coverage; neither result demonstrates an execution fill.
- Frozen 67-trade asymmetric audit: 22 fixed-cut exits, 49.25% positive closed trades, 3x closed DD 18.56%; historical stop fills and mark-to-market DD are unverified.
- Unified MFE document states sustained control transfer, not raw counter-volume; rejected tight trail and flow overlays remain rejected.
- Existing trade_manifest_gate_research.py accepts source *strings* but does not resolve paths, confirm tick completeness, private fill evidence or liquidation distance. No historical replay or monthly net equity is claimed here.

## Remaining critical path
Locate immutable 67 trade IDs/timestamps and matching actual historical Bybit public-trades/L50/mark data. Public trades are not private fills: simulate executable bid/ask with explicit assumptions, label model fills, and reject unresolvable same-ms ordering. Replay original unchanged baseline and low-risk alternatives on identical chronology and fees/funding/slippage, with stop orders, portfolio-capital ledger, mark-to-market DD and liquidation boundary. No new profit-protection overlay is promoted without independent unseen-forward evidence.

## Validation
Script contains 11 deterministic synthetic assertions. GitHub write succeeded; Python execution has not been independently observed in this run. Do not describe these assertions as executed historical tests.
