# HYPE full-data local-to-local — 2026-11-13 checkpoint (artifact audit)
Status: research-only, no live orders. This checkpoint is a reproducibility and risk audit of existing reports, NOT a newly run full-microstructure replay.

## Sources checked
- research/hype_terminal_local_strategy/results/HYPE_EVERY_LOCAL_ROBUST_STRATEGY_2026-11-12.md
- research/hype_terminal_local_strategy/results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md
- research/hype_terminal_local_strategy/results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md
- research/hype_terminal_local_strategy/results/H1_EXHAUSTIVE_124_FEATURE_SEARCH_2026-11-11.md
- research/hype_full_micro_202607/results/LATEST_FEATURE_AVAILABILITY.json
- research/hype_full_micro_202607/results/RUN_STATUS.json
- research/hype_full_micro_202607/results/TRUE_LOCAL_SIGNATURES_LATEST.md
- research/hype_all_in_one/MANIFEST.json

## Critical findings
1. A prior report **already exists** for 322 strict H1 Locals and 7,753 candidate hypotheses. Its statement that all 322 received a causal *trading state* must NOT be rephrased as 322/322 correctly predicted terminal Locals. Its sequential execution has 411 trades and 29.12% closed-equity DD; this is not a low-risk result.
2. The reported frozen-entry asymmetric 1% loss-cut + 5x account exposure result is $100->$1,308.86 across five non-contiguous preserved regimes, max **closed** DD 29.36%, 67 sequential trades, 0.15% notional roundtrip costs. This is a *historical simulation claim*, not verified live/forward performance, and closed-only DD understates possible intratrade drawdown.
3. At 5x account exposure, a 0.15% notional round-trip cost is **0.75% account equity per round trip**, before funding/slippage. For 411 executions, turnover cost is material; fees must be charged per actual fill, not assumed away. A 1% adverse underlying move at 5x exposure is about 5% equity before costs, consistent with the reported -5.75% worst modeled trade. A 5bps structural stop with 5x exposure is only ~0.25% equity price risk before 0.75% round-trip costs, and can be dominated by spreads/slippage; verify order sequencing and gap handling.
4. The reported oracle exact-opposite-extreme $100->$15,540.70 is **not executable** and must never be included in performance rankings.
5. The frozen post-local minimal rule: 71 true / 0 false on history, but only ~22.4% coverage, with median opposite-extreme remaining move 2.046% and **61.2% median MFE giveback** on causal exit. Exit timing remains a measured bottleneck.
6. Exhaustive 124-slot search reports that a zero-FP 30m consensus caught 18 of 258 true terminal labels (~7% coverage). In-sample 25/25 conjunctions are explicitly overfit.
7. July feature availability manifest: 116 total contract points; 86 causal/quality; 28 teacher/eval; 2 metadata. **Three causal input IDs 111,112,113 missing** from its observed/derived coverage report. Source file counts: trades 631, orderbook 631, liquidations 337, OI 378, mark 378, ticker 378. These are *file counts*, not proof of aligned per-minute historical completeness.
8. July full-micro results/RUN_STATUS.json shows status FAILED, run_id 42660911066; do not interpret saved result summaries as evidence that this latest run succeeded.
9. July exact-extreme AUC for best single LOW feature 0.697, HIGH 0.638: no credible near-perfect exact-extreme universal predictor from any single field.
10. Existing master data is described by artifact HYPE-HISTORY-20260712-20261103-MASTER, plus local116-HYPE and HYPE-RICH-STRONG-* families; these binary ZIPs have not been materialized or independently replayed in this checkpoint. No assertion of complete data access.

## Next falsifiable experiment
Retrieve concrete workflow run IDs/artifact IDs for master, rich-day and every-local replay. Materialize historical timestamps and actual execution event stream. Run **frozen** Every-Local baseline and frozen 1% cut side-by-side with same capital constraints, actual available-time ordering, explicit spread/slippage/funding, intrabar worst-case stop-before-profit and gap fills. Report by month and independent period: true terminal locals, true-first/false-first/false negatives, trade count, net return, realized and mark-to-market max DD, 1%-price stop fills, liquidation distance, MFE capture/giveback, sensitivity to doubled/tripled slippage. Reject 5bps stop assumptions if realistic spread+slippage consume them. No new threshold tuning on October or May. Keep all production orders OFF.

## Limitation
This checkpoint audits pre-existing GitHub results and quantitative implications of stated assumptions; it does NOT claim to have executed the historical full-116 replay, verified ZIP contents, or proven 30% per month without liquidation.
