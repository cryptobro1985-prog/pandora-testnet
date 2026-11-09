# HYPE Work data-usage audit — 2026-11-09

## Finding
The current EARLY_TRAJECTORY_REPORT_2026-11-09.md is a PARTIAL DEVELOPMENT SCREEN, not a full-data result.

The exact command recorded in WORK_PROGRESS.json was:

`python -W error -m research.hype_false_local_entry.replay_early_trajectory --master ../hype-work-cache/master.zip --rules research/hype_work_handoff_2026-11-09/EARLY_TRAJECTORY_RULES_V1.json --period 01_JUL12_AUG07_FULL_MICRO --output research/hype_work_handoff_2026-11-09/EARLY_TRAJECTORY_DEV_V1.json`

Therefore the reported 15.0% LOW baseline and 20.0/23.5% HIGH figures came from only:
- one development period: 2026-07-12 -> 2026-08-07;
- strict L6/K2 labels available for that period;
- M1 price / executed-flow trajectory layer used by replay_early_trajectory.

They were NOT computed over all preserved Jul-Nov periods.
They were NOT computed from the canonical 116-input live contract.
They were NOT computed from a clean validated L50/liquidation/OI full-micro cache.
They were NOT sealed May/June results.
They were NOT forward/live precision estimates.

## Data that exists but was not part of the V1 score

### Historical master
Artifact 13650399622:
- Jul12-Aug07
- Aug08-Sep01
- Sep01-Oct01
- Oct04-Nov03

Only the first member was scored by the V1 command.

### Full-micro / richer data
Existing Jul-Aug rich snapshots are known contaminated for promotion:
- 822/6260 crossed books passed the historical valid flag;
- liquidation availability masks were absent.

These may be used for hypothesis discovery only after explicitly masking invalid streams; they must not certify a final promoted rule.

A corrected clean-cache build is running as GitHub Actions run 42619539996.
Until it publishes and passes CLEAN_MICRO_AUDIT.json, L50/liquidation/OI trajectory claims remain pending.

### Canonical 116 contract
The 116-point contract exists in:
research/hype_quant/feature_contract.py

However the V1 replay did not evaluate all 86 causal model-eligible inputs. It used the narrower early M1 trajectory feature layer.

### Sealed / live
May/June sealed artifacts and forward/live captures were not used for V1 scoring.
They must remain untouched until a candidate is frozen, except for already completed diagnostic audits.

## Required interpretation
Do NOT present the current V1 numbers as "the result on all our saved data".
Correct wording:
"First development-screen result on one Jul-Aug M1 cohort; both proposed V1 families failed the development gate."

## Required next workflow
1. Finish and validate the corrected clean full-micro cache.
2. Produce a DATA COVERAGE MATRIX before new modeling.
3. Separate experiments by comparable availability cohort:
   - all-period M1 cohort;
   - clean historical microstructure cohort(s);
   - canonical live/full116 cohort;
   - sealed periods;
   - forward.
4. Do not mix missing microstructure with real zeros.
5. Develop/freeze on development data.
6. Only then score chronological/holdout/sealed.
7. Final report must state exactly which periods and fields contributed to every metric.
