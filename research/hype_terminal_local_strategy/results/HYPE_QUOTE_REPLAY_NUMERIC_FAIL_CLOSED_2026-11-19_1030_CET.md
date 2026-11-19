# HYPE quote-event replay — numeric fail-closed audit (2026-11-19 10:30 CET)

Scope: research-only, existing frozen D250 post-local entry. No retraining, no production, no orders.

## Concrete newly audited failure

Read the actual research module `quote_event_stop_replay_research.py` on the specified branch. Its original preflight check compared `risk_fraction`, `equity` and `entry_vwap` without testing finiteness, and did not constrain `roundtrip_cost_fraction`. A negative fee reserve could produce a larger-than-budget notional, or even negative notional when `stop_pct + roundtrip_cost_fraction < 0`. A NaN entry price could propagate to stop, notional, PnL and MFE. This invalidates even a hypothetical top-of-book replay.

## Repair committed

Before sizing, reject NaN/Infinity for risk fraction, equity, entry VWAP and round-trip cost. Require `0 <= roundtrip_cost_fraction < 1`. Existing 0 < risk <= 0.005, equity > 0 and entry > 0 checks remain. Six deterministic rejection cases were added to the module self-test (NaN entry, infinite equity, NaN risk, negative cost, NaN cost, cost >= 1). Existing four scenarios remain.

## Deterministic numeric illustration

With equity 100, risk 0.005, stop 0.01, entry 100 and valid round-trip cost 0.0015: nominal = 100*0.005/(0.01+0.0015) = 43.47826087 USD; quantity = 0.4347826087 HYPE. An invalid cost -0.02 previously implied nominal -50 USD. This is a pure input-validation example, not a historical trade.

## Execution status and remaining blockers

GitHub source was read and patched via the connected GitHub repository interface. Attempted to retrieve the updated module in the local Python runtime from raw.githubusercontent.com, but DNS resolution failed. Therefore the ten self-test assertions have **not** been executed in this runtime; do not claim passing tests. No per-trade historical replay or validated fill results were produced.

A correct replay must additionally validate chronological UTC event alignment, entry fill VWAP, bid/ask and L50 depth, mark-to-liquidation buffer, funding timing, and unique capital allocation; calculate MFE only through actual exit time; preserve rejected profit-lock overlays unless independent forward evidence improves them. The frozen entry rule and the 67-trade baseline were not modified.

## Research verdict

Numerical input corruption is now rejected at the research replay entry point. This removes one avenue for spurious nominal sizing, but does not establish positive net returns, live fills, no liquidation or improved MFE. Next priority is execute tests in GitHub Actions or another environment with the branch available, then join the 67 UTC trades to executable quote/depth events and compare unchanged baseline with 0.25%-0.5% equity stop-risk under identical costs.
