# HYPE delayed pre-entry tape regression — 2026-11-15 02:28 CET

Research only; no orders, no production changes, no detector retraining.

## Evidence reviewed
Read existing frozen reports `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md` and `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md` directly from this branch, plus `latency_aware_event_gate_20261115.py`. D250 thresholds remain unchanged: rev_atr > 2.0840049433824706, trade_ratio5 > 0.2727842248141979, side-normalized flow15 < 0.4504731635235635. The 67-trade 1% adverse cut baseline is unchanged.

## Concrete new regression
The prior gate accepts `entry_exchange_ms=None`, in which case it excludes pre-entry prints only by receipt timestamp. A print with exchange time 90, received at 120, can be mistaken for a stop after entry exchange time 100, received at 110. This is a **conditional unsafe invocation**, not evidence that existing historical simulations used it.

New regression module `delayed_preentry_tape_regression_20261115.py` requires both entry exchange and receipt timestamps, excludes pre-entry exchange prints even when received later, rejects exchange reordering, and distinguishes stop triggers from fills. It was executed locally: **6 deterministic synthetic checks passed** (LONG and SHORT delayed pre-entry print, LONG and SHORT genuine stop-first, missing entry clock, exchange reordering).

## Limitations
The new module is an isolated research guard, not a substitute for the existing simulator and not a historical Bybit replay. It assumes the entry exchange clock is reliably recorded, and the sequence is complete. It does not model book depth, marketable stop execution, funding, liquidation, or actual fill prices. The original gate is safe against this particular delayed pre-entry case **when entry_exchange_ms is provided**.

## Research status
No newly validated matched rich M1 tape for all 71 D250 signals in this iteration; no new monthly net equity, mark-to-market DD, stop fill rate, liquidation count or MFE retention. Historical 71/71 is precision on tested episodes, not 100% live win rate. Existing late-Aug weakness remains unresolved.

Next step: require non-null entry_exchange_ms at the event replay adapter boundary; find a complete matched tape and replay LONG/SHORT with identical costs and risk budgets (0.25%-0.5% equity, total stop risk <=1%), including chronological walk-forward and untouched forward. Keep rejected exit overlays rejected until independent evidence.
