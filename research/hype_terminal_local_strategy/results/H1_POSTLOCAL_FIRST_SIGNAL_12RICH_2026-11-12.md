# HYPE strict-H1 POST-LOCAL first-signal audit — 12 rich days
Date: 2026-11-12
Research only. Live trading code unchanged.

## Correct objective
Do NOT predict the exact H1 extreme.
A Local has already occurred. The task is to confirm it causally *after* the extreme and enter the new swing:
- Local LOW -> LONG
- Local HIGH -> SHORT
- a newer same-side extreme invalidates/resets the old candidate
- the FIRST accepted post-local signal is the scored signal
- a later correct signal never erases an earlier false-first signal
- strict H1 L6/K2 terminal labels are offline teacher/evaluation only

This is the same objective implemented by research/hype_false_local_entry/first_signal_objective.py.

## Recovered historical baseline
The prior strict-H1 30D first-signal attribution audit reported:
- 75 completed strict H1 swings
- 67 correct first core signals
- 8 wrong-side first core signals
- 0 no-signal
- conditional first-signal side accuracy 89.33%
- median correct-first lag 6 minutes

This is the relevant historical baseline; H1-close classification and exact-extreme prediction are different tasks.

## New 12-rich-day post-local replay
Dates: SEP03, SEP10, SEP17, SEP18, SEP30, OCT05, OCT08, OCT12, OCT22, OCT26, OCT27, OCT30.
Existing strict H1 teacher + existing causal M1 flow/structure + seven rich overlays.

Raw legacy dense post-local core on selected strict-H1 swings:
- 33 scored swings
- 23 correct first entries
- 10 wrong first entries
- median correct entry lag about 5 minutes
- median remaining next-swing fraction about 88.3%
- median distance from local is descriptive only; it is NOT an entry condition

## Structural invalidation after the completed H1
For 25 finalized terminal H1 locals and 114 nonfinal H1 candidate bars:
- +5m: 25 true survive, 79 nonfinal survive
- +10m: 25 / 67
- +15m: 25 / 62
- +30m: 25 / 50
- +45m: 25 / 41
- +60m: 25 / 32
- +90m: 25 / 27
- +120m: 25 / 17

Thus every finalized terminal local in this 12-day sample retained its same-side extreme through +120m, while most nonfinal candidates self-invalidated. This survival fact alone is not sufficient for an early entry, but it is a valid reset mechanism.

## 12+7 market relationships after Local
No fixed retracement percentage was used in this search.

On first 9 days, three economically distinct +90m confirmation paths were found:
1. reversal-side L50 replenishment dominates old-side replenishment;
2. side-normalized OI-notional change shows a strong position transfer;
3. post-H1 aggressor-flow shift strengthens in the new-side direction.

Frozen thresholds from those first 9 days, OR-combined, scored on the last three selected dates (OCT26/OCT27/OCT30):
- 8 of 9 terminal locals accepted
- 0 nonterminal candidates accepted

Across all 12 selected days with those frozen thresholds:
- 16 of 25 terminal locals accepted
- 0 false candidates accepted

Important: a leave-one-day-out re-estimation of this same three-path family produced 16 true and 3 false across the 12 days. Therefore the 16/25 zero-FP result is promising chronological evidence, not proof of a universal zero-FP rule.

More conservative leave-one-day-out zero-FP kernels:
- +90m: 30m post-local directional persistence -> 6 terminal confirmations / 0 false
- +120m: 60m post-local directional persistence -> 5 / 0
Earlier +5m and +10m checkpoints had no feature relationship that stayed zero-FP under leave-one-day-out testing.

## What the evidence says
The repeated post-local distinction is not “price has moved X%”.
It is:
1. the same-side extreme stops extending;
2. the new direction persists rather than appearing as one short bounce;
3. aggressor flow shifts toward the new side;
4. new-side flow produces sustained price impact while old-side impact decays;
5. when valid, L50 replenishment transfers toward the reversal side;
6. OI/notional behavior shows either old-side unwind or new-side positioning, interpreted jointly with flow;
7. liquidation information is confirmation when valid, not a mandatory zero-filled gate.

The current rich sample materially improves post-local confirmation, but a high-coverage, independently validated 0-FP strict-H1 rule is not yet proven. Do not replace the objective with H1-close classification or exact-local prediction.
