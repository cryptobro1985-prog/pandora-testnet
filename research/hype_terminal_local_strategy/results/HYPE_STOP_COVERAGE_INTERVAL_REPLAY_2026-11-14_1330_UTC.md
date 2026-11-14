# HYPE stop coverage interval replay — 2026-11-14 13:30 UTC

Research only. Frozen D250 entry and 1% adverse cut unchanged; no production or live orders.

## Source inspection
Read existing branch files `trade_manifest_gate_research.py`, `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`, and `HYPE_STOP_LIFECYCLE_CAUSALITY_AUDIT_2026-11-14_1225_UTC.md` directly. Baseline 67 sequential trades, 22 fixed-cut exits; private exchange order lifecycle data not present in these reports.

## Concrete new executable experiment
Implemented a local Python interval-based stop lifecycle checker using decimal quantities and time-ordered events (ACTIVE, CANCEL, REJECT, FILL_POSITION, REDUCE_POSITION), with separate LONG and SHORT stop geometry. Executed 10 synthetic assertions successfully in Python (10/10). This code was executed locally in the analysis workspace, not yet merged into the repository. Tests covered:
1. stop accepted at entry -> no uncovered time;
2. activation 10ms late -> uncovered [100,110);
3. cancellation mid-hold -> uncovered [150,200);
4. cancellation then replacement 1ms later -> uncovered [150,151);
5. stop covering only half position -> uncovered [100,200);
6. invalid LONG stop above entry -> rejected;
7. duplicate (timestamp, sequence) -> ambiguous;
8. valid SHORT stop above entry -> accepted;
9. invalid SHORT stop below entry -> rejected;
10. position size doubled without stop resizing -> uncovered [150,200).

This is a deterministic causal test, **not** a historical Bybit execution replay. A complete set of synthetic lifecycle fields does not establish exchange provenance. It also does not establish executable fill price, gap or liquidation margin.

## New operational finding
The old manifest's nonempty `protective_stop_order_source` cannot prove continuous stop coverage. Even a stop accepted exactly at entry fails risk control after a partial additional fill unless protected quantity increases accordingly. Cancel-and-replace is not atomic: a 1ms gap is unprotected. For historical paper fills, classify as `SIMULATED_STOP_COVERAGE` unless actual order-acceptance/replace/cancel/position-fill event IDs are supplied and validated.

## Remaining hard gates
- Obtain immutable per-trade event manifests with source SHA-256, complete coverage and causal event order for all 67 baseline trades; public prints are not private fills.
- Match mark/index/last trigger basis, order status, stop quantity, L50 bid/ask and slippage, fees/funding and margin/liquidation mechanics.
- Compare unchanged baseline, 0.25%-0.5% equity stop-risk sizing, staged entry and exits on same chronological trade set, including monthly net equity, mark-to-market DD, closed DD, MFE giveback, stops and unseen forward.
- Do not promote previously rejected MFE overlays without new independent forward evidence.

No new validated net-return, liquidation, or MFE statistics. No detector training or threshold changes.