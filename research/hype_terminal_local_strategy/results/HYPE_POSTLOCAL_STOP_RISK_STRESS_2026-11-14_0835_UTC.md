# HYPE post-local stop-risk stress checkpoint — 2026-11-14 08:35 UTC

Research only; no orders, no detector training, no new thresholds. Inputs verified directly against frozen `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`, `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`, and `trade_manifest_gate_research.py` on this branch.

## New deterministic calculation
A 1% adverse-price stop and a diagnostic structural stop with **median 3.14% entry-to-stop distance** are different exit geometries. At $100 equity, 0.15% round-trip notional cost and stress gap 1.0%, maximum notional for 0.5% equity risk:
- 1% cut: $23.2558, exposure 0.232558x.
- 3.14% structural distance: $11.6550, exposure 0.116550x.
At 0.25% risk these notionals halve. Formula: notional = equity × target risk / (stop distance + fees + gap). These are planning stress scenarios, NOT verified Bybit slippage bounds or guaranteed worst-case loss. Funding, spread, liquidation maintenance margin and partial fills need explicit trade-level inputs.

For the 1% stop at 0.5% equity risk, gap stress of 0%, 0.5%, 1%, 2.5% permits respectively 0.434783x, 0.303030x, 0.232558x, 0.136986x account exposure. This is materially below the previous 3x/5x fixed exposure experiments. Same stop-loss geometry does not imply the same account equity path when sizing changes.

## Audit of current manifest gate
Current `gate(row)` checks existence/truthiness of string source labels but does not establish that files exist, that a private fill was recorded, that the L50 and mark paths cover the trade, that the protective stop was active throughout the hold, or that liquidation price was safely beyond the stop. `EXECUTION_FIELDS_COMPLETE_NOT_LIQUIDATION_VERIFIED` must NOT be reported as a validated real trade. The synthetic tests use labels like `private-fill` and `mark`, not actual evidence. Reconcile each trade ID against source file hash, time interval and event IDs before advancing it to historical execution evidence.

## Research next gate
1. Export the 67 frozen entry/exit timestamps and matching raw Bybit tape artifact identifiers, without substituting aggregate results.
2. Preserve original 67-trade baseline, then replay LONG and SHORT with identical sample/cost/funding assumptions, causal timestamps and risk-based notional.
3. Mark missing historical L50/mark/sequence as unavailable; never fill from future data.
4. Measure monthly net equity, open-position MTM DD, closed DD, stop gaps, liquidation distance, MFE retained/given back, and independent untouched forward. No historical performance claim until this is done.

Existing rejected flow/MFE, K0/K1, ATR trailing and pyramiding overlays remain rejected. Frozen D250 rule unchanged.
