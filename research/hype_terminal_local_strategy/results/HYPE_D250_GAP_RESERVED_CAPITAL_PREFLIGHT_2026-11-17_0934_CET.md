# HYPE D250 execution preflight: conservative gap reserve and capital overlap — 2026-11-17 09:34 CET

Research only. Frozen D250, no detector training, no production edits, no real orders.

## Sources read in this exact branch
- `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`: frozen D250; 67 finalized opposite-local episodes; median structural stop distance 3.140%; causal opposite-local median MFE giveback 61.2%.
- `results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`: original 1% adverse cut; 67 sequential simulated trades; 22 fixed-cut exits; 0.15% round-trip notional cost; 5x original exposure.
- `d250_trade_replay_manifest_gate.py`: current manifest checks coverage assertions, not exchange tape; same-timestamp signal/entry remains allowed.
- `research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md`: price-impact efficiency/control transfer, not raw opposite flow.

## New executable local preflight and tests
Implemented `d250_execution_preflight.py` and `test_d250_execution_preflight.py` in the run workspace, **not yet uploaded to GitHub**. The preflight parses a per-trade CSV and fail-closes on side/local mismatch, missing or non-UTC timestamps, signal >= entry, exit <= entry, invalid stop geometry, 1% frozen-cut mismatch, wider-than-1% purported closer structural stop, duplicate IDs, and overlapping capital intervals. It computes risk-based exposure with a separately disclosed gap reserve; it does not infer fills or PnL. Ran seven synthetic unit tests locally: **7 passed / 0 failed** (LONG, SHORT, risk sizing, same-time signal/entry, invalid stop, overlapping capital, duplicate IDs). No real 67-trade manifest was supplied to this test.

## New cost-aware risk envelope (scenario, not observed slippage)
Assume fixed 1% stop, published round-trip 0.15% of notional, and *additional hypothetical* 0.50% adverse stop-gap reserve. Risk denominator = 0.01 + 0.0015 + 0.005 = **1.65% of notional**. Then max notional/equity = equity-risk-budget / 0.0165:
- 0.25% equity risk => **0.151515x** notional/equity, **0.606061%** margin/equity at 25x instrument leverage.
- 0.50% equity risk => **0.303030x** notional/equity, **1.212121%** margin/equity at 25x.
- At 1.00% total simultaneous stop-risk, maximum combined exposure is **0.606061x** under identical assumptions, provided overlapping trades are explicitly budgeted together.
- For the *diagnostic* 3.14% structural stop, denominator becomes 3.79%, giving **0.065963x** and **0.131926x** notional/equity for 0.25% and 0.50% risk respectively. This is diagnostic only: the published frozen 1% cut remains unchanged.

The reserve is **not a bound on market gaps**; a worse stop fill can exceed the risk budget. 25x isolated liquidation safety requires independently observed mark-price path, exchange maintenance margin tier and position parameters.

## Material replay blocker
The repository reports 67 aggregated sequential simulated trades but the trade-by-trade UTC manifest and matched executable bid/ask, Public Trades, mark price and L50 tape were **not recovered** in this run. No 67-trade replay, monthly net equity, MTM DD, realized stop fill count, liquidation count, or MFE captured can be validated. Do not infer these values from aggregates.

## Next required run
Recover the original 67 individual trade IDs and UTC entry/exit/stop timestamps, then execute the fail-closed preflight on the actual rows, identify overlapping intervals, attach real source paths/hashes/coverage, and replay frozen original and conservative variants with identical tape/cost/funding assumptions. Rejected MFE overlays remain rejected until independent forward evidence.

This checkpoint adds tested deterministic trade-level preflight logic and an explicit gap-aware sizing envelope, **not** a claim of improved historical profitability.
