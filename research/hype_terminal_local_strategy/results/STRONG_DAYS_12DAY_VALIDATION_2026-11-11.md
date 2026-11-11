# HYPE H1 terminal-local causal audit — 12 strong days

Date: 2026-11-11

## Correct scope
Only H1 candidates are used. No 6h-candidate logic is part of this audit.

Days:
SEP03, SEP10, SEP17, SEP18, SEP30, OCT05, OCT08, OCT12, OCT22, OCT26, OCT27, OCT30.

Strict H1 terminal locals inside these exact UTC days:
- 26 total
- 13 LOW
- 13 HIGH

Raw H1 L6/K2 candidates on the same days:
- 43 total
- 26 terminal true
- 17 non-terminal / later superseded same-side H1 candidates

Observation windows are the already agreed 60 / 180 / 300 seconds after the actual H1 candidate extreme.

## Critical causal result
All 43 H1 candidates — both the 26 true terminal locals and the 17 false/non-terminal candidates — remained un-invalidated during the first 300 seconds after their candidate extreme.

Therefore:
- survival for 60/180/300 seconds is NOT enough to distinguish a terminal local;
- price moving away from the extreme is NOT enough;
- a fixed retracement percentage cannot solve the problem.

### Price distance from candidate extreme

At 60s:
- true terminal median reversal: 16.19 bps = 0.162%
- false H1 median reversal: 16.44 bps = 0.164%

At 180s:
- true terminal median reversal: 21.92 bps = 0.219%
- false H1 median reversal: 27.17 bps = 0.272%

At 300s:
- true terminal median reversal: 33.56 bps = 0.336%
- false H1 median reversal: 43.22 bps = 0.432%

The distributions overlap strongly. In this sample the false H1 candidates can even have a larger early retracement than true terminal locals.

## Consequence
The previous claim that the 26 true locals alone showed a clean 180-second signature was incomplete because it did not compare them against all 17 false H1 candidates.

A correct terminal-local detector must distinguish:
- a genuine H1 terminal control transfer,
from
- an H1 reversal that looks convincing for the first 1–5 minutes but is later superseded by a stronger same-side H1.

No new indicator or arbitrary threshold is justified by this audit.

## Current verdict
We can label the 26 true terminal H1 locals retrospectively, but the currently tested early 60/180/300-second price/flow behavior does NOT support a claim of 26/26 causal detection with 0 false positives.

The next research step must stay inside the existing 12 strategic groups + 7 rich layers and identify which already-present market-state relationships separate the 26 true H1 terminals from the 17 false H1 candidates, under causal day-held-out validation.
