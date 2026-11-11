# HYPE H1 Zero-FP Rich Extension Contract — 2026-11-12

## Frozen baseline
Do not redesign or replace the existing zero-false-positive baseline:
- HYPE_LOCAL_HYBRID_ZERO_FP_V1
- Path A = Ultra Consensus model vote
- Path B = Ultra Survival V2
- Development union: 249 accepted / 249 true / 0 false
- Development coverage: 43.6077% of completed episodes
- Sealed May evidence available for frozen Ultra Survival V2: 31 accepted / 31 true / 0 false

Important: 249/249 means zero false among accepted confirmations, NOT 249 of every H1 local and NOT full recall.

## Correct objective
We do not predict the exact local extreme.
We confirm a Local AFTER it has formed and enter the subsequent swing:
- LOW -> LONG
- HIGH -> SHORT
- same-side extension invalidates/resets a candidate
- first accepted post-local signal counts
- a later correct signal never erases an earlier false-first signal
- strict H1 labels are teacher/evaluation only

## Why the seven rich blocks were collected
They are additional causal evidence for the existing transition chain:
STRUCTURAL EXTREME -> PRICE RESPONSE -> FLOW EFFICIENCY -> LIQUIDATION EXHAUSTION -> BOOK RECOVERY / CONTROL TRANSFER.

Seven blocks:
1. L50 order-book dynamics
2. public liquidations
3. open interest / delta / notional
4. mark / index / funding / basis
5. public long-short holder ratio when historically available
6. time/instrument metadata
7. gap/continuity/validity masks

Missing values are masked, never zero-imputed as market evidence.

## Extension rule
Paths A and B are frozen.
The seven rich blocks may only create an additive Path C for cases not accepted by A or B.

Path C is promotable only if:
1. it is selected without looking at the held-out days;
2. its first accepted signal is post-local and causal;
3. it produces 0 false-first signals on every held-out cohort used for promotion;
4. it increases true-local coverage beyond the frozen A|B union;
5. no thresholds from A or B are changed to manufacture the result.

Any rich rule that gives a false-first on held-out data is rejected, even if in-sample coverage is high.

## Current 12-rich-day status
All 12 completed rich-day overlays are available:
SEP03, SEP10, SEP17, SEP18, SEP30, OCT05, OCT08, OCT12, OCT22, OCT26, OCT27, OCT30.

Preliminary rich post-local searches show useful L50/OI/flow/persistence separation, but a broad rule that looked 0-FP on the selected chronological split produced false positives under leave-one-day-out re-estimation. Therefore it is not yet Path C.

## Next computation
1. Replay frozen A and B on the 12 rich days.
2. Partition each completed H1 swing into:
   - accepted by A|B true;
   - rejected by A|B but terminal true (coverage opportunity);
   - false candidates.
3. Search the seven rich blocks ONLY on the second vs third cohorts.
4. Freeze candidate Path C on discovery/validation days.
5. Score unchanged on untouched days.
6. Report A|B baseline coverage, incremental C true count, C false-first count, combined coverage, first-signal delay and remaining swing.
