# HYPE D250 opposite-event vs K2 availability: executable gate counterexample
Date: 2026-11-23. Research-only. No orders, no detector retraining.

## Confirmed source-code issue
Inspected `research/hype_terminal_local_strategy/d250_full_cohort_gate.py` (blob SHA 295cf5a7fb1414f8ae28b709f10bd4e77fb53d46) and the frozen walk-forward report (blob SHA 54865475546c10cd555199c65a2a81ce0f14aab7).

The gate's `opposite_ledger_first_utc` is compared directly against `entry_utc` and labeled `OPPOSITE_KNOWN_BEFORE_ENTRY` when first <= entry. However `opposite_k2_available_utc` is a separate field. The source's own causal-exit rule requires K2 availability; an opposite **extreme timestamp** cannot establish that a confirmed opposite Local was known at that time. In the CLOSED_OPPOSITE branch, `EXIT_BEFORE_OPPOSITE_AVAILABLE` similarly compares exit time to first event timestamp, while the stronger `EXIT_BEFORE_OPPOSITE_K2` comparison correctly uses K2.

### Deterministic counterexample (UTC, hypothetical only)
- original LOW extreme 2026-07-12T00:00:00Z; H1 confirmation 03:00Z
- D250 LONG signal 04:10Z; entry 04:11Z
- opposite HIGH extreme 04:00Z; opposite K2 available 06:00Z
- cutoff 08:00Z; causal opposite exit 06:01Z
- all other required fields valid and available; continuous event ledger from 00:00 to 08:00.

The existing code flags `OPPOSITE_KNOWN_BEFORE_ENTRY` solely because 04:00 <= 04:11, even though K2=06:00 > entry. Whether such a LONG should be *cancelled* because an opposite candidate extreme already occurred is a separate **strategy policy**, not proof that a confirmed opposite Local was known. A signal may be rejected conservatively, but the rejection reason must not conflate future-labeled event time with causal knowledge.

A second defect: for OPEN_AT_CUTOFF, any populated `opposite_k2_available_utc` triggers `OPEN_WITH_OPPOSITE_K2` without comparing its timestamp to cutoff. A future K2 value is lookahead metadata and must not be treated as known before cutoff.

## Minimal proposed patch / acceptance tests
Keep frozen D250 thresholds, entry side mapping, and baseline unchanged. Introduce distinct `opposite_extreme_utc`, `opposite_k2_available_utc`, and `opposite_candidate_asof_utc`. Reject on pre-entry confirmed opposite **only when K2 <= entry**. Separately apply an explicitly frozen conservative *candidate* veto if candidate information was actually available by entry. A CLOSED_OPPOSITE exit must be >= K2 and executable on the next available quote, never at the opposite extreme. OPEN_AT_CUTOFF requires no K2 <= cutoff; a K2 after cutoff must be censored rather than counted as a known opposite. Reject missing K2/coverage as UNKNOWN_DATA, never zero-impute.

Required synthetic assertions:
1. opposite extreme 04:00, K2 06:00, entry 04:11 -> not 'confirmed opposite known before entry'; candidate-veto separately evaluated.
2. same extreme, K2 04:05, entry 04:11 -> block confirmed-opposite pre-entry.
3. K2 06:00, attempted exit 05:59 -> block.
4. K2 06:00, exit 06:01 -> causally possible, execution still unverified.
5. cutoff 05:00, K2 06:00 -> OPEN censored, not a known confirmed opposite.
6. missing K2 with opposite extreme -> UNKNOWN_DATA; do not infer K2 from event time.

## Execution status / limitations
This iteration performed a direct code-level semantic audit with explicit timestamps, not an exchange-tape execution replay. No real 71-signal manifest or matched M1 Public Trades/L50/OI/liquidation quote tape was loaded; therefore no new trades, fill counts, MTM/closed DD, liquidation counts, monthly net equity or MFE retention are claimed. Prior 71/71 historical selection and 67-trade simulated baseline remain unmodified and are not evidence of live safety.

Next executable work: locate the 71 row-level timestamps and rich historical artifacts, hash and join by UTC, then evaluate original and low-risk sizing variants on identical fills and funding, preserving four censored signals and the original rejected exit overlays.
