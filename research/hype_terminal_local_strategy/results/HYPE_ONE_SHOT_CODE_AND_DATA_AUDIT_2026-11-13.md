# HYPE Full-Data Local Research — one-shot checkpoint implementation, 2026-11-13

## Sources / continuity
Continues from:
- research/hype_terminal_local_strategy/results/HYPE_CHECKPOINT_ONESHOT_REGRESSION_2026-11-13.md
- research/hype_terminal_local_strategy/results/HYPE_FULLDATA_RISK_AUDIT_2026-11-13.md
- research/hype_terminal_local_strategy/results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md
- research/hype_full_micro_202607/results/LATEST_FEATURE_AVAILABILITY.json
- research/hype_full_micro_202607/results/RUN_STATUS.json

## Concrete new work
Added research-only `research/hype_terminal_local_strategy/h1_checkpoint_oneshot_research.py` and `tests/test_hype_oneshot_checkpoint_research.py` in the existing research branch. This does NOT change the original detector, production, historical frozen thresholds or any real order behavior.

The frozen V1 detector should assess a candidate at age 285m only once. Original `evaluate` with >=285m can confirm a failed attempt at 286m or later; the new research model explicitly returns FALSE and consumes the checkpoint. Stale/missing observation is MISSED; same-side more-extreme print creates new candidate lineage.

Eight deterministic assertions passed on the local research version: LOW invalid late crossing; LOW TRUE one-shot; HIGH TRUE; same-side reset; missed late snapshot; future-unavailable snapshot rejection; premature snapshot; invalid price rejection.

## Rechecked data inventory
July observed/derived coverage report: 116 contract points; 86 causal/quality inputs; 28 offline teacher/eval; 2 metadata. Input IDs 111,112,113 missing. Archive source-file counts: trades 631, book 631, liquidation 337, OI/mark/ticker each 378. These counts do NOT prove all minute joins are complete. July latest run_status: FAILED, run_id 42660911066.

## Trading risk baseline (existing, not re-executed)
Frozen entry with 1% adverse-price stop and 5x total account exposure, 0.15% nominal roundtrip cost: 67 reported trades; $100->$1,308.86 across five noncontiguous historical slices; max CLOSED equity drawdown 29.36%; 49.25% positive closes. This result is not live and does not include verified intratrade DD, market impact, or arbitrary exchange funding. 3x account exposure reported $100->$531.16 with 18.56% max closed DD. These are not safe/tradable guarantees. Oracle exit at exact future opposite extreme must NOT be used in performance claims.

## Remaining next empirical step
On actual compact M1 time series, recreate candidate lineages and single snapshots with event/available timestamps; replay frozen checkpoint and old late-crossing logic side by side, count TP/FP/FN and missed checkpoints by month, including future strict H1 L6/K2 label only for offline scoring. Recover existing HYPE-HISTORY-20260712-20261103-MASTER / HYPE-RICH-STRONG-* artifacts or explicitly state missing. Only then join per-event liquidation, trade flow, L50 and OI with missing masks. Compare causal local-to-local signal exits against 1% fixed stop on aligned execution stream and report open/closed equity DD, funding, spread/slippage sensitivity, and liquidation distances.

No real-market replay or improvement in historical local precision is claimed by these unit tests.
