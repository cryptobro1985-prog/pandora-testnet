# HYPE D250 — execution evidence inventory and replay blocker (2026-11-18 14:34 CET)

Research-only checkpoint; frozen detector, thresholds, rejected overlays, and production unchanged. No orders.

## Direct branch evidence verified this iteration

Read original `H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md`, `HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md`, `HYPE_UNIFIED_CAUSAL_ENTRY_MFE_V1.md`, and prior recovered-artifact audit directly from the requested GitHub branch. Listed actual contents of `research/hype_terminal_local_strategy/`, its `results/` directory (135 files), and `research/hype_12p_clean_core/`. The 12p directory contains only `MANIFEST.json` and `README.md`, not a committed 67-row execution ledger. The repository research root has many source builders and derived reports; presence of a report is not presence of raw ordered fills.

The 2026-11-17 recovered-artifact audit documents Actions artifact 13650399622 (70 MiB, 28 ZIP members) with 157,375 compact M1 rows across four periods, but **not** the immutable 67-trade ledger or private execution fills. It found five non-60-second transitions across four partitions; these require timestamp-level inspection, not blind acceptance of gap=false. Its July microstructure snapshots are candidate-level derived data, not ordered L50/trade execution tape. July rich raw manifest explicitly says raw_files_retained=false.

## New reproducibility conclusion

There are **three separate entities** that must never be joined by count or nearest extreme:

1. 71/71 D250 accepted first confirmations (historical signal validation, 22.4% coverage);
2. 67 finalized opposite-local geometries / 67 sequential modeled outcomes (four accepted signals may be censored, but exact mapping is not established);
3. 157,375 compact M1 rows (coarse price path, not fills or mark-trigger tape).

No per-trade UTC key mapping has been recovered in this run. Thus none of the 67 outcomes can be certified as a matched executable fill. An OHLC bar whose high and low both cross exit/stop levels is path ambiguous even if it has timestamps for its extremes; bid/ask and mark-trigger paths are distinct.

## Concrete next executable gate

Require a 67-row immutable manifest with `signal_id,side,anchor_utc,strict_h1_confirmed_utc,d250_feature_end_utc,decision_utc,entry_submit_utc,entry_fill_utc,entry_fill_price,stop_order_ack_utc,stop_trigger_basis,exit_decision_utc,exit_fill_utc,exit_fill_price,source_sha256`. Every signal must satisfy: strict pivot availability <= decision, D250 feature end <= decision, decision < submit <= fill, stop acknowledgement after entry submission, no same-side invalidation before entry, and no opposite-local oracle extreme as an exit timestamp. Reject missing fields instead of imputing.

Only then perform the identical chronological cohort for unchanged 3x/5x baseline and risk-based 0.25%/0.5% sizing, shared funding/fees/slippage, mark-to-market DD, stop-first ordering, 1% total portfolio stop-risk, and causal opposite-local exit. Missing L50/mark/funding means execution metrics are UNKNOWN, not zero. No new forward performance claim.

## Results this iteration

New **direct branch inventory and cross-source reconciliation** completed. Matched event replay: NOT COMPLETED (missing immutable ledger and ordered executable tape). New net PnL, monthly equity, MTM DD, MFE capture, fills and liquidation count: UNKNOWN. No threshold refitting, no synthetic trades passed off as historical evidence.

Source paths:
- research/hype_terminal_local_strategy/results/H1_POSTLOCAL_MINIMAL_RULE_WALKFORWARD_2026-11-12.md
- research/hype_terminal_local_strategy/results/HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md
- research/hype_terminal_local_strategy/results/HYPE_RECOVERED_ACTIONS_ARTIFACT_M1_AUDIT_2026-11-17_1330_CET.md
- research/hype_terminal_local_strategy/results/HYPE_RICH_REPLAY_SOURCE_RECOVERY_2026-11-15_0930_CET.md
