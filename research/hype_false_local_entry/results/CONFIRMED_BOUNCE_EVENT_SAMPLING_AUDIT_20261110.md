# Confirmed Local Bounce CV — causal sampling audit (2026-11-10)

Scope: existing `confirmed_local_bounce_cv.py` and committed `HYPE_CONFIRMED_LOCAL_BOUNCE_CV.json`; no champion promotion.

## Reproduced from committed OOS report
- LOW: 19 true / 14 false / 33 confirmations; precision 57.58%, recall 19/121=15.70%.
- HIGH: 18 true / 15 false / 33 confirmations; precision 54.55%, recall 18/123=14.63%.
- Sep–Oct LOW: 2/6 (33.33%); HIGH: 7/17 (41.18%).
- Median remaining swing on **true confirmations only**: LOW 299.90 bps; HIGH 268.79 bps. This is not a paper PnL estimate.

## Critical issue: decision-time sampling is not event-driven
`full116_candidate_features.py` defines `EARLY_AGES = (*m1.AGES_S, 3600)`, `COMPARATOR_AGES=(5400,7200,12900,15000)`, and `m1_states(rows, ages=AGES)` loops over those fixed candidate ages. `full116_terminal_replay.py` then selects `early = [row for row in rows if row["age_s"] in features.EARLY_AGES]`; `confirmed_local_bounce_cv.build()` uses `p["early"]`. Thus the classifier has **no explicit time-gate**, but can only confirm on a finite, predetermined age grid (including 3600s). A 3600s signal is not proof of a wait-until-3600 gate, but this pipeline is **not a continuous/event-driven decision process**. It may miss earlier causal reversal evidence between snapshots. Age can remain a predictor; decision opportunities must not be age-gated.

## Additional measurement gaps
- `evaluate()` aggregates median entry distance, remaining swing and capture fraction **only for true first confirmations**. It does not aggregate false-confirmation adverse severity/MAE or evaluate actual paper fill, fees, slippage and exit PnL.
- Feature count (e.g. 138 names) is expanded feature columns, not 138 distinct canonical points; each `point_id` must still be in the 86 legal INPUT IDs.
- The four-period holdout CV is retrospective. Forward/shadow evidence remains necessary.

## Required next implementation (no production promotion)
1. Generate decision rows at **causal observable events** (new extreme, price/flow reversal, book update, OI/liquidation state change), deduplicate and order by observation timestamp; preserve timestamp and freshness/quality masks. No fixed age as a gate.
2. Reuse frozen 260-local STRICT oracle only for labels/evaluation, never as an X predictor. Keep the 86 INPUT whitelist.
3. Inner chronological OOF threshold calibration, then untouched outer-period holdout; compare LOW and HIGH separately. Ensure candidate IDs and episodes cannot leak across train/test boundaries.
4. Publish per-period confirmation precision, coverage, first confirmation delay/distance, remaining swing, capture fraction, **false MAE/severity**, book/flow quality coverage, and paper PnL after fees/slippage.
5. Real orders OFF; paper/shadow only until robust forward confirmation.

No change to model, oracle, workflows or trading flags was made by this audit.
