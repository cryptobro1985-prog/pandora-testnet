# D250 manifest semantic-gap audit — 2026-11-18 01:30 CET

Research-only, frozen thresholds unchanged. No training, production modification, or live orders.

## Actual work
Read the frozen D250 and asymmetric-risk reports and inspected `d250_trade_replay_manifest_gate.py` on the target branch. Added `d250_manifest_semantic_gap_probe_20261118.py`, an executable four-assertion regression probe for manifest eligibility. The probe was committed; **not executed against historical trade rows**. Its synthetic examples are deliberately not market observations.

## New critical finding
The current manifest gate can return `ELIGIBLE_FOR_EVENT_REPLAY` for a row even when an intervening same-side new extreme invalidated the candidate, because the gate neither requires nor checks a same-side invalidation event. It also cannot establish whether the next opposite local was already confirmed before D250; the STOP path does not require an opposite-local timestamp. Finally, coverage=`COMPLETE` is a self-declaration with no mandatory tape hash, per-event provenance, or time-window verification. Thus manifest eligibility is **not evidence of a valid D250 trade**, and eligible counts must not be used as backtest denominators.

The probe constructs a nominal LOW->LONG candidate, then three variants: intervening lower low, pre-D250 opposite confirmation, and empty tape SHA-256 fields. All currently pass `audit` by design. These are **counterexamples to the validation contract**, not proof that any of the historical 67 trades is invalid.

## Required before replay
1. Restore all 71 frozen accepted signals with UTC candidate extreme, H1 K2 confirmation, D250 checkpoint, as-of feature provenance and cancellation events; distinguish 67 closed opposite-local episodes from four censored/nonfinalized.
2. Require complete chronological local-state events from candidate extreme through entry: cancel on a new same-side extreme or an opposite confirmed local before D250. For STOP, absence of opposite-confirmation timestamp must not imply absence of opposite confirmation.
3. Join each candidate to immutable M1/Public Trades/mark event-tape windows with content hash, UTC range, source and observed gaps. Treat absent L50/OI/liquidation as unavailable, not zero.
4. Run separate LOW->LONG and HIGH->SHORT fills with order/event sequencing, stop gap/slippage, funding, mark liquidation and portfolio-capital constraints; then compare unchanged baseline and conservative risk variants on the same trades.
5. Keep rejected MFE overlays rejected until truly independent forward evidence.

## Status
Historical matched event replay: **not performed**. No new monthly net equity, MTM DD, liquidation count, or MFE retention is claimed. The immediate gain is an explicit reproducible guard against falsely promoting incomplete manifests into trading evidence.

References: `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`, `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`, `d250_trade_replay_manifest_gate.py`.
