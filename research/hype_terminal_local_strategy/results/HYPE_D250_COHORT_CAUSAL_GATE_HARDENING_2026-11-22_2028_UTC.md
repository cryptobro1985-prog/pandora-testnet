# D250 full-cohort causal gate hardening — 2026-11-22 20:28 UTC

Research only; no trading authorization. Frozen detector, D250 thresholds, 67-trade baseline and rejected MFE overlays unchanged.

## Actual code change
Updated `research/hype_terminal_local_strategy/d250_full_cohort_gate.py` in the existing branch, commit `cb1182d8e0a06de8c323664861af08ceb3ccdaad`.

Three previously permitted or ambiguously reported synthetic manifest situations now fail closed:
1. `UNKNOWN_DATA` status was eligible when other fields happened to be populated; now `UNKNOWN_DATA_NOT_EXECUTION_ELIGIBLE`.
2. Feature bundle timestamp could be after D250 signal yet before the modeled entry; now `FEATURE_NOT_AVAILABLE_AT_SIGNAL`. A frozen D250 decision cannot retrospectively consume late features.
3. First opposite-local ledger event could be after the observation cutoff; now `OPPOSITE_EVENT_AFTER_CUTOFF`.

Added three deterministic adversarial self-test assertions (7 total). Test assertions were added but have **not been executed** in this connector-only run. Manifest eligibility is not tape verification or execution replay.

## New audit conclusion
The full-cohort gate still has no verified individual UTC trade tape, bid/ask fills, mark-price liquidation path, funding events, or independent forward execution results. Its own `MANIFEST_ELIGIBLE_NOT_VERIFIED` status is intentionally not authorization.

The previously published 71 accepted / 67 opposite-complete / 4 censored figures and 0 observed false-firsts remain **historical research claims**, not execution-tested outcomes. The existing 67-trade account curves cannot be transferred to 0.25–0.5% equity stop-risk without a complete chronological event ledger.

## Next reproducible analysis
Obtain the 71 frozen signal rows and matched immutable raw Bybit tapes with provenance hashes. Verify D250 timestamp, H1 K2 availability, feature-asof, same-side invalidation, bid/ask spread and depth, mark/last divergence, gap/slippage and actual fill feasibility, 4 censored MTM positions, and capital reservation. Run both sides separately on the same chronological cohort and cost model. Only then compare original 1% adverse cut with risk-normalized sizing and candidate profit-lock overlays. No fabricated missing microstructure, no oracle opposite extremes, no production changes.
