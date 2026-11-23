# D250 K2 knowledge gate patch — 2026-11-23 04:30 CET

Research-only; no orders, production changes, detector retraining, or changes to frozen D250 thresholds.

## Verified repository action
Updated `research/hype_terminal_local_strategy/d250_full_cohort_gate.py` in the existing branch, commit `e8b86065b974eaa6457f6a4df40f71fb94da307c`.

The prior gate used `opposite_ledger_first_utc <= entry_utc` as evidence that a *confirmed* opposite H1 Local was already known. This timestamp can be the retrospective extreme, whereas knowledge is acquired at `opposite_k2_available_utc`. The patch changes the pre-entry confirmed-opposite check to K2 <= entry; if an opposite extreme exists without K2 evidence, it blocks eligibility as `OPPOSITE_K2_UNVERIFIED`. OPEN_AT_CUTOFF now rejects opposite K2 only if K2 <= cutoff, and stop-vs-opposite ordering uses K2 instead of the retrospective extreme.

The frozen report also states that an opposite strict H1 Local occurring before D250 invalidates the candidate. Therefore this patch fixes **knowledge semantics**, not necessarily eligibility under the unchanged conservative candidate veto. A separate candidate-as-of ledger is required to prove any pre-D250 veto was causally knowable; do not interpret this change as authorizing such entries.

## Added deterministic assertions (code-level)
- opposite extreme at T+200, K2 at T+310, entry T+251: no confirmed-opposite-pre-entry label;
- same extreme, K2 at T+205: confirmed opposite pre-entry;
- open at cutoff T+600 with K2 T+660: not marked as a known confirmed opposite;
- opposite extreme with missing K2: ineligible, not inferred.

**Execution status:** connector update succeeded; synthetic self-tests have not been executed in this run. No real 71-row manifest or matched Bybit Public Trades/CVD/L50/OI/liquidations quote tape was loaded. No new monthly net equity, MTM DD, fill, stop, liquidation or MFE statistics can be claimed.

## Next reproducible step
Run `python research/hype_terminal_local_strategy/d250_full_cohort_gate.py --self-test`; obtain immutable 71 signal IDs and raw UTC event/quote manifest; validate SHA256 against raw bytes, then match each event to the first executable quote after causal K2. Preserve all 4 censored trajectories, compare unchanged 67-trade baseline against 0.25%/0.5% stop-risk alternatives using identical chronology, fees, funding and slippage. Reject unavailable microstructure instead of imputing zero. Preserve rejected MFE overlays pending independent forward evidence.
