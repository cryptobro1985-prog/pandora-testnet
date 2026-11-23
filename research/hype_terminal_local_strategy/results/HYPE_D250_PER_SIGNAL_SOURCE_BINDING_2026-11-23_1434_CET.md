# D250 per-signal source binding: executed negative controls
Date: 2026-11-23 14:34 CET. Research only. Frozen thresholds, baseline, production and live orders unchanged.

## Source verification
Read the original frozen H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md and the current d250_cohort_raw_integrity_gate.py directly from the requested branch. Inspected the current results directory (255 entries), plus the direct-source and repository execution-data inventories. Prior inventory reports no committed matched 67-row execution ledger and no complete event-level bid/ask/mark tape. The 71 accepted signals are not 71 verified fills.

## New concrete executed analysis
Audited the current integrity gate: it verifies cohort ID membership against an ID list supplied **inside the same manifest** and verifies raw file hashes against hashes supplied **inside the same manifest**. Thus a self-consistent replacement of both cohort and manifest could pass, and the gate never checks that *each signal* is bound to the correct raw source. The current status name IDENTITY_AND_BYTES_ONLY must not be treated as an independently frozen cohort attestation.

Built and ran a local, research-only Python negative-control gate requiring (1) a separate precommitted cohort-byte SHA-256; (2) every row's explicit source_paths membership in a hash-verified source set; (3) nonempty side/decision/entry columns. Four synthetic assertions passed: intact synthetic cohort, substituted unverified per-row source, stale cohort commitment, and tampered raw source. No historical signals or fills were synthesized or scored. The new source-binding gate is a **provenance-only prerequisite**, not execution certification. In particular, an independently pinned commitment is only meaningful when archived before test execution; generating it from a new cohort on the fly is circular.

## Status and next actual replay
Real 71-row frozen manifest with externally precommitted hash: NOT RECOVERED. Per-signal matched quote/mark/public-trade tapes: NOT RECOVERED. Real matched fills verified: 0 (unverified, not zero historical executions). Monthly net equity, MTM DD, liquidation count, stop fills and MFE: UNKNOWN. No profit-lock overlay promoted.

Next: recover independent frozen 71-signal manifest and archived Actions event data; bind each signal to exact UTC windows and verified source hashes, then test causal LOW/LONG and HIGH/SHORT fills on the same immutable sample, cost and stop assumptions, risk 0.25-0.5% per trade and 1% aggregate. Never derive source hashes or signal IDs from the same candidate being certified.

Local executed command: python d250_signal_source_binding_gate.py --self-test
Output: PASS 4 provenance-only synthetic assertions; 0 real D250 executions validated.
