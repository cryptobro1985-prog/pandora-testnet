# HYPE post-local OHLC ambiguity and gap-bound checkpoint — 2026-11-14 18:28 UTC

Research only; no orders, detector retraining, new branches, or production changes.

## Sources inspected in this branch
- H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md: frozen D250 (rev_atr > 2.0840049433824706; trade_ratio5 > 0.2727842248141979; flow15 < 0.4504731635235635), 71 accepted first signals, 67 completed opposite-local paths; median causal-exit MFE giveback 61.2%.
- HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md: frozen 1% entry-relative adverse-price cut, 0.15% assumed round-trip fee, 67 sequential simulated trades, 22 stop cuts, 49.25% positive closed trades; rejected flow/MFE, K0/K1 and pyramiding variants remain rejected.
- HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md: directional price-impact efficiency/control transfer, not counter-volume alone.
- HYPE_RICH_SOURCE_PROVENANCE_BLOCKER_2026-11-14_1530_UTC.md: raw_files_retained=false in historical rich-source manifest; event-time execution cannot be verified from counts.
- HYPE_COST_FLOOR_FEASIBILITY_2026-11-14_1730_UTC.md: 5x exposure inconsistent with requested 0.25–0.5% stop-risk budget.

## New concrete executable analysis
Added `research/hype_terminal_local_strategy/ohlc_execution_bounds_20261114.py` and executed the identical seven deterministic assertions locally: PASS 7. The program distinguishes LONG and SHORT stop touch, gaps across stop, simultaneous stop/target reach in the same OHLC bar, no-touch HOLD, and risk-budget sizing. It conservatively classifies same-bar stop and target as **AMBIGUOUS_STOP_FIRST**, not a known win. When bar open is already beyond stop it records the worse opening price as an illustrative lower-bound gap proxy, **not a guaranteed executable fill**. Stop trigger is never labeled a verified private fill. The same logic is symmetric for HIGH->SHORT.

Example synthetic LONG bar O=100 H=102 L=98 C=101, stop=99 and target=101: both touched, order unknown; do not book target profit. Mirrored SHORT with stop=101 and target=99 is likewise ambiguous. LONG opening at 97 below stop 99 and SHORT opening at 103 above stop 101 each trigger the gap classification. All examples are synthetic, not historical HYPE data.

With $100 equity, 0.5% budget, 1% entry-relative stop, 0.15% assumed round-trip fee and 1% hypothetical incremental slippage, notional bound = $23.2558. A larger actual gap can exceed budget. The 0.15% fee is from frozen historical audit, not an independently verified current Bybit fee schedule.

## Important limits
An OHLC bar does not reveal the temporal ordering of high/low, stop trigger type (last/mark/index), queue priority, bid/ask spread, order acceptance, available book depth, stop coverage lifecycle, margin/liquidation thresholds, or actual fill. The opening-price proxy itself may be optimistic for a stop-market order. This program is a conservative **component for a future replay**, not a replay of the 67 trades; it does not establish a liquidation count, positive risk-adjusted net return, or protected MFE.

No entry thresholds or rejected profit overlays changed. Four of 71 signals without finalized opposite local must be carried as censored open-position MTM, not discarded. May/Sep/Oct already examined and cannot be described as truly unseen forward.

## Next replay gate
Recover 71 timestamped accepted signal records and matching verified M1/event-time price/mark tapes; retain absent L50/liquidations/OI as UNKNOWN. Apply same chronological entries, fees, funding, slippage, and non-overlapping capital across baseline and alternatives. Evaluate stop-first bounds for ambiguous bars, real gap sensitivity, per-trade risk sizing, month-end MTM/closed DD, stop/target ambiguity counts and MFE capture. No new performance figures are claimed here.
