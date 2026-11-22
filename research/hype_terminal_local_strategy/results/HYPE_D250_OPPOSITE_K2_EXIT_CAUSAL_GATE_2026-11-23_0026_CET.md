# D250 opposite-local exit: K2 availability causality gate
Date: 2026-11-23 00:26 CET. Research only; no orders.

## Evidence inspected
Read frozen `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`, `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`, and current `d250_full_cohort_gate.py` directly from the requested branch. Frozen entry remains rev_atr > 2.0840049433824706, trade_ratio5 > 0.2727842248141979, flow15 < 0.4504731635235635. The 67 completed historical trajectories are NOT an event-level exchange execution replay.

## New finding
The cohort gate previously checked exit time against `opposite_ledger_first_utc` but did not require a separately timestamped *K2 availability*. A timestamp representing the opposite local's extremum/first occurrence cannot authorize an exit at that instant: the strict H1 K2 confirmation may become available later. This could admit look-ahead bias even if the entry side and D250 timestamps pass.

## Code change
Added required manifest column `opposite_k2_available_utc`. For `CLOSED_OPPOSITE`, block when missing, earlier than opposite event, after observation cutoff, or later than recorded exit. For `OPEN_AT_CUTOFF`, block contradictory populated opposite K2. Added three synthetic assertions (missing K2, premature exit, valid order). Python self-test execution has **not** been independently verified in this run. The previous 9 tests are preserved; 12 assertions are now intended.

## Replay prerequisite
Reconstruct `opposite_ledger_first_utc` and `opposite_k2_available_utc` from original UTC H1 bars and the original K2 algorithm; ensure bar close and data-arrival timestamps. Match 71 frozen signal IDs to original records; SHA256 strings alone do not establish file integrity. A valid close must use an executable bid/ask event **at or after** K2 availability, with stop-first event priority when applicable. Keep 4 censored signals open in MTM ledger, never fabricate exits.

## Remaining blocked metrics
No per-trade matched Bybit M1 Public Trades/L50/Mark/funding tapes were located or executed in this run. Monthly net equity, fill rates, MTM and closed DD, stops, liquidation count, and MFE capture remain unverified. No retuning, no promotion of rejected overlays, no production changes.
