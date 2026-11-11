# HYPE cross-period local relationship diagnostic — 2026-11-11

This is a **descriptive research result, NOT model selection, untouched OOS,
a tradable signal, or validation that an exact terminal Local is predictable**.

## Source and methodology

Retained master archive:
`HYPE-HISTORY-20260712-20261103-MASTER`, SHA256
`c9d588b5c78d0e72a3073ceb62c7fa100381ebf69df911b22a170171a2653975`.

- Train-side descriptive feature ranking: Jul12–Aug07 FULL-MICRO.
- Fixed feature direction applied without adjusting on Oct04–Nov03 compact.
- Candidate snapshots at **300 seconds** only.
- AUC refers to candidate `strict_true` vs false in each corpus.
- Low rows: July 655 with 23 true; October 305 with 39 true.
- High rows: July 597 with 24 true; October 238 with 38 true.
- Different teacher/candidate-generation contracts and class rates **have not
  been proven identical**; all results are discovery-only.

## Representative single-feature frozen-direction AUCs

| Side | Causal snapshot feature | Jul oriented AUC | Oct same-direction AUC | Diagnostic |
|---|---|---:|---:|---|
| LOW | `rev_ret_300s` (same as oriented `ret_300s`) | 0.9043 | 0.6304 | partial transfer |
| LOW | `rev_eff_300s` | 0.8228 | 0.6084 | partial transfer |
| LOW | `distance_low_60m_bps` | 0.8307 | 0.4245 | unreliable/changes regime |
| LOW | `distance_low_6h_bps` | 0.8307 | 0.4245 | unreliable/changes regime |
| LOW | `imbalance_300s` | 0.7758 | 0.5147 | near chance |
| HIGH | `rev_ret_300s` (same as oriented `ret_300s`) | 0.8163 | 0.6925 | partial transfer |
| HIGH | `rev_eff_300s` | 0.7515 | 0.5739 | weak partial transfer |
| HIGH | `distance_high_60m_bps` | 0.8316 | 0.3099 | sign/selection instability |
| HIGH | `distance_high_6h_bps` | 0.8316 | 0.3099 | sign/selection instability |
| HIGH | `imbalance_300s` | 0.6848 | 0.5192 | near chance |

5 of the 12 July-best common LOW features scored October frozen-sign
AUC >= 0.55; 6 of the 12 July-best common HIGH features did.

## Interpretation

- The *price displacement after a candidate extreme* appears more transferable
  than raw absolute proximity to an old high/low under this diagnostic.
- Raw imbalance alone is comparatively weak.
- This does NOT show incremental predictive value of JEPA/Cortex, which must be
  established using frozen chronological ablations and correct teacher alignment.
- L50/OI/liquidations were preserved in July full-micro but absent from the
  October compact candidate file. Their crossperiod incremental value is
  **unverified**; never zero-fill the missing October families.
- `ret_300s` and `rev_ret_300s` are mechanically oriented duplicates,
  not two independent discoveries; do not double-count feature wins.

## Hypothesis for next controlled experiment

Train a LOW/HIGH-independent **price-response persistence** gate on train/dev,
and evaluate it alongside stronger false-local adversarial negatives and
appropriate data-quality masks. Compare its incremental value over the existing
state machine/score. Repeated correlated snapshots must be grouped by candidate
and separated by matured teacher timestamps.

Any thresholds developed after looking at the above October comparison require
a new genuinely unused forward period.
