# D250 post-local stop geometry and liquidation gate — 2026-11-21 05:30 CET
Paper research only. No live orders or retraining. Existing frozen entry thresholds unchanged.

## Source checked
Read original H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md and HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md directly on the named research branch, plus causal_exit_replay_research.py. Frozen 1% adverse cut says "unless structural stop is closer." The diagnostic structural stop is 0.25 ATR beyond original local, and median diagnostic entry-to-structural distance is 3.14%. The 3.14% median is NOT a per-trade input.

## New reproducible implementation
`research/hype_terminal_local_strategy/stop_geometry_risk_gate_20261121.py`
- LOW->LONG: structural = original LOW - 0.25*ATR; stop = max(entry*0.99, structural).
- HIGH->SHORT: structural = original HIGH + 0.25*ATR; stop = min(entry*1.01, structural).
- Reject wrong-side local geometry, invalid numbers, or modeled liquidation distance <= stop distance + gap reserve.
- Notional = equity*risk_fraction / (entry-to-stop fraction + roundtrip cost fraction + gap reserve fraction).
- Default risk fraction 0.5% equity, aggregate stop risk must be separately enforced <=1%; 25x only converts notional to required initial margin, NOT to risk budget.
- Unknown liquidation price produces PAPER_ONLY_UNVERIFIED_LIQUIDATION, never live eligibility.
- Self-test covers both directions, closer structural stop, invalid local geometry and liquidation-buffer failures. Self-test included in file; not claimed executed in GitHub Actions.

## Deterministic example, NOT historical execution
Entry 100, original LOW 97, ATR 2: structural 96.5, fixed 99 -> LONG stop 99.
Entry 100, original HIGH 103, ATR 2: structural 103.5, fixed 101 -> SHORT stop 101.
With assumed 0.15% roundtrip costs and 2% gap reserve, risk/notional = 3.15%; 0.5% equity risk permits 0.15873016x equity notional (margin 0.00634921x equity at 25x). These are sensitivity assumptions, not validated fee/slippage/maintenance rates.
Closer structural example: LONG entry 100, LOW 99.6, ATR .4 => structural 99.5, fixed 99, selected stop 99.5; risk/notional 2.65%, exposure 0.18867925x. Wider structural stops are NOT automatically substituted for the frozen 1% stop.

## Important limitation
Liquidation prices cannot be inferred reliably from a simple 25x leverage figure: tiered maintenance margin, fees, collateral mode and mark-price rules matter. This gate refuses to assert liquidation safety without a real position-specific liquidation price. A 2% gap reserve is not a loss cap.

## Next reproducible step
Join 67 frozen trade UTC entry/exit IDs to real Mark Price, bid/ask L50, public trades, funding and exact available opposite-local timestamps. Record missing coverage as UNRESOLVED; do not score it as no stop. Compare identical trade IDs under original 3x/5x baseline and risk-based notional with identical execution costs, no capital reuse, monthly MTM and closed equity, MAE/MFE and fill/stop/liquidation counts. No independent forward evidence was produced in this checkpoint.

No changes to detector, production or orders. No claims of new net returns.
