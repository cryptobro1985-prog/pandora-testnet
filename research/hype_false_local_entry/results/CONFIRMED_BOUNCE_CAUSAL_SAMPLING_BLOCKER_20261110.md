# HYPE Confirmed Bounce — causal sampling blocker (2026-11-10)

Status: diagnostic only; no model promotion, real orders OFF.

## Verified code path

- `research/hype_false_local_entry/full116_candidate_features.py`: `EARLY_AGES = (*m1.AGES_S, 3600)`, `COMPARATOR_AGES = (5400, 7200, 12900, 15000)`, `AGES = ...`.
- `m1_states(rows, ages=AGES)` iterates `for age in ages`, selecting the first completed M1 bar after `candidate_ts + age`. This is a fixed observation schedule even though `confirmed_local_bounce_cv.py` reports `time_gate=false`.
- `confirmed_local_bounce_cv.py` filters legal INPUT point IDs and uses inner-period OOF calibration, but it cannot recover decisions absent from upstream snapshots.
- Therefore the published 19/33 LOW and 18/33 HIGH are snapshot-grid OOS results, NOT true event-driven confirmation precision. The 3600-second age spike in the report is explained by the generator, not by learned reversal evidence.

## Required replacement, preserving the existing oracle

1. Generate one decision on each actual causal market-state transition: completed trade/flow update, new running extreme, L50 book absorption/replenishment/cancel transition, liquidation, OI/mark/basis update. Merge coincident events by exchange timestamp; use arrival-time ordering when reconstructing real-time availability. Never create a decision because candidate age equals a fixed number.
2. Maintain candidate lineage and reset it only on a strictly newer same-side running extreme. An extreme is a candidate, never a confirmation. Evaluate features only from messages available by decision timestamp; use as-of joins with source-specific freshness and missingness flags. Do not forward-fill stale microstructure as fresh evidence.
3. Keep the 260 STRICT L6/K2 finalized locals as teacher/evaluation ONLY. Preserve 86 legal INPUT predictors, exclude TARGET/EVAL/METADATA and any future-derived event labels from X. Partition all candidate lineages by period before model fitting; inner OOF threshold selection must remain out-of-fold.
4. Report LOW and HIGH separately: true/false first confirmations, no-signal episodes, precision/recall, entry distance, remaining swing, captured fraction, false adverse MAE/p90, and worst-fold precision including zero-signal folds as no coverage. Include data freshness/coverage by stream and paper trading with fees/slippage.
5. Assert no hard-coded age grid in production candidate generator and verify via tests that a synthetic reversal event between former age anchors triggers a decision at its own timestamp.
6. Do not compare event-driven challenger against the snapshot baseline as an equivalent OOS test without recording the changed candidate universe and observation frequency.

## Separate CI failure

GitHub Actions PAPER regression run 42749699297, 2026-11-10 03:30 UTC: 218 tests, 30 failures and 9 errors. This is a distinct failing workflow, not evidence that the confirmed-bounce CV passed full paper regression.

Next action: implement event-time state emitter upstream of `build(master)`, add causal timestamp/freshness tests, then rerun four-period OOS. Do not promote a champion until adequate support and forward stability are demonstrated.
