# HYPE D250 — STOP versus opposite-local event ordering audit
Date: 2026-11-23 17:27 CET. Research only; no orders, training or production edits.

## Directly inspected source
- `d250_trade_replay_manifest_gate.py` in the target branch, particularly the STOP / opposite-ledger conditions.
- `d250_preentry_event_replay_gate_20261121.py`.
- Frozen `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md` (71/71 historical first signals; 67 completed opposite-local episodes; median MFE giveback 61.2%).

## New concrete finding: STOP chronology cannot be established by exit timestamps alone
The trade manifest gate flags `STOP_NOT_PROVEN_BEFORE_LEDGER_OPPOSITE` when the first opposite confirmation timestamp is <= STOP exit timestamp. That is a conservative and appropriate rejection, but it does not verify a stop trigger or fill on the event tape in the opposite case (opposite confirmation > reported stop exit). A forged or assumed stop exit can pass if the reported timestamps and coverage labels are internally consistent. In particular, `exit_reason=STOP` has no mandatory stop trigger UTC, stop-order placement UTC, stop trigger price, exchange stop trigger basis (last/mark/index), exchange-side order ID, or post-trigger executable quote. Therefore the current validator cannot certify STOP fills or STOP-before-liquidation even if its manifest says ELIGIBLE_FOR_EVENT_REPLAY.

## Deterministic source-level cases (logical evaluation, not historical replay)
Assume entry 10:00, exit_reason STOP, exit 10:05, full opposite ledger and positive prices:
1. first opposite local confirmed 10:04 -> STOP_NOT_PROVEN_BEFORE_LEDGER_OPPOSITE, blocked.
2. first opposite local confirmed 10:06 -> no STOP-vs-opposite ordering flag; **still not an independently verified stop fill**.
3. first opposite local NONE -> no STOP-vs-opposite ordering flag; **still not an independently verified stop fill**.
4. first opposite local confirmed exactly 10:05 -> blocked (<=).
5. declared STOP exit 10:05 but mark price reaches liquidation threshold at 10:04 -> gate has no liquidation event field and cannot detect the contradiction.

These cases are derived from the inspected `audit` conditional logic; they are not claims that tests were executed or that any D250 trade is defective.

## Required matched replay contract
- Per side: LONG opens at executable ask, stops close via bid; SHORT opens at executable bid, stops close via ask.
- Stop state: placement/acknowledgement timestamp, trigger basis, stop level, first observed trigger event, marketable-order arrival, fill(s), partial-fill quantity, realized fees and adverse gap/slippage.
- Independent mark-price and exchange-specific margin-tier maintenance timeline; when stop and liquidation events compete, simulate event order, not favorable assumed STOP precedence.
- Opposite H1 pivot exit only after confirmation becomes available; fill strictly after decision/order latency.
- Require raw event provenance, independent coverage checks, and missing-data fail-closed. Preserve D250 thresholds and rejected profit overlays.
- Apply unchanged baseline and 0.25% / 0.5% equity-risk alternatives on exactly the same matched event tape, sequential equity and aggregate stop-risk <=1%; report LONG/SHORT separately.

## Outcome
Newly verified historical executions: 0; no event tape was loaded. No new net PnL, closed/MTM DD, MFE capture or liquidation statistics. This is a concrete source-code failure-mode analysis, not a claim of profitable replay. Next work: add independent stop-trigger/fill/liquidation sequence evidence and run on immutable 71-signal cohort.
