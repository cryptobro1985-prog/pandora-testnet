# PANDORA — HYPE LOCAL-ONLY / CODEX HANDOFF

## AUTHORITATIVE GOAL
There is only one research objective now:
detect a forming **Local LOW** and **Local HIGH** as early and causally as possible.

Intended eventual execution logic (NOT enabled in this bundle):
- confirmed/approved Local LOW -> long leg
- next Local HIGH -> close long / reverse short
- next Local LOW -> close short / reverse long

**Real orders are OFF.** This package is model/research infrastructure.

## ACTIVE ARCHITECTURE
1. 30-day supervised pretrain from HYPE history.
2. Strict H1 L6/K2 pivot labels are the teacher; future bars are LABELS ONLY.
3. Quantum heads: LOW/HIGH x 60s/180s/300s.
4. Full-H1 baseline trained across the saved H1 history.
5. Live FeatureState exposes the causal subset of the 116-point contract.
6. Live labels mature later when the strict teacher becomes known.
7. Cortex receives 30-day relationship memory + current Quant evidence and explains support/contradictions.
8. Checkpoint continuity is mandatory across workflow segments.

## DISABLED / NON-AUTHORITATIVE
- Caterpillar trading strategy
- Fibonacci strategy
- Direct Policy
- Three-Strategy Lab
- Entry/exit/re-entry/profit optimization heads
- Only-Profit research loop

Some legacy/support files remain because active collectors/monitor infrastructure imports shared utilities.
They must NOT become decision authorities for Local detection.

## IMPORTANT FILES
- src/research/hype_local_only/model.py
- src/research/hype_local_only/train_history.py
- src/research/hype_local_only/live_features.py
- src/research/hype_local_only/live_daemon.py
- src/research/hype_local_only/cortex_daemon.py
- src/research/hype_quant/feature_contract.py
- src/research/hype_quant/features.py
- src/research/hype_quant/raw_state.py
- src/research/hype_quant/start_local_cortex.sh
- src/research/hype_local_v5/labels.py
- src/research/hype_local_v5/resilient_capture.py
- src/research/hype_local_v5/context_capture.py
- src/research/local_116_30d/run_symbol.py
- src/research/hype_history_backfill/run.py
- src/research/hype_rest_relay/app.py
- src/research/hype_caterpillar_monitor/app.py (name is legacy; UI/payload is Local-Only)
- workflows/hype-local-only.yml
- workflows/hype-local-history-gap-backfill.yml

## DATA / MODELS
artifacts/latest_checkpoint/
- current Local-only model pickle, feature state, runtime state, relationship memory and reports.

artifacts/history_30d_local116/
- saved 30-day Local research dataset / candidate snapshots / compact bars / labels / manifest.

artifacts/historical_gaps/
- historical Bybit mark/index/OI/funding causal backfill.

artifacts/history_gap_oos/
- baseline vs enriched OOS comparison and promotion verdict.

artifacts/enriched_pretrain_rejected_or_candidate/
- enriched model candidate. DO NOT assume it is superior; inspect PROMOTION.json.
- Automatic promotion is gated; previous enriched attempts did not clearly beat baseline.

artifacts/latest_evidence/
- recent live status / events / training reports.

## CURRENT KNOWN STATE AT EXPORT TIME
- Historical micro labels: 2361.
- Full H1 pretrain is enabled.
- Live causal input coverage reached 86/86 supported predictive inputs.
- Live online labels have been accumulating on top of pretrain.
- Precision-first thresholds replaced the old recall-heavy thresholds.
- Historical mark/index/OI/funding were backfilled, but promotion is OOS-gated.
- Cortex had a local llama.cpp compatibility issue with response_format=json_object;
  current source contains a fallback request without JSON mode.
- Review docs/LIVE_STATUS_ISSUE_24.md for the exact most recent exported live state.

## CODEX PRIORITIES
1. Deep audit for target leakage. No target/eval/future information may enter predictive inputs.
2. Verify checkpoint restore/save is lossless across every workflow segment.
3. Improve OOS precision AND recall, especially LOW, without cherry-picking the OOS period.
4. Audit candidate generation so internal H1 locals are not missed and false candidates do not explode.
5. Audit historical-vs-live feature scale/name parity.
6. Verify the latest-candidate-per-hour live teacher assignment.
7. Fix/strengthen Cortex startup and schema handling; Cortex is analysis/meta-evidence, not an oracle.
8. Add walk-forward evaluation / calibration and probability reliability diagnostics.
9. Keep all live-only sources availability-aware; never fabricate historical L50/liquidation/latency.
10. Keep real order submission disabled until a separate explicit decision.

## SECURITY
No API secrets, Telegram tokens, private keys or exchange credentials are intentionally included.
Environment-variable NAMES may appear in source; secret VALUES must be supplied externally.
