# HYPE strict execution evidence gate — 2026-11-15 14:30 CET

Research-only. Frozen D250 thresholds, 1% adverse cut and all previously rejected overlays remain unchanged. No detector training, production modification, live order, or new branch.

## Concrete new work
Inspected `trade_manifest_gate_research.py` and `stop_bar_mfe_bounds_research.py` in this branch. Implemented `strict_execution_provenance_research.py`, an additional gate for the existing manifest rather than a replacement for the frozen strategy. It rejects placeholder-only provenance, requires existing relative-path evidence files within a specified root, computes SHA-256 for each, checks declared timestamp coverage, requires a stop acceptance timestamp before stop trigger, distinguishes simulated from private exchange fills, and requires the correct opposite-local type plus an explicit first-causal-opposite verification flag. Self-test includes four assertions; **self-test has not been executed against recovered market artifacts in this iteration**.

## Why this matters
The old manifest's `EXECUTION_FIELDS_COMPLETE_NOT_LIQUIDATION_VERIFIED` can be returned with strings that are not file paths. The new gate returns `UNKNOWN_EVIDENCE_*` until the evidence is present, and only `EVIDENCE_FILES_HASHED_NOT_EXECUTION_OR_LIQUIDATION_VERIFIED` once file hashes and metadata pass. Even then it does **not** independently parse exchange payloads, establish genuine private fills, verify bid/ask depth, verify mark-based liquidation or guarantee no data gaps. A claimed timestamp range in metadata is not proof of event-level continuity. Source-file authenticity and event-level semantics need separate parsers and checks.

## Required next replay
Recover actual 67 closed + 4 unfinished signal records; match LOW->LONG and HIGH->SHORT separately to H1 confirmation availability and market tapes. Check M1 gaps, event ordering, mark path, L50 sequence continuity, stop order acknowledgement, bid/ask depth and realistic stop gap. On identical nonoverlapping capital schedules compare original 5x exposure baseline against 0.25% and 0.5% equity-risk budgets with total stop-risk <=1%; preserve all fees/funding/slippage assumptions. Compute monthly net equity, MTM/closed drawdowns, MFE captured/given back, fills, stop counts and liquidation status. UNKNOWN is not zero.

## Evidence status
No new matched trade execution replay or new net-return/DD/liquidation statistics were produced. This iteration improves the reproducible verification machinery and prevents treating placeholder manifests as validated execution. A zero observed false-first historical signal rate is not a zero execution-loss rate.
