# HYPE 30D replay: first-signal attribution audit (2026-11-10)

Scope: research/hype-h1-local-v5-oi-microstructure-20261104. **Research only. Orders OFF.**

## Input and reproducibility limits

This audit inspects the locally available `/mnt/data/hype30d/replay_result.json` produced by a *reimplementation* of the sequential engine, not an independently reproduced execution of the checked-out GitHub module. The source minute bars, labels, and full flip ledger are **not bundled with this report**. Accordingly, the earlier claim of exact-minute candidate reachability 122/122 (and 76/76 strict) is **not independently verifiable from this JSON**. No untouched forward/OOS test was run.

Label contract in `LABEL_SCOPE_AUDIT_30D.json`: 122 finalized internal locals (61 LOW + 61 HIGH) => 121 complete swings; 76 strict finalized (38+38) => 75 swings. Previous restricted candidate coverage: 95/122 internal and 76/76 strict. These are separate from the new, unverified reachability claim.

## Recalculation from the available per-swing rows

| Metric | Internal | Strict |
|---|---:|---:|
| Complete swings | 121 | 75 |
| First core signal present within scoring window | 121 | 75 |
| Correct first core signal | 111 | 67 |
| **Wrong-side first core signal** | **10** | **8** |
| **No first core signal** | **0** | **0** |
| First-signal side accuracy conditional on a swing | 111/121 = 91.74% | 67/75 = 89.33% |
| Core flips over full replay | 2,507 | 2,507 |
| Correct first core signals / all flips | 111/2507 = 4.43% | 67/2507 = 2.67% |
| Remaining flips not credited as correct first signals | 2,396 | 2,440 |
| Median correct-first lag | 6 min | 6 min |

The prior JSON field `missed` equals `wrong_first` in both cohorts. It is **not a no-signal count**: every completed swing has a first signal, but 10/8 have the wrong side. This distinction is essential for redesign. The metric `true_first / all_core_flips` is a global event precision proxy, not trade win rate or per-swing side accuracy; it includes duplicate flips and signals outside credited intervals. `false_first` in the local replay JSON is therefore a misleading name for all uncredited flips.

## Required next experiment

1. Retrieve and hash original `labels.json.gz` and `compact_1m.jsonl.gz`, and reproduce the original Python engine, not a reimplementation.
2. Generate LOW/HIGH candidates on completed M1 data only. Audit each of 122 internal label IDs by exact minute and extreme price; report any timestamp convention mismatch and earliest observable candidate time. Label identity is for scoring, never for candidate construction.
3. Emit the **entire chronological core flip ledger**, including duplicate flips, with stage, causal inputs, timestamp, side and state transitions. Assert EARLY_PROBE never changes core position; HARD/ULTRA only.
4. Separate metrics: candidate recall, correct-first, wrong-first, no-first, duplicate flips, first-signal precision, median/p90 lag, entry distance, adverse extension and remaining swing, separately for internal/strict and LOW/HIGH. Do not conflate wrong-first with no-signal misses.
5. Fit any redesign only on historical training slices; freeze settings and evaluate on later, untouched forward/OOS. No orders.

This is an attribution audit, **not** evidence of profitable trading or successful OOS generalization.
