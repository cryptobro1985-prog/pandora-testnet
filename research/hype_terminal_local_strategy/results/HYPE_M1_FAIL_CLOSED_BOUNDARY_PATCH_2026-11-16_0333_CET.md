# HYPE M1 fail-closed replay boundary patch — 2026-11-16 03:33 CET

Research only; no orders, no detector retraining, no production changes.

## Concrete changes
Updated `m1_stop_order_ambiguity_replay_20261116.py` in-place, retaining the original branch. Rejected entry timestamps within a minute with `UNKNOWN_ENTRY_INTRABAR`, rejected partial exit minutes with `UNKNOWN_EXIT_INTRABAR`, and enforced every 60-second bar start in the interval [entry,exit). Missing trailing minute now returns `UNKNOWN_COVERAGE`; internal gaps return `UNKNOWN_GAP_OR_BOUNDARY`. No fill prices or event sequencing are fabricated.

Updated `tests/test_m1_stop_replay_boundary_20261116.py` to require fail-closed outcomes for the two defects previously reproduced, and aligned the source self-test gap assertion.

## Commits
- Replay boundary gate: 880db16f027cf0be1d4d8b6bea5b2ae31320a760
- Regression expectation update: daf8832b071314c5067dd76488af6db8a5832fcf
- Gap assertion alignment: 0080c914b2507b56377b88348fe853076e13ad1e

## Verification status
Static review and deterministic fixture expectations only. GitHub Actions execution not confirmed in this iteration. Importantly, the gate is deliberately conservative: partial-minute exits are UNKNOWN even if earlier M1 bars appear safe; if a stop is touched, its fill remains UNKNOWN. M1 OHLC cannot establish ordering of intrabar extrema or executable prices.

## Next empirical replay
Match the 67 sequential simulated trades to frozen causal entry timestamps and archived Bybit trade/mark/order-book data; preserve episode IDs and reject unavailable coverage. LOW->LONG and HIGH->SHORT analyzed separately. For matched episodes compare unchanged baseline against stop-risk 0.25% and 0.5% equity (aggregate <=1%), consistent funding, fee, gap/slippage and no capital reuse. Only then compute monthly net equity, closed/MTM DD, fills, liquidation-distance stress, and MFE capture/giveback. Preserve rejected profit-protection overlays as rejected until unseen evidence supports them.

## Limitations
No matched real-event execution replay or independent forward return established in this iteration. Prior 71/71 D250 selection, 67 trade simulation and other frozen metrics remain historical research, not verified fills or zero-liquidation evidence.
