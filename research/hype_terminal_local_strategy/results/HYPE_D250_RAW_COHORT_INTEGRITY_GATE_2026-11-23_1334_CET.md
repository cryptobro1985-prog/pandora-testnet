# D250 raw cohort integrity checkpoint — 2026-11-23 13:34 CET

Research only. Frozen D250 thresholds, baseline, detector and production unchanged. No real orders.

## New concrete implementation
Added `research/hype_terminal_local_strategy/d250_cohort_raw_integrity_gate.py` to address three execution blockers identified in the prior checkpoint: unverified 64-character hashes, 71-row count without immutable membership, and raw data absence. It checks (a) exactly 71 nonempty unique signal IDs, (b) exact membership against an externally frozen list of 71 IDs, (c) actual SHA-256 bytes for each referenced raw source, (d) missing raw files and path traversal outside source root. Any failure blocks the identity/byte gate.

Run:
```bash
python research/hype_terminal_local_strategy/d250_cohort_raw_integrity_gate.py --self-test
python research/hype_terminal_local_strategy/d250_cohort_raw_integrity_gate.py signals.csv frozen_manifest.json --root /path/to/raw
```
Manifest schema: `{"signal_ids":["...71 frozen IDs..."],"source_files":[{"path":"relative/raw.bin","sha256":"actual SHA-256"}]}`.

## Actual test
Four synthetic scenarios passed in a local Python run: valid 71-ID cohort + matching source bytes; tampered source bytes rejected; substituted cohort ID rejected; source path escaping root rejected. The test does **not** use historical Bybit market tapes. The GitHub-hosted version includes the same four self-test scenarios; GitHub CI execution has not been verified.

## Important limitation
The gate cannot establish that the frozen 71 IDs are *authentic* unless the frozen list itself is sourced from the original walk-forward output and pinned by commit/hash. Matching source bytes alone cannot establish data coverage, quote freshness, bid/ask fills, funding, stop-gap outcomes, mark-to-market drawdown, liquidation or MFE protection. Do not interpret `IDENTITY_AND_BYTES_ONLY` as execution eligibility.

## Current status
No original immutable 71-ID list or matched Bybit M1 Public Trades/CVD/L50/liquidations/OI/mark-price tape was supplied to this run; therefore **0/71 signals have newly verified real executions**. No monthly net equity, closed/MTM DD, stop fills, liquidations or independent forward metrics are claimed.

Next: locate the actual original 71-ID cohort and source tapes, pin their provenance, run this gate, then build time-synchronized execution replay on the unchanged cohort with 0.25–0.5% equity stop-risk and <=1% portfolio stop-risk. Preserve previously rejected MFE overlays as rejected pending independent forward evidence.
