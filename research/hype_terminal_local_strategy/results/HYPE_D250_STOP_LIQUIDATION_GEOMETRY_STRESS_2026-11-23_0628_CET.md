# D250 stop-vs-liquidation geometry stress — 2026-11-23 06:28 CET

Research-only checkpoint. No new detector training, no production changes, no real orders.

## Source verified
Read `research/hype_terminal_local_strategy/d250_cost_aware_risk_gate.py` (blob 50fa8130b7fd8f211deb7124612ddbaefca81e31) and `results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md` (blob 54865475546c10cd555199c65a2a81ce0f14aab7). The original walk-forward reports 71/71 accepted and 67 finalized causal opposite-local exits; median diagnostic structural stop 3.140% from entry and median MFE giveback 61.2%. These are not executable replay results.

## Concrete new deterministic calculation
Executed 36 synthetic scenarios: LONG and SHORT × 1.0% or 3.14% stop × 3x/5x/25x × 0.2%/1%/3% adverse stop gap. Assumptions: $100 equity, 0.5% equity risk, 0.06% entry fee, 0.06% exit fee, 0.03% entry slippage, 0.05% stop slippage, 0.5% maintenance margin approximation. Nominal stop-risk sized as $0.50 including assumed costs. 30/36 cases passed approximate stop-before-liquidation geometry; 6/36 failed, all at 25x: 3.14% stop with 1% or 3% gap, and 1% stop with 3% gap (both directions). Example: LONG entry 100, stop 99, 0.2% gap, 3x -> notional $35.7143, margin $11.9048, model loss $0.50. At 25x, approximate liquidation buffer is 3.5%, so a 3.14% stop plus 1% gap plus 0.05% stop slippage crosses that buffer.

The synthetic test initially asserted that all 25x/1%-stop cases were safe; this assertion FAILED for 3% gaps. The corrected expectation was rerun and all scenario assertions PASSED. This is a meaningful counterexample to using a fixed 25x leverage even with risk-based notional sizing.

## Critical limitation
This is not a Bybit liquidation calculation, no insurance/funding/mark-basis/tiers, and no proof that a modeled stop fills before liquidation. Realistic gaps can exceed the assumed reserves. The `d250_cost_aware_risk_gate.py` uses a simplified `1/leverage - maintenance_margin_fraction` buffer; fail-closed is appropriate until actual tier, mark, margin mode and stop execution data are available. No 71-signal UTC tape replay or monthly equity/DD was possible from these two source files alone.

## Next replay gate
Retrieve immutable 71-signal UTC cohort and matched Public Trades, L50, bid/ask, mark, OI, liquidation and funding data with source hashes. Preserve unchanged baseline, chronological train/OOS, original entry timing and independent forward. Reject any trade lacking executable quote/mark or verified liquidation tier. Compare 0.25% and 0.5% equity stop-risk with 1% total stop-risk cap, separately for LOW/LONG and HIGH/SHORT, and account for overlapping capital. Do not promote MFE overlays without independent evidence.
