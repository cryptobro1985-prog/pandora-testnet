# D250 execution policy checkpoint — 2026-11-22 03:30 UTC

Research-only; same branch, no detector retraining, no orders, no production changes.

## New code change
Added `d250_execution_policy_wrapper_20261122.py` above the unchanged combined risk gate. Prior audit demonstrated caller-controlled leverage and margin policy. The wrapper rejects candidate leverage above 25x, margin fraction above 20%, absent or mismatched actual account leverage, non-positive/nonfinite lot/minimum inputs, and any quantity that would require rounding UP to reach minimum order size. Quantity is rounded DOWN with decimal arithmetic. After rounding, the stress loss is checked against the remaining equity stop-risk budget (per-trade <=0.5%, aggregate <=1%). Successful outputs remain `RESEARCH_CANDIDATE_ONLY`, never execution authorization.

## Deterministic boundary calculations (not Bybit fills)
At equity $100, entry $100, stop $99, 0.15% cost, 2% adverse gap, 0.5% risk: raw nominal cap $15.87301587 and raw quantity 0.1587301587 HYPE. With illustrative step 0.01 HYPE, quantity rounds DOWN to 0.15, nominal $15, modeled stressed loss $0.4725. If illustrative minimum notional is $20, candidate is BLOCKED, not rounded up. With step 0.001 HYPE, quantity 0.158, nominal $15.8 and modeled loss $0.4977. These are hypothetical instrument limits; live historical exchange filters have NOT been sourced.

## Remaining limitations / replay gate
The wrapper still relies on authenticated but caller-supplied mark/liquidation/account state; it does not verify Bybit account state, timestamped instrument filters, funding, fill queue or stop slippage. The 67-trade timestamped ledger and matching historical public trades/L50/mark streams remain unproven in this branch. No new historical replay, forward returns, monthly net equity, MTM DD, MFE capture or liquidation claims. Do not alter frozen D250 thresholds or previously rejected protection overlays. Next iteration must prioritize locating the exact 67-entry UTC ledger and matched execution data; if absent, report coverage explicitly rather than substituting another strategy's CSV.
