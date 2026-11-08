# HYPE INTERNAL 122 — First-Signal / Dual-Scope Audit

Date: 2026-11-08  
Branch: `research/hype-h1-local-v5-oi-microstructure-20261104`  
Mode: research / paper only. Real orders remain OFF.

## What is actually solved

The causal completed-M1 candidate generator now reaches every finalized label in the 30-day archive:

- INTERNAL L3/K1: **122/122** = 61 LOW + 61 HIGH, 121 complete swings.
- STRICT L6/K2: **76/76** = 38 LOW + 38 HIGH, 75 complete swings.
- Exact label-time coverage uses the recorded `low_ts_ms/high_ts_ms`; tolerance is 0 ms.
- Lookback duplicates are collapsed, reducing the candidate event stream from an equivalent 45,639 hits to 22,264 events.

This is **100% reachability**, not 100% decision precision.

## Why the old metric was wrong

The trading problem is first-signal ordering. If a false correction is accepted first and the real terminal Local is accepted later, the episode is a failure. Candidate-level precision/recall can hide that failure by counting the later true candidate.

`first_signal_objective.py` now scores the first accepted candidate in every completed INTERNAL swing. A later correct Local can no longer erase an earlier false signal.

## Entry timing versus swing capture

On true INTERNAL locals with a following target swing:

| checkpoint | median distance from extreme | median swing remaining |
|---|---:|---:|
| 5m | 0.274% | 88.3% |
| 10m | 0.387% | 82.6% |
| 15m | 0.451% | 80.7% |
| 20m | 0.456% | 80.5% |
| 30m | 0.564% | 75.4% |
| 45m | 0.721% | 66.8% |
| 60m | 0.767% | 63.8% |

Median full INTERNAL swing was about 2.509%. The remembered ~0.34–0.38% early-entry area is therefore reproduced around the 10-minute checkpoint.

For the first false 10-minute probe in an episode, adverse continuation to invalidation had median ~29.45 bps, P90 ~65.18 bps and P95 ~90.20 bps. This is why EARLY remains a small probe with immediate same-side invalidation.

## Honest robustness result

A single 45-minute holdout looked strong: 12/15 first signals correct = 80% precision. Additional filters found after inspecting that holdout could make it look 10/11 or even 11/11, but those are **not untouched OOS results** and are not promoted.

Expanding chronological walk-forward exposed the regime problem:

- 30m: 17/35 = 48.6% first-signal precision, 25.8% recall.
- 45m: 21/42 = 50.0% precision, 31.8% recall.
- 60m: 31/55 = 56.4% precision, 47.0% recall.

The old strict-tuned static gates also fail to generalize to all 121 broad INTERNAL swings: CONF30 ~65.4% precision at only ~14.1% recall; HARD60 ~44.4%; ULTRA60 ~77.8% with only ~5.8% recall.

Therefore no historical result justifies calling the broad first-signal detector perfect.

## The architecture now used

There are two non-mixed teachers:

1. **INTERNAL L3/K1 — TACTICAL.** More frequent Local turns. It can learn probes/scaling, but `core_flip_authorized=false`.
2. **STRICT L6/K2 — CORE.** Larger structural turns. It remains the macro/core structure layer.

Both are now **terminal-finalized**. A K1/K2 pivot is provisional. It is not taught as positive until a later opposite matured pivot exists. If a better same-side pivot appears first, the old provisional pivot becomes false. This directly prevents the learner from training on the classic false-local sequence.

Teacher lookahead is label-only. The teacher code itself filters out every H1 row that was not completed at `now_ms`, so future leakage is blocked in code rather than by convention.

## Continuous forward gate

Every hourly learner cycle now writes `FIRST_SIGNAL_FORWARD_STATUS.json`. It reconstructs only terminal-finalized INTERNAL swings and measures:

- first accepted signals,
- true-first,
- false-first,
- precision,
- recall,
- per-side counts.

Promotion gate is fixed before the forward sample grows: at least 20 completed episodes, at least 10 true-first, precision >= 80%, recall >= 40%. Even passing this gate authorizes **paper/forward promotion only**, not real-money execution.

## Historical limitation

The old 30-day candidate artifact did not retain full raw L50/liquidation microstructure for the 27 INTERNAL locals that were outside its original candidate space. Those values are not fabricated. Richer evidence is collected prospectively and will enter the forward learner as it becomes genuinely available.

## Bottom line

The candidate-generation problem is solved on this archive: 122/122. The remaining problem is first-signal discrimination, and historical tuning cannot honestly prove perfection. The system has therefore been changed so that it learns the correct target, keeps INTERNAL and STRICT semantics separate, finalizes only terminal locals, and automatically scores itself on future completed swings.
