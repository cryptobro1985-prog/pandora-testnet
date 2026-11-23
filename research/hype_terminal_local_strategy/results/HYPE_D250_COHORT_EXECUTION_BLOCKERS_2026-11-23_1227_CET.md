# D250 execution evidence audit — 2026-11-23 12:27 CET
Research only; no live orders. Existing frozen detector and baseline unchanged.

## Verified source inspection
Read the actual branch files:
- results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md
- d250_full_cohort_gate.py
- d250_quantity_precision_gate.py

Frozen thresholds: rev_atr > 2.0840049433824706; trade_ratio5 > 0.2727842248141979; flow15 < 0.4504731635235635. Historical 71/71 first accepted is a *classification* result, not 71 proven executable trades. 67 finalized opposite-local movements are not automatically 67 matched fills. Opposite K2 must be known before its use as exit.

## New concrete code-path audit findings
1. d250_full_cohort_gate.py's `source_sha256` validation checks **only 64 hexadecimal characters**, never recomputes the hash of source bytes. A plausible but wrong 64-char value can pass. Therefore `MANIFEST_ELIGIBLE_NOT_VERIFIED` must not be called raw-tape verified.
2. `same_side_ledger_coverage`, `opposite_ledger_coverage`, `quote_coverage` and `mark_coverage` are accepted as literal string `COMPLETE`, without independent comparison to actual timestamps or gap intervals. A missing market tape segment cannot be detected from that string alone.
3. The gate checks `len(rows)==71` but does not verify the 71 signal IDs against an immutable source cohort hash or sorted ID list. A swapped/duplicated cohort is partially caught (duplicate IDs) but a substituted 71-row cohort can still pass size and uniqueness checks.
4. The quantity gate uses caller-provided `step`, `min_qty`, `min_notional`, leverage and fee inputs. It does not independently validate the instrument metadata source, timestamp, risk tier or mark-price liquidation path. Its status `SIZE_FEASIBLE_LIQUIDATION_UNVERIFIED` correctly limits the claim.
5. Neither inspected gate runs an event-by-event bid/ask/mark fill replay or shared portfolio equity allocation. Their successful synthetic tests cannot establish monthly net equity, MTM DD, zero liquidation or MFE capture.

## Reproducible negative test design (not executed here)
- Feed 71 syntactically valid distinct rows with identical placeholder `source_sha256='a'*64` and `quote_coverage='COMPLETE'`. The validator has no source-byte input and cannot disprove these claims. This is a structural proof by inspection, not a claim that these rows passed all other validations.
- Swap one otherwise-valid row for a different signal with a new ID, keeping 71 rows: no immutable cohort membership comparison exists.
- Supply quantity step and minimum notional different from Bybit instrument metadata: the quantity function cannot detect the mismatch without an external verified snapshot.

## Required next actual replay, unchanged sample
1. Retrieve immutable 71 IDs with local extreme, H1 confirmation, D250 signal, features as-of and K2 availability; persist hashes of raw inputs and cohort IDs.
2. Map M1 Public Trades/CVD and, where genuinely available, L50, liquidations, OI, bid/ask and mark price. Mark missing spans UNKNOWN, never fill zeros.
3. Replay LONG and SHORT separately with latency, bid/ask fill, maker/taker fees, funding, partial fills, gaps, instrument lot filters and time-varying liquidation rules.
4. Compare frozen original baseline to 0.25%/0.5% stop-risk sizing (total <=1%), staged entry, mandatory stop and independently supported MFE control-transfer exits, preserving rejected overlays until fresh OOS evidence.
5. Single shared equity ledger: no overlapping capital reuse. Report monthly closed and MTM equity/DD, fill/stop counts, liquidations, MFE capture/giveback, and independent forward results.

## Result and decision
This iteration identifies **five concrete verification gaps** in actual repository code. No verified per-trade raw-tape replay was produced; no new performance or liquidation claim is justified. Do not promote to live. No production code, detector, thresholds or original baseline changed.
