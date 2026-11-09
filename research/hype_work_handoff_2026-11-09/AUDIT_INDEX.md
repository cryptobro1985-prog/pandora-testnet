# HYPE Research Audit Index

Work should recursively inspect the following directories, not only this curated list:
- research/hype_false_local_entry/
- research/hype_local_only/results/
- research/hype_true_local_relation/
- research/hype_strict_h1_guard/
- research/hype_full_micro_202607/results/
- research/hype_local_v5/

## Highest-priority audits

### Terminal/teacher correctness
- research/hype_false_local_entry/STRICT_H1_TERMINAL_ALWAYS_ON_AUDIT_2026-11-09.md
- research/hype_strict_h1_guard/terminal_local_state_machine.py
- research/hype_strict_h1_guard/test_terminal_local_state_machine.py
- research/hype_local_v5/labels.py

### False-vs-true causal relation
- research/hype_false_local_entry/FALSE_VS_TRUE_CAUSAL_SIGNATURE_AUDIT_2026-11-09.md
- research/hype_false_local_entry/FALSE_VS_TRUE_FINAL_CAUSAL_RESULT_2026-11-09.md
- research/hype_false_local_entry/HYPE_DEEP_LOCAL_SIGNATURE_AUDIT_2026-11-09.md
- research/hype_true_local_relation/TRUE_LOCAL_RELATION_116_LATEST.md
- research/hype_true_local_relation/TRUE_LOCAL_RELATION_116_LATEST.json
- research/hype_true_local_relation/TRUE_LOCAL_RELATION_QUARTER_STABILITY.md
- research/hype_true_local_relation/TRUE_LOCAL_RELATION_QUARTER_STABILITY.json

### First-signal / candidate coverage
- research/hype_false_local_entry/FIRST_SIGNAL_122_AUDIT_2026-11-08.md
- research/hype_false_local_entry/FIRST_SIGNAL_122_AUDIT_2026-11-08.json
- research/hype_false_local_entry/CANDIDATE_COVERAGE_AUDIT_30D.json
- research/hype_false_local_entry/LABEL_SCOPE_AUDIT_30D.json
- research/hype_false_local_entry/M1_EPISODE_AWARE_WALKFORWARD_2026-11-09.json
- research/hype_false_local_entry/first_signal_objective.py

### HARD120 and survival
- research/hype_false_local_entry/HARD120_HISTORICAL_AUDIT_2026-11-08.md
- research/hype_false_local_entry/HARD120_HISTORICAL_AUDIT_2026-11-08.json
- research/hype_false_local_entry/HARD120_CROSS_PERIOD_202607_AUDIT_2026-11-08.md
- research/hype_false_local_entry/HARD120_CROSS_PERIOD_202607_AUDIT_2026-11-08.json
- research/hype_false_local_entry/HARD120_INDICATOR_STRUCTURE_AUDIT_2026-11-09.md
- research/hype_false_local_entry/SURVIVAL_LADDER_AUDIT_2026-11-08.md
- research/hype_false_local_entry/SURVIVAL_LADDER_AUDIT_2026-11-08.json
- research/hype_false_local_entry/hard_survival_gate.py

### Early challengers / failures
- research/hype_false_local_entry/EARLY60_FULL_STACK_DUAL_PERIOD_AUDIT_2026-11-09.json
- research/hype_false_local_entry/HARD120_PLUS_HIGH_FLOW_DUAL_PERIOD_AUDIT_2026-11-09.json
- research/hype_false_local_entry/HIGH_FLOW_V2_SEALED_LATE_AUGUST_AUDIT_2026-11-09.json
- research/hype_false_local_entry/HIGH_FINAL_THREE_PERIOD_DECISION_2026-11-09.md
- research/hype_false_local_entry/HIGH_FINAL_THREE_PERIOD_DECISION_2026-11-09.json
- research/hype_false_local_entry/SEPTEMBER_FROZEN_CHALLENGER_AUDIT_2026-11-09.json
- research/hype_false_local_entry/SEPTEMBER_UNTOUCHED_BASELINE_AUDIT_2026-11-09.json

### Frozen strategy portfolio
- research/hype_strict_h1_guard/FROZEN_EARLY_LOCAL_RULES_2026-11-09.json
- research/hype_strict_h1_guard/FINAL_LOCAL_STRATEGY_PORTFOLIO_2026-11-09.json
- research/hype_local_only/results/HYPE_LOCAL_ULTRA_SURVIVAL_V2.json
- research/hype_local_only/results/HYPE_LOCAL_ULTRA_CONSENSUS_V1.json
- research/hype_local_only/results/HYPE_LOCAL_HYBRID_ZERO_FP_V1.json
- research/hype_local_only/results/MAY_ULTRA_SURVIVAL_V2_SCORE_2026-11-09.json

### Full micro / data quality
- research/hype_full_micro_202607/results/LATEST_FEATURE_AVAILABILITY.json
- research/hype_full_micro_202607/results/LATEST_MANIFEST.json
- research/hype_full_micro_202607/results/LATEST_REPORT.json
- research/hype_full_micro_202607/results/TRUE_LOCAL_SIGNATURES_LATEST.md
- research/hype_full_micro_202607/results/GLOBAL_LOCAL_RELATION_LATEST.json
- research/hype_full_micro_202607/results/LOW_HIGH_RELATIONS_LATEST.json
- research/hype_full_micro_202607/test_data_quality.py

Important defects already discovered:
- crossed L50 books existed in old Jul-Aug rich snapshots and must be masked;
- missing liquidation source must not be encoded as genuine zero;
- corrected rebuild/validity masks are required before promoting L50/liquidation rules.

## Workflows worth reading
- .github/workflows/hype-local-only.yml
- .github/workflows/hype-preserve-jul-nov-master.yml
- .github/workflows/hype-score-may-ultra-survival-v2.yml
- .github/workflows/hype-full-micro-202607.yml
- .github/workflows/hype-dense-cross-period-now.yml
- .github/workflows/hype-four-regime-meta-selection.yml
- .github/workflows/hype-september-untouched-shadow-stack.yml

## Historical handoffs
Read for context, but prefer the newer audits above:
- research/hype_local_v5/HYPE_H1_LOCAL_ENGINE_V5_FINAL_HANDOFF.md
- research/hype_local_v5/FINAL_ANALYSIS_2026-11-04.md
- research/hype_local_v5/CODEX_TASK_HYPE_H1_LOCAL_ENGINE.md
