# HYPE post-local stop lifecycle causal audit — 2026-11-14 12:25 UTC

Research-only checkpoint. Existing branch. No detector training, threshold changes, production changes or orders.

## Sources read directly
- research/hype_terminal_local_strategy/trade_manifest_gate_research.py
- research/hype_terminal_local_strategy/causal_event_tape_guard_research.py
- research/hype_terminal_local_strategy/results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md
- research/hype_terminal_local_strategy/results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md
- research/hype_unified_entry_mfe/HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md

## New concrete defect: stop order lifecycle is not established

The manifest gate requires a nonempty `protective_stop_order_source` label but has **no protective-stop order ID, accepted/active timestamp, quantity, remaining quantity, trigger basis, cancellation/replacement timeline, or exchange rejection status**. The gate also does not establish that the stop was active before a STOP trigger or continuously active during an OPPOSITE_LOCAL hold.

### Constructive counterexample, STOP
Take the gate's own self_test base (LONG entry fill t=22, stop trigger t=30, stop fill t=31, stop price 99, actual stop fill 98.8). The row passes `EXECUTION_FIELDS_COMPLETE_NOT_LIQUIDATION_VERIFIED` with `protective_stop_order_source="order-log"`. Now suppose the stop order was actually accepted at t=35, after the alleged trigger and fill. This extra fact cannot be expressed by the manifest schema, so the gate still passes. A historical public trade crossing 99 at t=30 cannot prove that a stop not yet accepted was filled at t=31. This is a deterministic code-path counterexample, not a replay of a Bybit trade.

### Constructive counterexample, OPPOSITE_LOCAL
The self_test opposite exit holds from entry t=22 to exit t=52; `protective_stop_order_source` is merely a nonempty string. A stop canceled at t=23 and never replaced would leave the trade unprotected until t=52, yet the gate passes. This invalidates any assertion of continuously protected downside.

### Additional numerical consistency issue
At $100 entry, 1% stop = $99; stop-market execution at $98.8 is a 1.2% adverse move from entry, not a 1.0% realized stop loss. For $100 notional and $0.15 combined fees, loss is $1.35. If the same order had not been active before the crossing, the fill itself is not established at all. Public trade prints are not private execution receipts.

## Required fail-closed lifecycle contract
1. Private/actual fills: exchange order ID, execution ID, side, quantity, execution price and time, fee asset, immutable source hash. For historical hypothetical simulation without private orders, label `SIMULATED_FILL` and derive an explicit bid/ask/L50 slippage model, never `VERIFIED_FILL`.
2. Stop: accepted order ID and accepted/active timestamp **no later than the first time the position is exposed**; correct stop direction and trigger source (last/mark/index); protected quantity >= live position quantity; trace every replace/cancel/reject and remaining size. If exchange-native stop cannot be atomic with entry, explicitly model the unprotected interval.
3. STOP: trigger event must occur after stop activation; execution ID and actual gap/slippage after trigger; if missing, `STOP_EXECUTION_UNKNOWN`.
4. OPPOSITE_LOCAL: prove uninterrupted stop coverage from entry through confirmed opposite-local exit, including partial fills and replacement. Unknown intervals -> `UNPROTECTED_INTERVAL_UNKNOWN`.
5. Both: order/market event ordering within the same millisecond must use sequence identifiers or remain `AMBIGUOUS_ORDER`. Liquidation distance must use actual mark and account margin configuration, not instrument leverage alone.
6. Source provenance: file exists, SHA-256 verified, time window continuous and includes every lifecycle event. Source labels alone do not establish coverage.

## Risk implications
A risk budget of 0.25–0.5% equity per trade and 1% aggregate is **only modeled** until stop coverage and fill gap are proven. The frozen 1% adverse-price cut is not a maximum realized loss. Preserve the original 67-trade baseline and rejected profit-protection overlays. Do not infer live liquidation count or mark-to-market DD from closed-equity simulations.

## Status / next action
No actual 67-trade execution tape or per-trade rich-data join was obtained in this iteration. This checkpoint documents a new independent, reproducible causal failure in the existing gate. Next implement lifecycle validation against immutable real order/market artifacts; where only historical public data exists, run labeled simulated fills with explicit uncertainty bounds and compare LONG and SHORT on identical sequential capital and fee assumptions. No new performance claims.
