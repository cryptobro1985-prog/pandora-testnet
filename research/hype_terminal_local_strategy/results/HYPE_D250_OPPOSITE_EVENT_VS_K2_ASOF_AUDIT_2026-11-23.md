# HYPE D250 opposite-local event-time versus K2 availability audit — 2026-11-23

Research-only; frozen thresholds unchanged; no production or real orders.

## Concrete new analysis
Read the existing `d250_full_cohort_gate.py` and the frozen walk-forward report on the specified research branch. Reproduced three deterministic timestamp scenarios with a Python assertion script (3/3 passed).

The current validator uses `opposite_ledger_first_utc <= entry_utc` to reject an entry and `OPEN_AT_CUTOFF and first != NONE` to reject an open position. However `opposite_ledger_first_utc` is not documented as either the *extreme timestamp* or the *K2-available timestamp*. For a strict H1 local, these are different. The frozen report's statement 'next opposite strict H1 local has not already occurred' also needs explicit temporal interpretation.

Example UTC-relative to T0: opposite extreme at T0+200m, D250 entry at T0+250m, opposite K2 available T0+310m, observation cutoff T0+280m. An as-of replay could not have known the terminal opposite at entry or cutoff; retrospective strict-local episode scoring can nevertheless classify it as already occurring. Conflating those two definitions can create hindsight contamination or incorrect censoring.

## Deterministic replay scenarios (synthetic, not HYPE trade results)
1. K2 at +310, entry +250, cutoff +280: OPEN_AT_CUTOFF under strictly causal execution.
2. K2 at +310, entry +250, cutoff +330: close no earlier than +310.
3. K2 at +240, entry +250, cutoff +330: opposite already confirmed; block entry.

Python assertions: PASS 3/3. These do not establish the true classification of any of the 71 historical signals.

## Required data reconciliation before changing code
For each accepted signal preserve separately: `opposite_extreme_utc`, `opposite_k2_available_utc`, `opposite_event_first_observable_utc`, `entry_utc`, `observation_cutoff_utc`, and the source evidence/hash. Identify whether frozen D250 was evaluated with hindsight episode boundaries; do not silently reinterpret its 71/71 result as online-executable precision. Apply the same interpretation to all 71 signals, including the four censored positions, and report both retrospective episode validity and causal trade eligibility as separate columns.

## Trading risk impact
No replay execution prices, mark-to-market, liquidation paths, fees/funding, or per-trade bid/ask data were established in this iteration. No new net PnL, MFE capture, or drawdown claim is justified. Continue with actual per-signal UTC ledger and matched Bybit tape; freeze baseline and rejected exit overlays. Risk target remains 0.25–0.5% equity per trade, total stop risk <=1%, with stop gap/slippage and liquidation buffer.
